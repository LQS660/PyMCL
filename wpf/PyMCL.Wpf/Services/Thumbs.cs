using System.Collections.Concurrent;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace PyMCL.Services;

/// <summary>
/// 列表缩略图。加载顺序与 Qt 端 widgets.ThumbnailTile 一致：
/// 内存缓存 → 桥上已有的磁盘缓存（thumb_path）→ 后台 ensure_thumb 下载。
/// 解码一律在线程池做完再 Freeze，UI 线程只负责贴图——搜索结果一页二三十行，
/// 在 UI 线程解码首屏就会明显掉帧。
/// </summary>
public static class Thumbs
{
    private const int MaxParallel = 4;

    private static readonly ConcurrentDictionary<string, BitmapSource> _mem = new();
    private static readonly ConcurrentDictionary<string, DateTime> _failed = new();
    private static readonly ConcurrentDictionary<string, Task<BitmapSource?>> _inflight = new();
    private static readonly SemaphoreSlim _gate = new(MaxParallel, MaxParallel);
    private static readonly TimeSpan FailCooldown = TimeSpan.FromMinutes(5);

    private static string Key(string url, int px) => url + "|" + px;

    /// <summary>已经在内存里的那张；没有返回 null，调用方先画字母底。</summary>
    public static BitmapSource? Cached(string url, int px) =>
        string.IsNullOrEmpty(url) ? null : _mem.GetValueOrDefault(Key(url, px));

    /// <summary>取一张缩略图。整个过程不碰 UI 线程；返回的位图已 Freeze。</summary>
    public static Task<BitmapSource?> LoadAsync(string url, int px)
    {
        if (string.IsNullOrWhiteSpace(url)) return Task.FromResult<BitmapSource?>(null);
        var key = Key(url, px);
        if (_mem.TryGetValue(key, out var hit)) return Task.FromResult<BitmapSource?>(hit);
        if (_failed.TryGetValue(url, out var when))
        {
            if (DateTime.UtcNow - when < FailCooldown) return Task.FromResult<BitmapSource?>(null);
            _failed.TryRemove(url, out _);
        }
        return _inflight.GetOrAdd(key, _ => FetchAsync(url, px, key));
    }

    private static async Task<BitmapSource?> FetchAsync(string url, int px, string key)
    {
        try
        {
            // 桥上可能已经下过：thumb_path 只查缓存位置，不联网，先问它一次。
            var local = await AppServices.Client.TryCallAsync<string>("thumb_path", new { url }, "") ?? "";
            var bmp = await DecodeAsync(local, px);
            if (bmp is null)
            {
                await _gate.WaitAsync().ConfigureAwait(false);
                try
                {
                    // ensure_thumb 会真的去下载并落盘，慢且可能超时，绝不能放 UI 线程。
                    local = await AppServices.Client.TryCallAsync<string>("ensure_thumb", new { url }, "") ?? "";
                }
                finally { _gate.Release(); }
                bmp = await DecodeAsync(local, px);
            }
            if (bmp is null)
            {
                _failed[url] = DateTime.UtcNow;
                return null;
            }
            _mem[key] = bmp;
            if (_mem.Count > 400) Trim();
            return bmp;
        }
        catch
        {
            _failed[url] = DateTime.UtcNow;
            return null;
        }
        finally { _inflight.TryRemove(key, out _); }
    }

    private static Task<BitmapSource?> DecodeAsync(string path, int px) => Task.Run<BitmapSource?>(() =>
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path)) return null;
        try
        {
            var bytes = File.ReadAllBytes(path);
            if (bytes.Length == 0) return null;
            var bmp = new BitmapImage();
            bmp.BeginInit();
            bmp.CacheOption = BitmapCacheOption.OnLoad;
            bmp.CreateOptions = BitmapCreateOptions.IgnoreColorProfile;
            bmp.DecodePixelWidth = Math.Max(16, px * 2);
            bmp.StreamSource = new MemoryStream(bytes);
            bmp.EndInit();
            bmp.Freeze();
            return bmp;
        }
        catch { return null; }
    });

    private static void Trim()
    {
        foreach (var k in _mem.Keys.Take(_mem.Count - 300)) _mem.TryRemove(k, out _);
    }
}

/// <summary>字母底 + 缩略图。图没到位时先显示首字母，到位后淡入换掉，不抖布局。</summary>
public sealed class ThumbTile : Border
{
    private readonly Image _img = new() { Stretch = Stretch.UniformToFill };
    private readonly TextBlock _letter;
    private int _token;

    public ThumbTile(string text, double size = 42, double radius = 10)
    {
        Width = Height = size;
        CornerRadius = new CornerRadius(radius);
        ClipToBounds = true;
        SetResourceReference(BackgroundProperty, "B.AccentSoft");
        _letter = Ui.Txt(string.IsNullOrEmpty(text) ? "?" : text.Substring(0, 1).ToUpperInvariant(),
            Math.Max(12, size * 0.4), true, "B.AccentDeep").Center();
        _letter.VerticalAlignment = VerticalAlignment.Center;
        var g = new Grid();
        g.Children.Add(_letter);
        g.Children.Add(_img);
        _img.Visibility = Visibility.Collapsed;
        Child = g;
    }

    /// <summary>换一张图。同一个控件被列表复用时靠 token 作废上一轮晚回来的结果。</summary>
    public void SetUrl(string? url)
    {
        var token = ++_token;
        var px = (int)Math.Max(16, Width);
        if (string.IsNullOrWhiteSpace(url))
        {
            Show(null);
            return;
        }
        var cached = Thumbs.Cached(url, px);
        if (cached != null)
        {
            Show(cached);
            return;
        }
        Show(null);
        _ = LoadAsync(url, px, token);
    }

    private async Task LoadAsync(string url, int px, int token)
    {
        var bmp = await Thumbs.LoadAsync(url, px);
        if (bmp is null || token != _token) return;
        await Dispatcher.InvokeAsync(() =>
        {
            if (token != _token) return;
            Show(bmp);
            Motion.Fade(_img, 1, 180);
        });
    }

    private void Show(BitmapSource? bmp)
    {
        _img.Source = bmp;
        _img.Opacity = bmp is null ? 0 : 1;
        _img.Visibility = bmp is null ? Visibility.Collapsed : Visibility.Visible;
        _letter.Visibility = bmp is null ? Visibility.Visible : Visibility.Collapsed;
    }
}

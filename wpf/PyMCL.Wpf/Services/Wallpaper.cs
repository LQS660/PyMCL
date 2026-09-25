using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Effects;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using System.Windows.Threading;
// System.Windows.Shapes 里也有个 Path，这里要的一直是文件路径那个
using IOPath = System.IO.Path;

namespace PyMCL.Services;

/// <summary>
/// 窗口背景层：静态图片与 mp4 动态壁纸，对齐 Qt 端 app/background.py。
///
/// 铺在整窗最底下；开了壁纸就把标题栏 / 侧栏 / 页面底色换成半透明版本，壁纸才透得出来，
/// 关掉时原样还回去（重新走 SetResourceReference，跟着主题走）。
///
/// 视频用 WPF 自带的 MediaElement（走 Media Foundation），不额外引第三方包——
/// 这个项目是「无第三方包」的体积优先策略，见 csproj 里那句注释。
/// 看不见的时候一律 Pause：最小化、切到别的窗口、把壁纸关掉，都不该让解码器在后台空转。
/// </summary>
public static class Wallpaper
{
    private static Grid? _host;
    private static Border? _chromeBar;
    private static Border? _side;
    private static Rectangle? _wash;
    private static readonly Image _still = new() { Stretch = Stretch.UniformToFill };
    private static MediaElement? _video;
    private static readonly Rectangle _dim = new();
    private static readonly DispatcherTimer _rotate = new();
    private static readonly Playlist _playlist = new();

    private static string _source = "";
    private static int _blur;
    private static int _dimPercent;
    private static bool _windowActive = true;

    /// <summary>壁纸没起来的原因，设置页拿它提示用户。</summary>
    public static string Error { get; private set; } = "";

    public static bool Active => !string.IsNullOrEmpty(_source);

    /// <summary>主窗口构造时把要接管的那几块交过来。</summary>
    public static void Attach(Grid host, Border chromeBar, Border side, Rectangle wash)
    {
        _host = host;
        _chromeBar = chromeBar;
        _side = side;
        _wash = wash;
        _still.Visibility = Visibility.Collapsed;
        _dim.Visibility = Visibility.Collapsed;
        _dim.IsHitTestVisible = false;
        _still.IsHitTestVisible = false;
        RenderOptions.SetBitmapScalingMode(_still, BitmapScalingMode.HighQuality);
        host.Children.Add(_still);
        host.Children.Add(_dim);
        _rotate.Tick += (_, _) => Advance();
    }

    /// <summary>窗口激活 / 最小化时调一下：看不见就别解码。</summary>
    public static void SetWindowActive(bool active)
    {
        _windowActive = active;
        SyncPlayback();
    }

    /// <summary>从后端设置里重新读一遍壁纸配置并应用。</summary>
    public static async Task ReloadAsync()
    {
        if (_host is null || !AppServices.Ready) return;
        var api = AppServices.Client;
        var image = (await api.TryCallAsync<string>("get_setting", new { key = "ui_background", @default = "" }, "") ?? "").Trim();
        var folder = (await api.TryCallAsync<string>("get_setting", new { key = "ui_background_folder", @default = "" }, "") ?? "").Trim();
        var shuffle = await api.TryCallAsync<bool>("get_setting", new { key = "ui_background_shuffle", @default = false }, false);
        var interval = await api.TryCallAsync<int>("get_setting", new { key = "ui_background_interval", @default = 10 }, 10);
        var blur = await api.TryCallAsync<int>("get_setting", new { key = "ui_background_blur", @default = 0 }, 0);
        var dim = await api.TryCallAsync<int>("get_setting", new { key = "ui_background_dim", @default = 0 }, 0);

        // 文件夹轮播优先：设了文件夹就按它挑图，单张那条让位。
        string path;
        if (folder.Length > 0 && _playlist.SetFolder(folder, shuffle))
        {
            path = _playlist.Current();
            _rotate.Interval = TimeSpan.FromMinutes(Clamp.Of(interval, 1, 1440));
            _rotate.Start();
        }
        else
        {
            _rotate.Stop();
            // 旧的预设色名（default / eye / warm / mist）不是路径，别当壁纸使
            path = FileKinds.IsWallpaper(image) ? image : "";
        }

        SetEffects(blur, dim);
        SetSource(path);
    }

    private static void Advance()
    {
        var next = _playlist.Advance();
        if (next.Length > 0) SetSource(next);
    }

    /// <summary>换壁纸。空路径 = 关掉，界面原样还给主题。</summary>
    public static void SetSource(string path)
    {
        path = (path ?? "").Trim();
        if (path == _source) return;
        _source = path;
        Error = "";
        StopVideo();
        _still.Source = null;
        _still.Visibility = Visibility.Collapsed;

        if (path.Length == 0)
        {
            ApplyChrome(false);
            return;
        }
        if (!File.Exists(path))
        {
            Error = L("文件不存在：") + path;
            _source = "";
            ApplyChrome(false);
            return;
        }

        if (FileKinds.IsVideo(path)) StartVideo(path);
        else
        {
            var bmp = LoadImage(path);
            if (bmp is null)
            {
                Error = L("图片读不出来：") + path;
                _source = "";
                ApplyChrome(false);
                return;
            }
            _still.Source = bmp;
            _still.Visibility = Visibility.Visible;
        }
        ApplyChrome(true);
    }

    /// <summary>可读性处理：blur=模糊半径 px，dim=遮罩浓度 %。遮罩刷主题底色而不是黑色。</summary>
    public static void SetEffects(int blur, int dim)
    {
        _blur = Clamp.Of(blur, 0, 40);
        _dimPercent = Clamp.Of(dim, 0, 80);
        // BlurEffect 在 WPF 里是 GPU 合成的，半径大了才有明显成本；
        // RenderingBias.Performance 让它走低精度那条路，动态壁纸每帧都要过一遍。
        Effect? effect = _blur > 0
            ? new BlurEffect { Radius = _blur, KernelType = KernelType.Gaussian, RenderingBias = RenderingBias.Performance }
            : null;
        _still.Effect = effect;
        if (_video != null) _video.Effect = effect;

        var dark = App.IsDark;
        var color = dark ? Color.FromRgb(0x10, 0x14, 0x18) : Color.FromRgb(0xFF, 0xFF, 0xFF);
        _dim.Fill = new SolidColorBrush(color) { Opacity = _dimPercent / 100.0 };
        _dim.Visibility = _dimPercent > 0 && Active ? Visibility.Visible : Visibility.Collapsed;
    }

    // ==================== 视频 ====================
    private static void StartVideo(string path)
    {
        var media = new MediaElement
        {
            LoadedBehavior = MediaState.Manual,
            UnloadedBehavior = MediaState.Manual,
            Stretch = Stretch.UniformToFill,
            IsMuted = true,          // 壁纸不该出声
            IsHitTestVisible = false,
            ScrubbingEnabled = false,
        };
        media.MediaFailed += (_, e) =>
        {
            Error = L("视频解码失败（系统可能缺 H.264 解码器）：") + e.ErrorException?.Message;
            StopVideo();
            ApplyChrome(false);
        };
        // 循环播放：WPF 的 MediaElement 没有 Loops，放完自己倒回去
        media.MediaEnded += (_, _) =>
        {
            media.Position = TimeSpan.Zero;
            media.Play();
        };
        if (_blur > 0)
            media.Effect = new BlurEffect { Radius = _blur, KernelType = KernelType.Gaussian, RenderingBias = RenderingBias.Performance };
        _video = media;
        _host!.Children.Insert(0, media);
        media.Source = new Uri(IOPath.GetFullPath(path));
        SyncPlayback();
    }

    private static void StopVideo()
    {
        var media = _video;
        _video = null;
        if (media is null) return;
        try
        {
            media.Stop();
            media.Close();
            media.Source = null;
        }
        catch { }
        _host?.Children.Remove(media);
    }

    /// <summary>看不见就暂停。关掉壁纸后这里不会再有播放器，CPU 自然回到 0。</summary>
    private static void SyncPlayback()
    {
        if (_video is null) return;
        try
        {
            if (_windowActive) _video.Play();
            else _video.Pause();
        }
        catch { }
    }

    private static BitmapSource? LoadImage(string path)
    {
        try
        {
            var bmp = new BitmapImage();
            bmp.BeginInit();
            bmp.CacheOption = BitmapCacheOption.OnLoad;
            bmp.CreateOptions = BitmapCreateOptions.IgnoreColorProfile;
            // 壁纸只需要铺满窗口，1080p 以上的原图解到 1920 宽就够，别整幅拉进内存
            bmp.DecodePixelWidth = 1920;
            bmp.UriSource = new Uri(IOPath.GetFullPath(path));
            bmp.EndInit();
            bmp.Freeze();
            return bmp;
        }
        catch { return null; }
    }

    // ==================== 界面让位 ====================
    /// <summary>
    /// 开壁纸时把标题栏 / 侧栏 / 页面底色换成半透明版本；关掉时重新绑回主题资源。
    /// 改的是 Border 自己的 Background 而不是 Opacity——后者会把上面的文字一起弄淡。
    /// </summary>
    private static void ApplyChrome(bool on)
    {
        if (_chromeBar is null || _side is null || _wash is null) return;
        _dim.Visibility = on && _dimPercent > 0 ? Visibility.Visible : Visibility.Collapsed;
        if (!on)
        {
            _chromeBar.SetResourceReference(Border.BackgroundProperty, "B.Chrome");
            _side.SetResourceReference(Border.BackgroundProperty, "B.Side");
            _wash.SetResourceReference(Shape.FillProperty, "B.PageWash");
            _wash.Opacity = 1;
            return;
        }
        _chromeBar.Background = Translucent("B.Chrome", 0.78);
        _side.Background = Translucent("B.Side", 0.72);
        // 页面底色整块让开，壁纸才是主角；卡片自己还有不透明底，文字照样看得清
        _wash.Opacity = 0;
    }

    private static Brush Translucent(string key, double alpha)
    {
        var baseColor = Application.Current.TryFindResource(key) is SolidColorBrush b
            ? b.Color
            : (App.IsDark ? Color.FromRgb(0x18, 0x1E, 0x1B) : Colors.White);
        return new SolidColorBrush(baseColor) { Opacity = alpha };
    }

    /// <summary>主题切换后重刷一遍：遮罩颜色与半透明底色都跟着主题走。</summary>
    public static void OnThemeChanged()
    {
        SetEffects(_blur, _dimPercent);
        ApplyChrome(Active);
    }

    public static void Shutdown()
    {
        _rotate.Stop();
        StopVideo();
    }

    /// <summary>文件夹轮播：顺序播记着走到哪儿，随机播不连着抽同一张。</summary>
    private sealed class Playlist
    {
        private string _folder = "";
        private bool _shuffle;
        private List<string> _files = new();
        private string _current = "";
        private readonly Random _rng = new();

        public bool SetFolder(string folder, bool shuffle)
        {
            folder = (folder ?? "").Trim();
            _shuffle = shuffle;
            if (folder != _folder)
            {
                _folder = folder;
                _current = "";
            }
            Scan();
            return _files.Count > 0;
        }

        /// <summary>每次换下一张都重扫一遍文件夹：用户往里丢新图、删掉当前这张，下一轮自然跟上。</summary>
        private void Scan()
        {
            if (_folder.Length == 0 || !Directory.Exists(_folder))
            {
                _files = new List<string>();
                return;
            }
            try
            {
                _files = Directory.EnumerateFiles(_folder)
                    .Where(FileKinds.IsWallpaper)
                    .OrderBy(p => p, StringComparer.OrdinalIgnoreCase)
                    .ToList();
            }
            catch { _files = new List<string>(); }
        }

        public string Current() =>
            _current.Length > 0 && File.Exists(_current) ? _current : Advance();

        public string Advance()
        {
            Scan();
            if (_files.Count == 0) return _current = "";
            if (_files.Count == 1) return _current = _files[0];
            if (_shuffle)
            {
                string pick;
                do { pick = _files[_rng.Next(_files.Count)]; } while (pick == _current);
                return _current = pick;
            }
            var idx = _files.IndexOf(_current);
            return _current = _files[(idx < 0 ? 0 : idx + 1) % _files.Count];
        }
    }
}

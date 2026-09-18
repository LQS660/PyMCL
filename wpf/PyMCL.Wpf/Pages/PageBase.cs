using System.Windows;
using System.Windows.Controls;
using PyMCL.Services;

namespace PyMCL.Pages;

public abstract class PageBase : UserControl
{
    private bool _loaded;

    public string Id { get; set; } = "";
    public virtual string Title => "";

    protected static BridgeClient Api => AppServices.Client;
    protected static MainWindow? Win => AppServices.Window;

    protected PageBase()
    {
        Focusable = false;
        HorizontalAlignment = HorizontalAlignment.Stretch;
        VerticalAlignment = VerticalAlignment.Stretch;
    }

    private Task? _inflight;

    /// <summary>
    /// 保证这一页加载过一次。已经在加载时**返回同一个在飞的任务**，而不是立刻返回——
    /// 后者会让第二个调用方以为加载完了，拿着一个半成品页面继续往下走
    /// （运行期冒烟就是这么被骗过去的：Navigate 自己先起了一次，冒烟再调就秒回）。
    /// </summary>
    public Task EnsureLoadedAsync()
    {
        if (_loaded) return Task.CompletedTask;
        return _inflight ??= LoadOnceAsync();
    }

    private async Task LoadOnceAsync()
    {
        try
        {
            await LoadAsync();
            _loaded = true;
        }
        catch (Exception ex)
        {
            // 这里吞掉的异常冒不到 UI 线程的未处理钩子上，冒烟时得单独记一笔
            Smoke.Note(string.IsNullOrEmpty(Id) ? GetType().Name : Id, ex.ToString());
            Toast(L("加载失败"), ex.Message, ToastKind.Error);
        }
        finally { _inflight = null; }
    }

    protected virtual Task LoadAsync() => Task.CompletedTask;

    /// <summary>后端 ui_changed / 用户按 F5 时刷新。未加载过的页面不做事。</summary>
    public virtual Task RefreshAsync() => _loaded ? LoadAsync() : Task.CompletedTask;

    public virtual void OnEvent(BridgeEvent ev) { }

    public virtual void OnShown() { }

    public virtual void OnHidden() { }

    protected static void Toast(string title, string body = "", ToastKind kind = ToastKind.Info) =>
        AppServices.Window?.Toast(title, body, kind);

    /// <summary>
    /// 全工程 async void 事件处理器的**唯一**出口：包一层异常兜底（async void 里漏出来的异常会把整个应用崩掉），
    /// 同时向冒烟登记「有一个异步操作在飞」——Smoke 点完按钮就是等这个计数归零再判成败、再截图，
    /// 处理器里抛出来的异常也记进 issues；不走这里的 async void，冒烟看到的就是「点了、没报错」的空数字。
    /// 静态的 Dialogs / MainWindow 也用这一个（public），别再各自写一份 try/catch 的 async void。
    /// 主动取消（切页、重搜把上一次掐掉）不算失败：不提示、不记。
    /// </summary>
    public static async void Run(Func<Task> work, string? failTitle = null)
    {
        var op = Smoke.OperationStarted();
        try { await work(); }
        catch (OperationCanceledException) { }
        catch (Exception ex)
        {
            Smoke.Note("handler", ex.ToString());
            AppServices.Window?.Toast(failTitle ?? L("操作失败"), ex.Message, ToastKind.Error);
        }
        finally { Smoke.OperationFinished(op); }
    }

    /// <summary>
    /// 把这一页变成拖放落点。Qt 那边每个子页各自 setAcceptDrops（catalog_page / mod_page /
    /// download_hub 共五处），道理一样：文件落在哪一页，就该用那一页正在操作的实例和版本。
    /// WPF 的路由事件本来就会冒泡到主窗口，这里先接住并给上下文，接不住的再交给主窗口那条通路。
    /// </summary>
    protected void EnableDrop(Func<FileDrop.DropContext> context)
    {
        AllowDrop = true;
        // 走 Preview（隧道）而不是冒泡：页面里的 TextBox 默认自己收拖放，会把文件路径当文字插进去。
        // 隧道是 Window → Page → TextBox，页面在这一段先接住；主窗口那条通路仍挂在冒泡上，
        // 于是「落在页面上」走页面上下文，「落在侧栏等页面之外」才退回主窗口的默认实例。
        PreviewDragOver += (_, e) =>
        {
            if (!e.Data.GetDataPresent(DataFormats.FileDrop)) return;
            e.Effects = DragDropEffects.Copy;
            e.Handled = true;
        };
        PreviewDrop += (_, e) =>
        {
            if (!e.Data.GetDataPresent(DataFormats.FileDrop)) return;
            if (e.Data.GetData(DataFormats.FileDrop) is not string[] paths || paths.Length == 0) return;
            e.Handled = true;
            var win = Win;
            if (win is null) return;
            Run(() => FileDrop.HandleAsync(win, paths, context()), L("拖放处理失败"));
        };
    }

    protected static Panel Body(params UIElement?[] kids)
    {
        var v = Ui.V(14, kids);
        v.Margin = new Thickness(26, 20, 26, 20);
        return v;
    }

    protected static SmoothScroll ScrollBody(params UIElement?[] kids)
    {
        var v = Ui.V(14, kids);
        v.Margin = new Thickness(26, 20, 26, 22);
        return Ui.Scroll(v);
    }
}

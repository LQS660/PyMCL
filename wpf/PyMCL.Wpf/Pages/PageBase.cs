using System.Windows;
using System.Windows.Controls;
using PyMCL.Services;

namespace PyMCL.Pages;

public abstract class PageBase : UserControl
{
    private bool _loaded;
    private bool _loading;

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

    public async Task EnsureLoadedAsync()
    {
        if (_loaded || _loading) return;
        _loading = true;
        try
        {
            await LoadAsync();
            _loaded = true;
        }
        catch (Exception ex)
        {
            Toast("加载失败", ex.Message, ToastKind.Error);
        }
        finally { _loading = false; }
    }

    protected virtual Task LoadAsync() => Task.CompletedTask;

    /// <summary>后端 ui_changed / 用户按 F5 时刷新。未加载过的页面不做事。</summary>
    public virtual Task RefreshAsync() => _loaded ? LoadAsync() : Task.CompletedTask;

    public virtual void OnEvent(BridgeEvent ev) { }

    public virtual void OnShown() { }

    public virtual void OnHidden() { }

    protected static void Toast(string title, string body = "", ToastKind kind = ToastKind.Info) =>
        AppServices.Window?.Toast(title, body, kind);

    /// <summary>包一层异常兜底，避免 async void 事件把整个应用崩掉。</summary>
    protected static async void Run(Func<Task> work, string failTitle = "操作失败")
    {
        try { await work(); }
        catch (Exception ex) { AppServices.Window?.Toast(failTitle, ex.Message, ToastKind.Error); }
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

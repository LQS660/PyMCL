using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;

namespace PyMCL.Services;

public enum ToastKind { Info, Success, Warning, Error }

/// <summary>窗内模态层。不开新 Window，弹窗与主窗同一块画布，转场才能连贯。</summary>
public static class Dlg
{
    public static Grid? Host { get; set; }

    public sealed class Layer
    {
        public required Grid Root { get; init; }
        public required Border Card { get; init; }
        public required Action Close { get; init; }
    }

    public static bool AnyOpen => Host is { Children.Count: > 0 };

    private static Layer Push(UIElement card, Action? onDismiss, bool dismissable = true,
        bool smokeAutoAnswer = true)
    {
        var host = Host ?? throw new InvalidOperationException(L("对话层未初始化"));
        var mask = new Border { Opacity = 0 };
        mask.SetResourceReference(Border.BackgroundProperty, "B.Mask");
        var wrap = new Grid();
        wrap.Children.Add(mask);
        var holder = new Grid
        {
            HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(24),
        };
        holder.Children.Add(card);
        wrap.Children.Add(holder);
        host.Children.Add(wrap);
        host.Visibility = Visibility.Visible;

        Motion.Fade(mask, 1, 150);
        Motion.PopIn(holder);

        void Close()
        {
            if (!host.Children.Contains(wrap)) return;
            Motion.Fade(mask, 0, 130);
            Motion.PopOut(holder, () =>
            {
                host.Children.Remove(wrap);
                if (host.Children.Count == 0) host.Visibility = Visibility.Collapsed;
            });
        }

        if (dismissable)
            mask.MouseLeftButtonDown += (_, _) =>
            {
                onDismiss?.Invoke();
                Close();
            };
        wrap.Focusable = true;
        wrap.KeyDown += (_, e) =>
        {
            if (e.Key != Key.Escape || !dismissable) return;
            onDismiss?.Invoke();
            Close();
            e.Handled = true;
        };
        if (!Smoke.Active) wrap.Loaded += (_, _) => wrap.Focus();
        // 冒烟模式下替用户把它点掉：这些框返回的都是「没人点就永远不完成」的 Task，
        // 无人值守里开一个就挂死一轮。钩子只在 Smoke.Active 时生效，生产路径一行行为不变。
        if (Smoke.Active && smokeAutoAnswer) Smoke.AutoAnswerDialog(card, () => { onDismiss?.Invoke(); Close(); });
        return new Layer { Root = wrap, Card = card as Border ?? new Border(), Close = Close };
    }

    private static Border Shell(string title, UIElement body, UIElement? footer, double width)
    {
        var head = Ui.G(null, "*,Auto");
        head.Add(Ui.H2(title).VCenter(), 0, 0);
        var content = Ui.V(14, head, body);
        if (footer != null) content.Children.Add(footer);
        var card = new Border
        {
            CornerRadius = new CornerRadius(14),
            Padding = new Thickness(22, 18, 22, 18),
            BorderThickness = new Thickness(1),
            MaxWidth = width,
            MinWidth = Math.Min(width, 380),
            Child = content,
        };
        card.SetResourceReference(Border.BackgroundProperty, "B.Paper");
        card.SetResourceReference(Border.BorderBrushProperty, "B.Line");
        Motion.Shadow(card, 40, 0.28, 10);
        return card;
    }

    // 默认按钮文案不能写成常量默认值（L() 不是编译期常量），null 表示「用本语言的确定 / 取消」。
    public static Task<bool> Confirm(string title, string body, string? ok = null, string? cancel = null, bool danger = false)
        => Ask(title, Ui.Muted(body).Wrap().MinW(320), ok, cancel, danger);

    public static Task<bool> Ask(string title, UIElement body, string? ok = null, string? cancel = null,
        bool danger = false, double width = 520)
    {
        var tcs = new TaskCompletionSource<bool>();
        var okBtn = Ui.Btn(ok ?? L("确定"), danger ? BtnKind.Danger : BtnKind.Primary);
        var cancelBtn = Ui.Btn(cancel ?? L("取消"));
        var footer = Ui.H(8, cancelBtn, okBtn).Right();
        var card = Shell(title, body, footer, width);
        Layer? layer = null;
        layer = Push(card, () => tcs.TrySetResult(false));
        okBtn.Click += (_, _) =>
        {
            tcs.TrySetResult(true);
            layer!.Close();
        };
        cancelBtn.Click += (_, _) =>
        {
            tcs.TrySetResult(false);
            layer!.Close();
        };
        return tcs.Task;
    }

    public static Task Alert(string title, string body, double width = 520)
    {
        var tcs = new TaskCompletionSource<bool>();
        var okBtn = Ui.Btn(L("知道了"), BtnKind.Primary);
        var text = new TextBox
        {
            Text = body,
            IsReadOnly = true,
            BorderThickness = new Thickness(0),
            Background = Brushes.Transparent,
            TextWrapping = TextWrapping.Wrap,
            MaxHeight = 380,
            VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
            FontSize = 13,
        };
        text.SetResourceReference(Control.ForegroundProperty, "B.InkSoft");
        var card = Shell(title, text, Ui.H(8, okBtn).Right(), width);
        var layer = Push(card, () => tcs.TrySetResult(true));
        okBtn.Click += (_, _) =>
        {
            tcs.TrySetResult(true);
            layer.Close();
        };
        return tcs.Task;
    }

    public static Task<string?> Prompt(string title, string label, string initial = "", string placeholder = "")
    {
        var tcs = new TaskCompletionSource<string?>();
        var input = Ui.Input(placeholder, initial).MinW(340);
        var body = Ui.V(6, Ui.Muted(label), input);
        var okBtn = Ui.Btn(L("确定"), BtnKind.Primary);
        var cancelBtn = Ui.Btn(L("取消"));
        var card = Shell(title, body, Ui.H(8, cancelBtn, okBtn).Right(), 460);
        Layer? layer = null;
        layer = Push(card, () => tcs.TrySetResult(null));
        void Ok()
        {
            tcs.TrySetResult(input.Text?.Trim() ?? "");
            layer!.Close();
        }
        okBtn.Click += (_, _) => Ok();
        cancelBtn.Click += (_, _) =>
        {
            tcs.TrySetResult(null);
            layer!.Close();
        };
        input.KeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter) Ok();
        };
        input.Loaded += (_, _) =>
        {
            input.Focus();
            input.SelectAll();
        };
        return tcs.Task;
    }

    /// <summary>自定义内容 + 自定义按钮。返回被点按钮的下标，取消/关闭返回 -1。</summary>
    public static Task<int> Choose(string title, UIElement body, string[] options, double width = 560, bool dismissable = true)
    {
        var tcs = new TaskCompletionSource<int>();
        var row = Ui.H(8).Right();
        var card = Shell(title, body, row, width);
        Layer? layer = null;
        layer = Push(card, () => tcs.TrySetResult(-1), dismissable);
        for (var i = 0; i < options.Length; i++)
        {
            var idx = i;
            var b = Ui.Btn(options[i], i == options.Length - 1 ? BtnKind.Primary : BtnKind.Normal);
            b.Click += (_, _) =>
            {
                tcs.TrySetResult(idx);
                layer!.Close();
            };
            row.Children.Add(b);
        }
        return tcs.Task;
    }

    /// <summary>表单式弹窗：内容自定，点确定时用 collect 取值；返回 null 表示取消。</summary>
    public static async Task<T?> Form<T>(string title, UIElement body, Func<T> collect,
        string? ok = null, double width = 560) where T : class
    {
        T? result = null;
        var tcs = new TaskCompletionSource<bool>();
        var okBtn = Ui.Btn(ok ?? L("保存"), BtnKind.Primary);
        var cancelBtn = Ui.Btn(L("取消"));
        var card = Shell(title, body, Ui.H(8, cancelBtn, okBtn).Right(), width);
        Layer? layer = null;
        layer = Push(card, () => tcs.TrySetResult(false));
        okBtn.Click += (_, _) =>
        {
            try { result = collect(); }
            catch (Exception ex)
            {
                AppServices.Toast(L("填写有误"), ex.Message, ToastKind.Warning);
                Motion.Shake(card);
                return;
            }
            tcs.TrySetResult(true);
            layer!.Close();
        };
        cancelBtn.Click += (_, _) =>
        {
            tcs.TrySetResult(false);
            layer!.Close();
        };
        await tcs.Task;
        return result;
    }

    /// <summary>无按钮的大内容弹窗（日志/详情/管理器）。</summary>
    public static Layer Panel(string title, UIElement body, double width = 720, Action? onClose = null)
    {
        var closeBtn = Ui.IconBtn(Ico.Close, L("关闭"));
        var head = Ui.G(null, "*,Auto");
        head.Add(Ui.H2(title).VCenter(), 0, 0);
        head.Add(closeBtn, 0, 1);
        var card = new Border
        {
            CornerRadius = new CornerRadius(14),
            Padding = new Thickness(20, 16, 20, 18),
            BorderThickness = new Thickness(1),
            MaxWidth = width,
            MinWidth = Math.Min(width, 420),
            Child = Ui.V(12, head, body),
        };
        card.SetResourceReference(Border.BackgroundProperty, "B.Paper");
        card.SetResourceReference(Border.BorderBrushProperty, "B.Line");
        Motion.Shadow(card, 40, 0.28, 10);
        var layer = Push(card, onClose);
        closeBtn.Click += (_, _) =>
        {
            onClose?.Invoke();
            layer.Close();
        };
        return layer;
    }

    /// <summary>阻塞式忙碌遮罩，using 作用域结束自动关。</summary>
    public static IDisposable Busy(string? text = null)
    {
        text ??= L("处理中…");
        var ring = Ui.Prog();
        ring.IsIndeterminate = true;
        ring.Width = 220;
        var card = new Border
        {
            CornerRadius = new CornerRadius(12),
            Padding = new Thickness(24, 20, 24, 20),
            Child = Ui.V(12, Ui.Txt(text, 13).Center(), ring),
        };
        card.SetResourceReference(Border.BackgroundProperty, "B.Paper");
        Motion.Shadow(card, 30, 0.22, 6);
        var layer = Push(card, null, dismissable: false, smokeAutoAnswer: false);
        return new Scope(layer.Close);
    }

    private sealed class Scope(Action close) : IDisposable
    {
        private int _done;
        public void Dispose()
        {
            if (Interlocked.Exchange(ref _done, 1) == 0) close();
        }
    }

    // ---------------- 系统文件对话框 ----------------
    public static string? PickFile(string filter, string? title = null)
    {
        title ??= L("选择文件");
        if (Smoke.Active) { Smoke.AutoCancelSystemDialog(title); return null; }
        var d = new Microsoft.Win32.OpenFileDialog { Filter = filter, Title = title, CheckFileExists = true };
        return d.ShowDialog() == true ? d.FileName : null;
    }

    public static string[]? PickFiles(string filter, string? title = null)
    {
        title ??= L("选择文件");
        if (Smoke.Active) { Smoke.AutoCancelSystemDialog(title); return null; }
        var d = new Microsoft.Win32.OpenFileDialog { Filter = filter, Title = title, Multiselect = true };
        return d.ShowDialog() == true ? d.FileNames : null;
    }

    public static string? SaveFile(string filter, string name, string? title = null)
    {
        title ??= L("保存到");
        if (Smoke.Active) { Smoke.AutoCancelSystemDialog(title); return null; }
        var d = new Microsoft.Win32.SaveFileDialog { Filter = filter, FileName = name, Title = title };
        return d.ShowDialog() == true ? d.FileName : null;
    }

    public static string? PickFolder(string? title = null)
    {
        title ??= L("选择文件夹");
        if (Smoke.Active) { Smoke.AutoCancelSystemDialog(title); return null; }
        var d = new Microsoft.Win32.OpenFolderDialog { Title = title };
        return d.ShowDialog() == true ? d.FolderName : null;
    }
}

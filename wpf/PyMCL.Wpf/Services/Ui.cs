using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace PyMCL.Services;

public enum BtnKind { Primary, Soft, Normal, Ghost, Danger, Chip, Icon }

/// <summary>Segoe MDL2 Assets 字形。用系统字体当图标，零资源体积。</summary>
public static class Ico
{
    public const string Play = "\uE768";
    public const string Stop = "\uE71A";
    public const string Rocket = "\uE7C1";
    public const string Home = "\uE80F";
    public const string Box = "\uE7B8";
    public const string Download = "\uE896";
    public const string Cloud = "\uE753";
    public const string Gear = "\uE713";
    public const string Coffee = "\uEC32";
    public const string User = "\uE77B";
    public const string Robot = "\uE99A";
    public const string Wifi = "\uE701";
    public const string Server = "\uE968";
    public const string Clock = "\uE823";
    public const string Chat = "\uE8BD";
    public const string Folder = "\uE8B7";
    public const string Trash = "\uE74D";
    public const string Refresh = "\uE72C";
    public const string Search = "\uE721";
    public const string Add = "\uE710";
    public const string Check = "\uE73E";
    public const string Close = "\uE711";
    public const string Chevron = "\uE70D";
    public const string ChevronRight = "\uE76C";
    public const string ChevronLeft = "\uE76B";
    public const string Star = "\uE734";
    public const string StarFill = "\uE735";
    public const string List = "\uE8FD";
    public const string Palette = "\uE790";
    public const string Moon = "\uE708";
    public const string Sun = "\uE706";
    public const string Pin = "\uE718";
    public const string Link = "\uE71B";
    public const string Copy = "\uE8C8";
    public const string Edit = "\uE70F";
    public const string Save = "\uE74E";
    public const string Warning = "\uE7BA";
    public const string Info = "\uE946";
    public const string Error = "\uEA39";
    public const string Success = "\uEC61";
    public const string Grid = "\uE80A";
    public const string Package = "\uE7B8";
    public const string Shader = "\uE706";
    public const string World = "\uE909";
    public const string Data = "\uE8F1";
    public const string Image = "\uEB9F";
    public const string Puzzle = "\uEA86";
    public const string Bug = "\uEBE8";
    public const string Send = "\uE724";
    public const string More = "\uE712";
    public const string Open = "\uE8A7";
    public const string Sort = "\uE8CB";
    public const string Filter = "\uE71C";
    public const string Shield = "\uEA18";
    public const string Broom = "\uEA99";
    public const string Import = "\uE8B5";
    public const string Export = "\uEDE1";
    public const string Play2 = "\uF5B0";
    public const string Lightning = "\uE945";
    public const string Heart = "\uEB51";
    public const string Book = "\uE8F4";
    public const string Camera = "\uE722";
    public const string Repair = "\uE90F";
    public const string Windowed = "\uE737";
    public const string Minimize = "\uE921";
    public const string Maximize = "\uE922";
    public const string Restore = "\uE923";
    public const string CloseWin = "\uE8BB";
}

/// <summary>带间距的堆叠面板。WPF 原生 StackPanel 没有 Spacing，这里补上。</summary>
public sealed class SPanel : Panel
{
    public Orientation Orientation { get; set; } = Orientation.Vertical;
    public double Spacing { get; set; } = 8;

    protected override Size MeasureOverride(Size available)
    {
        double w = 0, h = 0;
        var vis = 0;
        var childAvail = Orientation == Orientation.Vertical
            ? new Size(available.Width, double.PositiveInfinity)
            : new Size(double.PositiveInfinity, available.Height);
        foreach (UIElement c in InternalChildren)
        {
            c.Measure(childAvail);
            if (c.Visibility == Visibility.Collapsed) continue;
            vis++;
            if (Orientation == Orientation.Vertical)
            {
                w = Math.Max(w, c.DesiredSize.Width);
                h += c.DesiredSize.Height;
            }
            else
            {
                h = Math.Max(h, c.DesiredSize.Height);
                w += c.DesiredSize.Width;
            }
        }
        var gap = Math.Max(0, vis - 1) * Spacing;
        if (Orientation == Orientation.Vertical) h += gap; else w += gap;
        return new Size(
            double.IsInfinity(available.Width) ? w : Math.Min(w, Math.Max(w, available.Width)),
            double.IsInfinity(available.Height) ? h : h);
    }

    protected override Size ArrangeOverride(Size final)
    {
        double pos = 0;
        foreach (UIElement c in InternalChildren)
        {
            if (c.Visibility == Visibility.Collapsed) continue;
            if (Orientation == Orientation.Vertical)
            {
                c.Arrange(new Rect(0, pos, final.Width, c.DesiredSize.Height));
                pos += c.DesiredSize.Height + Spacing;
            }
            else
            {
                c.Arrange(new Rect(pos, 0, c.DesiredSize.Width, final.Height));
                pos += c.DesiredSize.Width + Spacing;
            }
        }
        return final;
    }
}

/// <summary>惯性平滑滚动。原生 ScrollViewer 按行跳，滚起来发涩。</summary>
public sealed class SmoothScroll : ScrollViewer
{
    public static readonly DependencyProperty OffsetProperty = DependencyProperty.Register(
        nameof(Offset), typeof(double), typeof(SmoothScroll),
        new PropertyMetadata(0.0, (d, e) => ((SmoothScroll)d).ScrollToVerticalOffset((double)e.NewValue)));

    public double Offset
    {
        get => (double)GetValue(OffsetProperty);
        set => SetValue(OffsetProperty, value);
    }

    private double _target = -1;

    public SmoothScroll()
    {
        VerticalScrollBarVisibility = ScrollBarVisibility.Auto;
        HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled;
        CanContentScroll = false;
        PanningMode = PanningMode.VerticalOnly;
    }

    protected override void OnMouseWheel(MouseWheelEventArgs e)
    {
        if (!Motion.Enabled || ScrollableHeight <= 0)
        {
            base.OnMouseWheel(e);
            return;
        }
        e.Handled = true;
        var start = _target < 0 ? VerticalOffset : _target;
        var next = Math.Clamp(start - e.Delta * 0.95, 0, ScrollableHeight);
        _target = next;
        var an = new DoubleAnimation(VerticalOffset, next, TimeSpan.FromMilliseconds(230))
        {
            EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut },
        };
        an.Completed += (_, _) => _target = -1;
        BeginAnimation(OffsetProperty, an);
    }
}

public static class Fmt
{
    public static string Downloads(long n) => n switch
    {
        >= 100_000_000 => (n / 100_000_000.0).ToString("0.#", CultureInfo.InvariantCulture) + " 亿",
        >= 10_000 => (n / 10_000.0).ToString("0.#", CultureInfo.InvariantCulture) + " 万",
        > 0 => n.ToString(CultureInfo.InvariantCulture),
        _ => "—",
    };

    public static string Size(long bytes) => bytes switch
    {
        >= 1L << 30 => (bytes / (double)(1L << 30)).ToString("0.##") + " GB",
        >= 1L << 20 => (bytes / (double)(1L << 20)).ToString("0.#") + " MB",
        >= 1L << 10 => (bytes / (double)(1L << 10)).ToString("0.#") + " KB",
        _ => bytes + " B",
    };

    public static string Duration(long seconds)
    {
        if (seconds <= 0) return "0 分钟";
        var h = seconds / 3600;
        var m = seconds % 3600 / 60;
        if (h >= 24) return $"{h / 24} 天 {h % 24} 小时";
        if (h > 0) return $"{h} 小时 {m} 分钟";
        return $"{Math.Max(1, m)} 分钟";
    }

    /// <summary>后端进度文案形如 "补全依赖库 (3/9)  |  12.4 MB/s"，拆成状态 + 速度。</summary>
    public static void SplitMsg(string? msg, out string status, out string speed)
    {
        status = msg ?? "";
        speed = "";
        if (string.IsNullOrEmpty(status)) return;
        var i = status.IndexOf("  |  ", StringComparison.Ordinal);
        if (i < 0) return;
        speed = status[(i + 5)..].Trim();
        status = status[..i].Trim(' ', '·');
    }
}

public static class Ui
{
    public static Style S(string key) => (Style)Application.Current.FindResource(key);
    public static Brush Res(string key) => (Brush)Application.Current.FindResource(key);

    // ---------------- 文本 ----------------
    public static TextBlock Txt(string text = "", double size = 13, bool bold = false, string? fg = null)
    {
        var t = new TextBlock { Text = text, FontSize = size, TextWrapping = TextWrapping.NoWrap };
        if (bold) t.FontWeight = FontWeights.SemiBold;
        if (fg != null) t.SetResourceReference(TextBlock.ForegroundProperty, fg);
        return t;
    }

    public static TextBlock H1(string text) => Styled(text, "T.H1");
    public static TextBlock H2(string text) => Styled(text, "T.H2");
    public static TextBlock H3(string text) => Styled(text, "T.H3");
    public static TextBlock Muted(string text) => Styled(text, "T.Muted");
    public static TextBlock Small(string text) => Styled(text, "T.Small");
    public static TextBlock Mono(string text) => Styled(text, "T.Mono");

    private static TextBlock Styled(string text, string key) => new() { Text = text, Style = S(key) };

    public static TextBlock Glyph(string glyph, double size = 14, string? fg = null)
    {
        var t = new TextBlock
        {
            Text = glyph,
            FontFamily = new FontFamily("Segoe MDL2 Assets"),
            FontSize = size,
            VerticalAlignment = VerticalAlignment.Center,
        };
        if (fg != null) t.SetResourceReference(TextBlock.ForegroundProperty, fg);
        return t;
    }

    // ---------------- 布局 ----------------
    public static SPanel V(double spacing, params UIElement?[] kids) => Fill(new SPanel { Orientation = Orientation.Vertical, Spacing = spacing }, kids);
    public static SPanel H(double spacing, params UIElement?[] kids) => Fill(new SPanel { Orientation = Orientation.Horizontal, Spacing = spacing }, kids);

    private static SPanel Fill(SPanel p, UIElement?[] kids)
    {
        foreach (var k in kids)
            if (k != null) p.Children.Add(k);
        return p;
    }

    /// <summary>行/列用 "Auto,*,32" 这种字符串描述。</summary>
    public static Grid Grid(string? rows = null, string? cols = null)
    {
        var g = new Grid();
        foreach (var r in Parse(rows)) g.RowDefinitions.Add(new RowDefinition { Height = r });
        foreach (var c in Parse(cols)) g.ColumnDefinitions.Add(new ColumnDefinition { Width = c });
        return g;
    }

    private static IEnumerable<GridLength> Parse(string? spec)
    {
        if (string.IsNullOrWhiteSpace(spec)) yield break;
        foreach (var raw in spec.Split(',', StringSplitOptions.RemoveEmptyEntries))
        {
            var s = raw.Trim();
            if (s == "Auto") yield return GridLength.Auto;
            else if (s == "*") yield return new GridLength(1, GridUnitType.Star);
            else if (s.EndsWith('*') && double.TryParse(s[..^1], out var st)) yield return new GridLength(st, GridUnitType.Star);
            else if (double.TryParse(s, out var px)) yield return new GridLength(px);
            else yield return GridLength.Auto;
        }
    }

    public static Border Card(UIElement? content = null, double padding = 16, string style = "Card")
    {
        var b = new Border { Style = S(style), Padding = new Thickness(padding) };
        if (content != null) b.Child = content;
        return b;
    }

    public static Border Pane(UIElement? content, string bg = "B.Paper2", double radius = 10, double padding = 12)
    {
        var b = new Border { CornerRadius = new CornerRadius(radius), Padding = new Thickness(padding) };
        b.SetResourceReference(Border.BackgroundProperty, bg);
        if (content != null) b.Child = content;
        return b;
    }

    public static SmoothScroll Scroll(UIElement content, double padding = 0)
    {
        var s = new SmoothScroll { Content = content, Padding = new Thickness(padding) };
        return s;
    }

    public static Border Sep(bool vertical = false)
    {
        var b = new Border();
        b.SetResourceReference(Border.BackgroundProperty, "B.LineSoft");
        if (vertical) { b.Width = 1; b.VerticalAlignment = VerticalAlignment.Stretch; }
        else { b.Height = 1; b.HorizontalAlignment = HorizontalAlignment.Stretch; }
        return b;
    }

    public static FrameworkElement Spring() => new Border { Width = 0, Height = 0 };

    // ---------------- 控件 ----------------
    public static Button Btn(string text, BtnKind kind = BtnKind.Normal, RoutedEventHandler? click = null, string? glyph = null)
    {
        var b = new Button { Style = S(StyleOf(kind)) };
        b.Content = glyph is null
            ? text
            : H(6, Glyph(glyph, kind == BtnKind.Primary ? 13 : 12.5), string.IsNullOrEmpty(text) ? null : Txt(text, 13));
        if (click != null) b.Click += click;
        return b;
    }

    public static Button IconBtn(string glyph, string? tip = null, RoutedEventHandler? click = null, double size = 14)
    {
        var b = new Button { Style = S("Btn.Icon"), Content = Glyph(glyph, size) };
        if (tip != null) b.ToolTip = tip;
        if (click != null) b.Click += click;
        return b;
    }

    private static string StyleOf(BtnKind k) => k switch
    {
        BtnKind.Primary => "Btn.Primary",
        BtnKind.Soft => "Btn.Soft",
        BtnKind.Ghost => "Btn.Ghost",
        BtnKind.Danger => "Btn.Danger",
        BtnKind.Chip => "Btn.Chip",
        BtnKind.Icon => "Btn.Icon",
        _ => "Btn.Normal",
    };

    public static TextBox Input(string placeholder = "", string text = "", double width = double.NaN)
    {
        var t = new TextBox { Style = S("Input"), Tag = placeholder, Text = text };
        if (!double.IsNaN(width)) t.Width = width;
        return t;
    }

    public static TextBox Multi(string placeholder = "", string text = "", double height = 90)
    {
        var t = new TextBox { Style = S("Input.Multi"), Tag = placeholder, Text = text, Height = height };
        return t;
    }

    public static TextBox LogBox()
    {
        var t = new TextBox { Style = S("Input.Log") };
        return t;
    }

    public static PasswordBox Pw(double width = double.NaN)
    {
        var p = new PasswordBox { Style = S("Pw") };
        if (!double.IsNaN(width)) p.Width = width;
        return p;
    }

    public static ComboBox Combo(IEnumerable<string>? items = null, string? selected = null, double width = double.NaN, string placeholder = "")
    {
        var c = new ComboBox { Style = S("Combo"), Tag = placeholder };
        if (items != null)
            foreach (var i in items) c.Items.Add(i);
        if (selected != null && c.Items.Contains(selected)) c.SelectedItem = selected;
        else if (c.Items.Count > 0) c.SelectedIndex = 0;
        if (!double.IsNaN(width)) c.Width = width;
        return c;
    }

    public static CheckBox Check(string label, bool value = false, RoutedEventHandler? changed = null)
    {
        var c = new CheckBox { Style = S("Chk"), Content = label, IsChecked = value };
        if (changed != null)
        {
            c.Checked += changed;
            c.Unchecked += changed;
        }
        return c;
    }

    public static CheckBox Switch(bool value = false, RoutedEventHandler? changed = null)
    {
        var c = new CheckBox { Style = S("Switch"), IsChecked = value, VerticalAlignment = VerticalAlignment.Center };
        if (changed != null)
        {
            c.Checked += changed;
            c.Unchecked += changed;
        }
        return c;
    }

    public static Slider Sld(double min, double max, double value, double tick = 1)
    {
        return new Slider
        {
            Style = S("Sld"),
            Minimum = min,
            Maximum = max,
            Value = Math.Clamp(value, min, max),
            TickFrequency = tick,
            IsSnapToTickEnabled = tick > 0,
        };
    }

    public static ProgressBar Prog(double value = 0)
        => new() { Style = S("Prog"), Value = value, Maximum = 100 };

    // ---------------- 复合件 ----------------
    public static Border Tag(string text, string fg = "B.InkMuted", string bg = "B.LineSoft")
    {
        var b = new Border
        {
            CornerRadius = new CornerRadius(5),
            Padding = new Thickness(6, 1.5, 6, 2.5),
            VerticalAlignment = VerticalAlignment.Center,
            Child = Txt(text, 11, fg: fg),
        };
        b.SetResourceReference(Border.BackgroundProperty, bg);
        return b;
    }

    public static Border Badge(string text)
    {
        var b = new Border
        {
            CornerRadius = new CornerRadius(999),
            Padding = new Thickness(6, 0, 6, 1),
            MinWidth = 18,
            Height = 18,
            VerticalAlignment = VerticalAlignment.Center,
            Child = new TextBlock
            {
                Text = text,
                FontSize = 11,
                FontWeight = FontWeights.SemiBold,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
                Foreground = Brushes.White,
            },
        };
        b.SetResourceReference(Border.BackgroundProperty, "B.Accent");
        return b;
    }

    /// <summary>设置页的一行：左标题 + 右控件 +（可选）下说明。</summary>
    public static UIElement Field(string label, UIElement control, string? hint = null, double labelWidth = 170)
    {
        var g = Grid(null, $"{labelWidth},*");
        var left = V(2, Txt(label, 13), hint is null ? null : Small(hint));
        left.VerticalAlignment = VerticalAlignment.Center;
        left.Margin = new Thickness(0, 0, 14, 0);
        Grid.SetColumn(left, 0);
        control.SetValue(FrameworkElement.VerticalAlignmentProperty, VerticalAlignment.Center);
        Grid.SetColumn((UIElement)control, 1);
        g.Children.Add(left);
        g.Children.Add(control);
        g.Margin = new Thickness(0, 5, 0, 5);
        return g;
    }

    public static UIElement Section(string title, string? sub = null, UIElement? right = null)
    {
        var g = Grid(null, "*,Auto");
        var left = V(2, H2(title), sub is null ? null : Muted(sub));
        Grid.SetColumn(left, 0);
        g.Children.Add(left);
        if (right != null)
        {
            right.SetValue(FrameworkElement.VerticalAlignmentProperty, VerticalAlignment.Center);
            Grid.SetColumn(right, 1);
            g.Children.Add(right);
        }
        return g;
    }

    public static UIElement Empty(string glyph, string title, string? hint = null)
    {
        var v = V(8,
            Glyph(glyph, 34, "B.InkFaint"),
            new TextBlock { Text = title, FontSize = 14, HorizontalAlignment = HorizontalAlignment.Center }
                .Dyn(TextBlock.ForegroundProperty, "B.InkMuted"),
            hint is null ? null : new TextBlock
            {
                Text = hint, FontSize = 12, TextWrapping = TextWrapping.Wrap, MaxWidth = 420,
                TextAlignment = TextAlignment.Center, HorizontalAlignment = HorizontalAlignment.Center,
            }.Dyn(TextBlock.ForegroundProperty, "B.InkFaint"));
        v.HorizontalAlignment = HorizontalAlignment.Center;
        v.VerticalAlignment = VerticalAlignment.Center;
        v.Margin = new Thickness(0, 46, 0, 46);
        foreach (UIElement c in v.Children) c.SetValue(FrameworkElement.HorizontalAlignmentProperty, HorizontalAlignment.Center);
        return v;
    }

    /// <summary>加载占位骨架（带扫光）。</summary>
    public static Border Skeleton(double height = 16, double width = double.NaN)
    {
        var b = new Border { Height = height, CornerRadius = new CornerRadius(6), ClipToBounds = true };
        if (!double.IsNaN(width)) b.Width = width;
        b.SetResourceReference(Border.BackgroundProperty, "B.LineSoft");
        var sweep = new Border
        {
            Width = 90,
            HorizontalAlignment = HorizontalAlignment.Left,
            Background = new LinearGradientBrush(
                new GradientStopCollection
                {
                    new(Color.FromArgb(0, 255, 255, 255), 0),
                    new(Color.FromArgb(120, 255, 255, 255), 0.5),
                    new(Color.FromArgb(0, 255, 255, 255), 1),
                }, 0),
        };
        var tt = new TranslateTransform(-90);
        sweep.RenderTransform = tt;
        b.Child = sweep;
        if (Motion.Enabled)
        {
            var an = new DoubleAnimation(-90, 520, TimeSpan.FromMilliseconds(1150)) { RepeatBehavior = RepeatBehavior.Forever };
            tt.BeginAnimation(TranslateTransform.XProperty, an);
        }
        return b;
    }

    /// <summary>可点击的行卡片（列表项）。</summary>
    public static Border RowCard(UIElement content, MouseButtonEventHandler? click = null, double padding = 12)
    {
        var b = new Border
        {
            CornerRadius = new CornerRadius(10),
            Padding = new Thickness(padding),
            BorderThickness = new Thickness(1),
            Child = content,
            Cursor = click != null ? Cursors.Hand : null,
        };
        b.SetResourceReference(Border.BackgroundProperty, "B.Paper");
        b.SetResourceReference(Border.BorderBrushProperty, "B.Line");
        if (click != null) b.MouseLeftButtonUp += click;
        return b;
    }

    public static void OpenUrl(string url)
    {
        try
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(url) { UseShellExecute = true });
        }
        catch (Exception ex) { AppServices.Toast("打不开链接", ex.Message, ToastKind.Warning); }
    }
}

public static class UiExt
{
    public static T Dyn<T>(this T el, DependencyProperty p, string key) where T : FrameworkElement
    {
        el.SetResourceReference(p, key);
        return el;
    }

    public static T M<T>(this T el, double l, double t = 0, double r = 0, double b = 0) where T : FrameworkElement
    {
        el.Margin = new Thickness(l, t, r, b);
        return el;
    }

    public static T M<T>(this T el, double all) where T : FrameworkElement
    {
        el.Margin = new Thickness(all);
        return el;
    }

    public static T W<T>(this T el, double w) where T : FrameworkElement
    {
        el.Width = w;
        return el;
    }

    public static T MinW<T>(this T el, double w) where T : FrameworkElement
    {
        el.MinWidth = w;
        return el;
    }

    public static T Hh<T>(this T el, double h) where T : FrameworkElement
    {
        el.Height = h;
        return el;
    }

    public static T At<T>(this T el, int row, int col = 0, int rowSpan = 1, int colSpan = 1) where T : UIElement
    {
        System.Windows.Controls.Grid.SetRow(el, row);
        System.Windows.Controls.Grid.SetColumn(el, col);
        if (rowSpan > 1) System.Windows.Controls.Grid.SetRowSpan(el, rowSpan);
        if (colSpan > 1) System.Windows.Controls.Grid.SetColumnSpan(el, colSpan);
        return el;
    }

    public static Grid Add(this Grid g, UIElement el, int row, int col = 0, int rowSpan = 1, int colSpan = 1)
    {
        el.At(row, col, rowSpan, colSpan);
        g.Children.Add(el);
        return g;
    }

    public static T Left<T>(this T el) where T : FrameworkElement
    {
        el.HorizontalAlignment = HorizontalAlignment.Left;
        return el;
    }

    public static T Right<T>(this T el) where T : FrameworkElement
    {
        el.HorizontalAlignment = HorizontalAlignment.Right;
        return el;
    }

    public static T Center<T>(this T el) where T : FrameworkElement
    {
        el.HorizontalAlignment = HorizontalAlignment.Center;
        return el;
    }

    public static T Stretch<T>(this T el) where T : FrameworkElement
    {
        el.HorizontalAlignment = HorizontalAlignment.Stretch;
        return el;
    }

    public static T VCenter<T>(this T el) where T : FrameworkElement
    {
        el.VerticalAlignment = VerticalAlignment.Center;
        return el;
    }

    public static T VTop<T>(this T el) where T : FrameworkElement
    {
        el.VerticalAlignment = VerticalAlignment.Top;
        return el;
    }

    public static T Wrap<T>(this T el) where T : TextBlock
    {
        el.TextWrapping = TextWrapping.Wrap;
        return el;
    }

    public static T Trim<T>(this T el) where T : TextBlock
    {
        el.TextTrimming = TextTrimming.CharacterEllipsis;
        return el;
    }

    public static T Tip<T>(this T el, string tip) where T : FrameworkElement
    {
        el.ToolTip = tip;
        return el;
    }

    public static T Tag2<T>(this T el, object tag) where T : FrameworkElement
    {
        el.Tag = tag;
        return el;
    }

    public static T Hide<T>(this T el, bool hidden = true) where T : UIElement
    {
        el.Visibility = hidden ? Visibility.Collapsed : Visibility.Visible;
        return el;
    }

    public static T Show<T>(this T el, bool shown = true) where T : UIElement
    {
        el.Visibility = shown ? Visibility.Visible : Visibility.Collapsed;
        return el;
    }

    public static bool Shown(this UIElement el) => el.Visibility == Visibility.Visible;

    public static string Str(this ComboBox c) => c.SelectedItem as string ?? "";

    public static void Fill(this ComboBox c, IEnumerable<string> items, string? keep = null)
    {
        var cur = keep ?? c.SelectedItem as string;
        c.Items.Clear();
        foreach (var i in items) c.Items.Add(i);
        if (cur != null && c.Items.Contains(cur)) c.SelectedItem = cur;
        else if (c.Items.Count > 0) c.SelectedIndex = 0;
    }
}

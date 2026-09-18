using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Effects;

namespace PyMCL.Services;

/// <summary>
/// 全局动效。原则：位移 ≤ 14px、时长 130~260ms、统一 CubicEase.Out，
/// 只动 Opacity / Transform / Effect.Opacity 这些不触发布局的属性，保证 60fps。
/// </summary>
public static class Motion
{
    public static bool Enabled { get; set; } = true;
    public static double Scale { get; set; } = 1.0;

    private static readonly CubicEase EaseOut = new() { EasingMode = EasingMode.EaseOut };
    private static readonly CubicEase EaseIn = new() { EasingMode = EasingMode.EaseIn };
    private static readonly QuadraticEase EaseInOut = new() { EasingMode = EasingMode.EaseInOut };
    private static readonly BackEase EaseBack = new() { EasingMode = EasingMode.EaseOut, Amplitude = 0.4 };

    private static Duration D(double ms) => TimeSpan.FromMilliseconds(Math.Max(1, ms * Scale));

    private static TranslateTransform EnsureTranslate(UIElement el)
    {
        if (el.RenderTransform is TransformGroup g)
            return g.Children.OfType<TranslateTransform>().FirstOrDefault() ?? Add(g, new TranslateTransform());
        if (el.RenderTransform is TranslateTransform t) return t;
        var group = new TransformGroup();
        if (el.RenderTransform is Transform old && old is not MatrixTransform { Matrix.IsIdentity: true })
            group.Children.Add(old);
        var tt = new TranslateTransform();
        group.Children.Add(tt);
        el.RenderTransform = group;
        return tt;
    }

    private static ScaleTransform EnsureScale(UIElement el)
    {
        el.RenderTransformOrigin = new Point(0.5, 0.5);
        if (el.RenderTransform is TransformGroup g)
            return g.Children.OfType<ScaleTransform>().FirstOrDefault() ?? Add(g, new ScaleTransform(1, 1));
        if (el.RenderTransform is ScaleTransform s) return s;
        var group = new TransformGroup();
        if (el.RenderTransform is Transform old && old is not MatrixTransform { Matrix.IsIdentity: true })
            group.Children.Add(old);
        var st = new ScaleTransform(1, 1);
        group.Children.Add(st);
        el.RenderTransform = group;
        return st;
    }

    private static T Add<T>(TransformGroup g, T t) where T : Transform
    {
        g.Children.Add(t);
        return t;
    }

    /// <summary>入场：淡入 + 轻微上浮。</summary>
    public static void FadeIn(UIElement el, double ms = 220, double fromY = 10, double delayMs = 0)
    {
        if (!Enabled)
        {
            el.Opacity = 1;
            return;
        }
        var tt = EnsureTranslate(el);
        el.Opacity = 0;
        tt.Y = fromY;
        var begin = TimeSpan.FromMilliseconds(delayMs * Scale);
        el.BeginAnimation(UIElement.OpacityProperty,
            new DoubleAnimation(0, 1, D(ms)) { BeginTime = begin, EasingFunction = EaseOut });
        tt.BeginAnimation(TranslateTransform.YProperty,
            new DoubleAnimation(fromY, 0, D(ms + 60)) { BeginTime = begin, EasingFunction = EaseOut });
    }

    public static void FadeOut(UIElement el, double ms = 140, Action? then = null)
    {
        if (!Enabled)
        {
            el.Opacity = 0;
            then?.Invoke();
            return;
        }
        var an = new DoubleAnimation(el.Opacity, 0, D(ms)) { EasingFunction = EaseIn };
        if (then != null) an.Completed += (_, _) => then();
        el.BeginAnimation(UIElement.OpacityProperty, an);
    }

    /// <summary>列表/网格错峰入场。</summary>
    public static void Stagger(Panel host, double step = 26, double ms = 210, double fromY = 12)
    {
        if (!Enabled) return;
        var i = 0;
        foreach (UIElement child in host.Children)
        {
            FadeIn(child, ms, fromY, Math.Min(i * step, 320));
            i++;
        }
    }

    public static void StaggerItems(IEnumerable<UIElement> items, double step = 24, double ms = 200, double fromY = 10)
    {
        if (!Enabled) return;
        var i = 0;
        foreach (var child in items)
        {
            FadeIn(child, ms, fromY, Math.Min(i * step, 300));
            i++;
        }
    }

    /// <summary>鼠标悬浮时轻微抬起 + 阴影加深，离开复位。</summary>
    public static void HoverLift(FrameworkElement el, double scale = 1.012, double lift = 2, double blur = 22)
    {
        var shadow = new DropShadowEffect
        {
            BlurRadius = blur,
            ShadowDepth = 3,
            Direction = 270,
            Opacity = 0,
            Color = Color.FromRgb(0x14, 0x22, 0x1D),
            RenderingBias = RenderingBias.Performance,
        };
        el.Effect = shadow;
        var sc = EnsureScale(el);
        var tt = EnsureTranslate(el);
        el.MouseEnter += (_, _) =>
        {
            if (!Enabled) return;
            sc.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(scale, D(170)) { EasingFunction = EaseOut });
            sc.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(scale, D(170)) { EasingFunction = EaseOut });
            tt.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(-lift, D(170)) { EasingFunction = EaseOut });
            shadow.BeginAnimation(DropShadowEffect.OpacityProperty, new DoubleAnimation(0.16, D(170)));
        };
        el.MouseLeave += (_, _) =>
        {
            sc.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(1, D(190)) { EasingFunction = EaseOut });
            sc.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(1, D(190)) { EasingFunction = EaseOut });
            tt.BeginAnimation(TranslateTransform.YProperty, new DoubleAnimation(0, D(190)) { EasingFunction = EaseOut });
            shadow.BeginAnimation(DropShadowEffect.OpacityProperty, new DoubleAnimation(0, D(190)));
        };
    }

    /// <summary>静态阴影（卡片层次）。</summary>
    public static T Shadow<T>(T el, double blur = 18, double opacity = 0.08, double depth = 2) where T : UIElement
    {
        el.Effect = new DropShadowEffect
        {
            BlurRadius = blur,
            ShadowDepth = depth,
            Direction = 270,
            Opacity = opacity,
            Color = Color.FromRgb(0x10, 0x1C, 0x18),
            RenderingBias = RenderingBias.Performance,
        };
        return el;
    }

    /// <summary>点一下的弹一下。</summary>
    public static void Pulse(UIElement el, double peak = 1.06)
    {
        if (!Enabled) return;
        var sc = EnsureScale(el);
        var an = new DoubleAnimationUsingKeyFrames { Duration = D(280) };
        an.KeyFrames.Add(new EasingDoubleKeyFrame(peak, KeyTime.FromPercent(0.35), EaseOut));
        an.KeyFrames.Add(new EasingDoubleKeyFrame(1, KeyTime.FromPercent(1), EaseBack));
        sc.BeginAnimation(ScaleTransform.ScaleXProperty, an);
        sc.BeginAnimation(ScaleTransform.ScaleYProperty, an.Clone());
    }

    /// <summary>出错时左右抖一下。</summary>
    public static void Shake(UIElement el)
    {
        if (!Enabled) return;
        var tt = EnsureTranslate(el);
        var an = new DoubleAnimationUsingKeyFrames { Duration = D(330) };
        double[] xs = { -7, 6, -4, 3, -1.5, 0 };
        for (var i = 0; i < xs.Length; i++)
            an.KeyFrames.Add(new EasingDoubleKeyFrame(xs[i], KeyTime.FromPercent((i + 1.0) / xs.Length), EaseOut));
        tt.BeginAnimation(TranslateTransform.XProperty, an);
    }

    /// <summary>横幅上的光扫。</summary>
    public static Storyboard Shine(FrameworkElement layer, TranslateTransform tx, double width = 1200)
    {
        var sb = new Storyboard { RepeatBehavior = RepeatBehavior.Forever };
        var an = new DoubleAnimation(-260, width, D(2600)) { BeginTime = TimeSpan.Zero, EasingFunction = EaseInOut };
        Storyboard.SetTarget(an, layer);
        Storyboard.SetTargetProperty(an, new PropertyPath("RenderTransform.X"));
        sb.Children.Add(an);
        var fade = new DoubleAnimationUsingKeyFrames { Duration = D(2600) };
        fade.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromPercent(0)));
        fade.KeyFrames.Add(new LinearDoubleKeyFrame(0.5, KeyTime.FromPercent(0.25)));
        fade.KeyFrames.Add(new LinearDoubleKeyFrame(0.5, KeyTime.FromPercent(0.6)));
        fade.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromPercent(1)));
        Storyboard.SetTarget(fade, layer);
        Storyboard.SetTargetProperty(fade, new PropertyPath("Opacity"));
        sb.Children.Add(fade);
        layer.RenderTransform = tx;
        if (Enabled) sb.Begin();
        return sb;
    }

    /// <summary>进度条平滑推进，避免数字跳变造成的顿挫。</summary>
    public static void Progress(ProgressBar bar, double value)
    {
        value = Math.Clamp(value, 0, 100);
        if (!Enabled)
        {
            bar.BeginAnimation(RangeBase.ValueProperty, null);
            bar.Value = value;
            return;
        }
        bar.BeginAnimation(RangeBase.ValueProperty,
            new DoubleAnimation(value, D(Math.Abs(value - bar.Value) > 40 ? 320 : 200)) { EasingFunction = EaseOut });
    }

    /// <summary>
    /// 数字滚动。跟着合成器的渲染节拍走（CompositionTarget.Rendering），不自己开 16ms 的
    /// DispatcherTimer——那种定时器和真实刷新率对不齐，既会多跑帧也会掉帧，页面一多还各跑各的。
    /// </summary>
    public static void CountUp(TextBlock tb, double from, double to, string fmt = "0", double ms = 620)
    {
        if (!Enabled)
        {
            tb.Text = to.ToString(fmt);
            return;
        }
        var sw = System.Diagnostics.Stopwatch.StartNew();
        var total = Math.Max(1, ms * Scale);
        EventHandler? tick = null;
        tick = (_, _) =>
        {
            var t = Math.Min(1, sw.Elapsed.TotalMilliseconds / total);
            var e = 1 - Math.Pow(1 - t, 3);
            tb.Text = (from + (to - from) * e).ToString(fmt);
            // 文本块被换掉 / 页面已卸载就别再占着渲染回调。
            if (t >= 1 || !tb.IsLoaded && tb.Parent is null) CompositionTarget.Rendering -= tick;
        };
        CompositionTarget.Rendering += tick;
    }

    /// <summary>宽/高的平滑变化（用于侧栏折叠、面板展开）。</summary>
    public static void AnimateWidth(FrameworkElement el, double to, double ms = 220, Action? done = null)
    {
        if (!Enabled)
        {
            el.Width = to;
            done?.Invoke();
            return;
        }
        var from = double.IsNaN(el.Width) ? el.ActualWidth : el.Width;
        var an = new DoubleAnimation(from, to, D(ms)) { EasingFunction = EaseOut };
        if (done != null) an.Completed += (_, _) => done();
        el.BeginAnimation(FrameworkElement.WidthProperty, an);
    }

    public static void AnimateHeight(FrameworkElement el, double to, double ms = 220, Action? done = null)
    {
        if (!Enabled)
        {
            el.Height = to;
            done?.Invoke();
            return;
        }
        var from = double.IsNaN(el.Height) ? el.ActualHeight : el.Height;
        var an = new DoubleAnimation(from, to, D(ms)) { EasingFunction = EaseOut };
        if (done != null) an.Completed += (_, _) => done();
        el.BeginAnimation(FrameworkElement.HeightProperty, an);
    }

    public static void Fade(UIElement el, double to, double ms = 160, Action? done = null)
    {
        if (!Enabled)
        {
            el.Opacity = to;
            done?.Invoke();
            return;
        }
        var an = new DoubleAnimation(to, D(ms)) { EasingFunction = EaseOut };
        if (done != null) an.Completed += (_, _) => done();
        el.BeginAnimation(UIElement.OpacityProperty, an);
    }

    /// <summary>弹窗入场：淡入 + 从 0.96 放大。</summary>
    public static void PopIn(FrameworkElement el, double ms = 200)
    {
        if (!Enabled)
        {
            el.Opacity = 1;
            return;
        }
        var sc = EnsureScale(el);
        el.Opacity = 0;
        sc.ScaleX = sc.ScaleY = 0.96;
        el.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(0, 1, D(ms)) { EasingFunction = EaseOut });
        sc.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(0.96, 1, D(ms + 60)) { EasingFunction = EaseOut });
        sc.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(0.96, 1, D(ms + 60)) { EasingFunction = EaseOut });
    }

    public static void PopOut(FrameworkElement el, Action done, double ms = 130)
    {
        if (!Enabled)
        {
            done();
            return;
        }
        var sc = EnsureScale(el);
        sc.BeginAnimation(ScaleTransform.ScaleXProperty, new DoubleAnimation(0.97, D(ms)) { EasingFunction = EaseIn });
        sc.BeginAnimation(ScaleTransform.ScaleYProperty, new DoubleAnimation(0.97, D(ms)) { EasingFunction = EaseIn });
        var an = new DoubleAnimation(0, D(ms)) { EasingFunction = EaseIn };
        an.Completed += (_, _) => done();
        el.BeginAnimation(UIElement.OpacityProperty, an);
    }

    /// <summary>侧边滑入（Toast / 抽屉）。</summary>
    public static void SlideIn(FrameworkElement el, double fromX = 40, double ms = 240)
    {
        if (!Enabled)
        {
            el.Opacity = 1;
            return;
        }
        var tt = EnsureTranslate(el);
        el.Opacity = 0;
        tt.X = fromX;
        el.BeginAnimation(UIElement.OpacityProperty, new DoubleAnimation(0, 1, D(ms)) { EasingFunction = EaseOut });
        tt.BeginAnimation(TranslateTransform.XProperty, new DoubleAnimation(fromX, 0, D(ms + 60)) { EasingFunction = EaseOut });
    }

    public static void SlideOut(FrameworkElement el, Action done, double toX = 40, double ms = 180)
    {
        if (!Enabled)
        {
            done();
            return;
        }
        var tt = EnsureTranslate(el);
        tt.BeginAnimation(TranslateTransform.XProperty, new DoubleAnimation(toX, D(ms)) { EasingFunction = EaseIn });
        var an = new DoubleAnimation(0, D(ms)) { EasingFunction = EaseIn };
        an.Completed += (_, _) => done();
        el.BeginAnimation(UIElement.OpacityProperty, an);
    }

    /// <summary>页面切换：旧页淡出上移，新页淡入上浮。</summary>
    public static void PageSwap(ContentControl host, UIElement next, bool forward = true)
    {
        var old = host.Content as UIElement;
        if (!Enabled || old is null)
        {
            host.Content = next;
            if (Enabled) FadeIn(next, 230, 12);
            return;
        }
        var tt = EnsureTranslate(old);
        var fade = new DoubleAnimation(0, D(110)) { EasingFunction = EaseIn };
        fade.Completed += (_, _) =>
        {
            host.Content = next;
            FadeIn(next, 250, forward ? 14 : -14);
        };
        tt.BeginAnimation(TranslateTransform.YProperty,
            new DoubleAnimation(forward ? -8 : 8, D(110)) { EasingFunction = EaseIn });
        old.BeginAnimation(UIElement.OpacityProperty, fade);
    }
}

using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Animation;
using Windows.Foundation;
using Windows.UI.ViewManagement;

namespace PyMCL.Services;

public static class Motion
{
    private static readonly DependencyProperty HoverOnProperty =
        DependencyProperty.RegisterAttached("_hoverOn", typeof(bool), typeof(Motion), new PropertyMetadata(false));

    private static readonly DependencyProperty ActiveSbProperty =
        DependencyProperty.RegisterAttached("_activeSb", typeof(Storyboard), typeof(Motion), new PropertyMetadata(null));

    /// <summary>
    /// 正在跑的动画对应的完成信号。Storyboard.Stop() 不触发 Completed，
    /// 而 AnimateAsync 的返回值就挂在那上面——被顶掉或 ResetVisual 掐掉之后，
    /// 等在 await 上的调用方（PageInAsync / DockShowAsync / TabInAsync …）就永远不返回。
    /// 存一份在这里，让 Stop 的两条路径能主动把它放行。
    /// </summary>
    private static readonly DependencyProperty ActiveDoneProperty =
        DependencyProperty.RegisterAttached("_activeDone", typeof(TaskCompletionSource), typeof(Motion), new PropertyMetadata(null));

    public static bool AnimationsWanted()
    {
        try
        {
            return new UISettings().AnimationsEnabled;
        }
        catch
        {
            return true;
        }
    }

    public static CompositeTransform Tx(UIElement el)
    {
        if (el.RenderTransform is CompositeTransform ct)
            return ct;
        ct = new CompositeTransform();
        el.RenderTransform = ct;
        el.RenderTransformOrigin = new Point(0.5, 0.5);
        return ct;
    }

    public static Task AnimateAsync(UIElement el, double? opacity, double? x, double? y, double? scale, int ms, EasingMode mode = EasingMode.EaseOut)
    {
        if (!AnimationsWanted() || ms <= 0)
        {
            ApplyInstant(el, opacity, x, y, scale);
            return Task.CompletedTask;
        }
        var t = Tx(el);
        StopActive(el);
        var sb = new Storyboard();
        el.SetValue(ActiveSbProperty, sb);
        var ease = new CubicEase { EasingMode = mode };
        var dur = new Duration(TimeSpan.FromMilliseconds(ms));
        if (opacity is double o)
            sb.Children.Add(Anim(el, "Opacity", o, dur, ease));
        if (x is double xv)
            sb.Children.Add(Anim(t, "TranslateX", xv, dur, ease));
        if (y is double yv)
            sb.Children.Add(Anim(t, "TranslateY", yv, dur, ease));
        if (scale is double s)
        {
            sb.Children.Add(Anim(t, "ScaleX", s, dur, ease));
            sb.Children.Add(Anim(t, "ScaleY", s, dur, ease));
        }
        var done = new TaskCompletionSource();
        el.SetValue(ActiveDoneProperty, done);
        sb.Completed += (_, _) =>
        {
            if (ReferenceEquals(el.GetValue(ActiveSbProperty), sb))
            {
                el.SetValue(ActiveSbProperty, null);
                el.SetValue(ActiveDoneProperty, null);
            }
            done.TrySetResult();
        };
        sb.Begin();
        return done.Task;
    }

    /// <summary>停掉在跑的动画并放行它的 await（Stop 不触发 Completed，得手动收尾）。</summary>
    private static void StopActive(UIElement el)
    {
        if (el.GetValue(ActiveSbProperty) is Storyboard prev)
        {
            try { prev.Stop(); } catch { }
            el.SetValue(ActiveSbProperty, null);
        }
        if (el.GetValue(ActiveDoneProperty) is TaskCompletionSource tcs)
        {
            el.SetValue(ActiveDoneProperty, null);
            tcs.TrySetResult();
        }
    }

    private static void ApplyInstant(UIElement el, double? opacity, double? x, double? y, double? scale)
    {
        var t = Tx(el);
        if (opacity is double o) el.Opacity = o;
        if (x is double xv) t.TranslateX = xv;
        if (y is double yv) t.TranslateY = yv;
        if (scale is double s)
        {
            t.ScaleX = s;
            t.ScaleY = s;
        }
    }

    private static DoubleAnimation Anim(DependencyObject target, string prop, double to, Duration dur, EasingFunctionBase ease)
    {
        var a = new DoubleAnimation
        {
            To = to,
            Duration = dur,
            EasingFunction = ease,
            EnableDependentAnimation = false,
        };
        Storyboard.SetTarget(a, target);
        Storyboard.SetTargetProperty(a, prop);
        return a;
    }

    /// <summary>
    /// 等元素 Loaded。加一个上限：元素若永不 Loaded（被换下的页、构造后没进可视树），
    /// 原来这里会永久挂起，而 PageInAsync / TabInAsync 都 await 它。
    /// </summary>
    public static async Task WaitLoadedAsync(FrameworkElement el)
    {
        if (el.IsLoaded) return;
        var tcs = new TaskCompletionSource();
        RoutedEventHandler? h = null;
        h = (_, _) =>
        {
            el.Loaded -= h;
            tcs.TrySetResult();
        };
        el.Loaded += h;
        await Task.WhenAny(tcs.Task, Task.Delay(1000));
        // 超时也要把处理器摘掉，否则这个元素每等一次就多挂一个永不执行的委托
        if (!tcs.Task.IsCompleted) el.Loaded -= h;
    }

    public static async Task PageOutAsync(UIElement el)
    {
        Tx(el);
        await AnimateAsync(el, 0, -40, null, 0.96, 120, EasingMode.EaseIn);
    }

    public static async Task PageInAsync(UIElement el)
    {
        if (el is FrameworkElement fe)
            await WaitLoadedAsync(fe);
        var t = Tx(el);
        el.Opacity = 0;
        t.TranslateX = 40;
        t.TranslateY = 0;
        t.ScaleX = 0.97;
        t.ScaleY = 0.97;
        await AnimateAsync(el, 1, 0, 0, 1, 240, EasingMode.EaseOut);
    }

    public static async Task TabOutAsync(UIElement el)
    {
        await AnimateAsync(el, 0, null, -18, 0.98, 100, EasingMode.EaseIn);
    }

    public static async Task TabInAsync(UIElement el)
    {
        if (el is FrameworkElement fe)
            await WaitLoadedAsync(fe);
        var t = Tx(el);
        el.Opacity = 0;
        t.TranslateX = 0;
        t.TranslateY = 20;
        t.ScaleX = 0.98;
        t.ScaleY = 0.98;
        await AnimateAsync(el, 1, 0, 0, 1, 220, EasingMode.EaseOut);
    }

    public static void PopIn(UIElement el, int delayMs)
    {
        if (!AnimationsWanted())
        {
            ResetVisual(el);
            return;
        }
        var t = Tx(el);
        el.Opacity = 0;
        t.TranslateY = 20;
        t.ScaleX = 0.9;
        t.ScaleY = 0.9;
        async Task Run()
        {
            if (el is FrameworkElement fe)
                await WaitLoadedAsync(fe);
            if (delayMs > 0)
                await Task.Delay(delayMs);
            await AnimateAsync(el, 1, 0, 0, 1, 300, EasingMode.EaseOut);
        }
        _ = Run();
    }

    public static async Task DockShowAsync(UIElement el)
    {
        el.Visibility = Visibility.Visible;
        if (!AnimationsWanted())
        {
            ResetVisual(el);
            return;
        }
        var t = Tx(el);
        el.Opacity = 0;
        t.TranslateY = 64;
        t.ScaleX = 0.94;
        t.ScaleY = 0.94;
        await AnimateAsync(el, 1, 0, 0, 1, 360, EasingMode.EaseOut);
    }

    public static async Task DockHideAsync(UIElement el)
    {
        if (AnimationsWanted())
            await AnimateAsync(el, 0, 0, 48, 0.95, 200, EasingMode.EaseIn);
        el.Visibility = Visibility.Collapsed;
        ResetVisual(el);
    }

    public static void EnableHoverLift(UIElement el, double scale = 1.045)
    {
        if ((bool)el.GetValue(HoverOnProperty)) return;
        el.SetValue(HoverOnProperty, true);
        Tx(el);
        el.PointerEntered += (_, _) =>
        {
            if (!AnimationsWanted()) return;
            _ = AnimateAsync(el, null, null, -7, scale, 160);
        };
        el.PointerExited += (_, _) =>
        {
            if (!AnimationsWanted()) { ApplyInstant(el, null, null, 0, 1); return; }
            _ = AnimateAsync(el, null, null, 0, 1, 180);
        };
        el.PointerPressed += (_, _) =>
        {
            if (!AnimationsWanted()) return;
            _ = AnimateAsync(el, null, null, 0, 0.97, 70);
        };
        el.PointerReleased += (_, _) =>
        {
            if (!AnimationsWanted()) return;
            _ = AnimateAsync(el, null, null, -7, scale, 120);
        };
    }

    public static void ResetVisual(UIElement? el)
    {
        if (el is null) return;
        StopActive(el);
        var t = Tx(el);
        el.Opacity = 1;
        t.TranslateX = 0;
        t.TranslateY = 0;
        t.ScaleX = 1;
        t.ScaleY = 1;
    }

    public static void CardEnter(UIElement el, int delayMs = 0, double hoverScale = 1.045, bool popIn = true)
    {
        EnableHoverLift(el, hoverScale);
        if (popIn)
            PopIn(el, delayMs);
        else
            ResetVisual(el);
    }

    public static async Task PulseOnceAsync(UIElement el)
    {
        if (!AnimationsWanted()) return;
        await AnimateAsync(el, null, null, null, 1.08, 90);
        await AnimateAsync(el, null, null, null, 1, 140);
    }

    /// <summary>返回 Storyboard，调用方负责在 Unloaded / 不可见时 Stop。</summary>
    public static Storyboard? StartShine(UIElement shine, TranslateTransform tx)
    {
        if (!AnimationsWanted())
        {
            shine.Opacity = 0;
            return null;
        }
        shine.Opacity = 0.42;
        var sb = new Storyboard { RepeatBehavior = RepeatBehavior.Forever };
        var a = new DoubleAnimationUsingKeyFrames
        {
            Duration = TimeSpan.FromMilliseconds(2800),
            EnableDependentAnimation = false,
        };
        a.KeyFrames.Add(new EasingDoubleKeyFrame { KeyTime = TimeSpan.FromMilliseconds(0), Value = -160 });
        a.KeyFrames.Add(new EasingDoubleKeyFrame
        {
            KeyTime = TimeSpan.FromMilliseconds(1600),
            Value = 980,
            EasingFunction = new CubicEase { EasingMode = EasingMode.EaseInOut },
        });
        a.KeyFrames.Add(new EasingDoubleKeyFrame { KeyTime = TimeSpan.FromMilliseconds(2800), Value = 980 });
        Storyboard.SetTarget(a, tx);
        Storyboard.SetTargetProperty(a, "X");
        sb.Children.Add(a);
        sb.Begin();
        return sb;
    }
}

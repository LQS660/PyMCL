using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Animation;
using Windows.Foundation;

namespace PyMCL.Services;

public static class Motion
{
    private static readonly DependencyProperty HoverOnProperty =
        DependencyProperty.RegisterAttached("_hoverOn", typeof(bool), typeof(Motion), new PropertyMetadata(false));

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
        var t = Tx(el);
        var sb = new Storyboard();
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
        sb.Completed += (_, _) => done.TrySetResult();
        sb.Begin();
        return done.Task;
    }

    private static DoubleAnimation Anim(DependencyObject target, string prop, double to, Duration dur, EasingFunctionBase ease)
    {
        var a = new DoubleAnimation
        {
            To = to,
            Duration = dur,
            EasingFunction = ease,
            EnableDependentAnimation = true,
        };
        Storyboard.SetTarget(a, target);
        Storyboard.SetTargetProperty(a, prop);
        return a;
    }

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
        await tcs.Task;
    }

    public static async Task PageOutAsync(UIElement el)
    {
        Tx(el);
        await AnimateAsync(el, 0, -40, null, 0.96, 170, EasingMode.EaseIn);
    }

    public static async Task PageInAsync(UIElement el)
    {
        if (el is FrameworkElement fe)
            await WaitLoadedAsync(fe);
        var t = Tx(el);
        el.Opacity = 0;
        t.TranslateX = 52;
        t.TranslateY = 0;
        t.ScaleX = 0.96;
        t.ScaleY = 0.96;
        await AnimateAsync(el, 1, 0, 0, 1, 340, EasingMode.EaseOut);
    }

    public static async Task TabOutAsync(UIElement el)
    {
        await AnimateAsync(el, 0, null, -18, 0.98, 130, EasingMode.EaseIn);
    }

    public static async Task TabInAsync(UIElement el)
    {
        if (el is FrameworkElement fe)
            await WaitLoadedAsync(fe);
        var t = Tx(el);
        el.Opacity = 0;
        t.TranslateX = 0;
        t.TranslateY = 24;
        t.ScaleX = 0.98;
        t.ScaleY = 0.98;
        await AnimateAsync(el, 1, 0, 0, 1, 280, EasingMode.EaseOut);
    }

    public static void PopIn(UIElement el, int delayMs)
    {
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
        var t = Tx(el);
        el.Opacity = 0;
        t.TranslateY = 64;
        t.ScaleX = 0.94;
        t.ScaleY = 0.94;
        await AnimateAsync(el, 1, 0, 0, 1, 360, EasingMode.EaseOut);
    }

    public static async Task DockHideAsync(UIElement el)
    {
        await AnimateAsync(el, 0, 0, 48, 0.95, 200, EasingMode.EaseIn);
        el.Visibility = Visibility.Collapsed;
        var t = Tx(el);
        t.TranslateY = 0;
        t.ScaleX = 1;
        t.ScaleY = 1;
        el.Opacity = 1;
    }

    public static void EnableHoverLift(UIElement el, double scale = 1.045)
    {
        if ((bool)el.GetValue(HoverOnProperty)) return;
        el.SetValue(HoverOnProperty, true);
        Tx(el);
        el.PointerEntered += (_, _) => _ = AnimateAsync(el, null, null, -7, scale, 160);
        el.PointerExited += (_, _) => _ = AnimateAsync(el, null, null, 0, 1, 180);
        el.PointerPressed += (_, _) => _ = AnimateAsync(el, null, null, 0, 0.97, 70);
        el.PointerReleased += (_, _) => _ = AnimateAsync(el, null, null, -7, scale, 120);
    }

    public static void CardEnter(UIElement el, int delayMs = 0, double hoverScale = 1.045)
    {
        EnableHoverLift(el, hoverScale);
        PopIn(el, delayMs);
    }

    public static async Task PulseOnceAsync(UIElement el)
    {
        await AnimateAsync(el, null, null, null, 1.08, 90);
        await AnimateAsync(el, null, null, null, 1, 140);
    }

    public static void StartShine(UIElement shine, TranslateTransform tx)
    {
        shine.Opacity = 0.42;
        var sb = new Storyboard { RepeatBehavior = RepeatBehavior.Forever };
        var a = new DoubleAnimationUsingKeyFrames { Duration = TimeSpan.FromMilliseconds(2800), EnableDependentAnimation = true };
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
    }
}

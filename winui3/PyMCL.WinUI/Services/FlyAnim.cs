using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Animation;
using Microsoft.UI.Xaml.Shapes;
using Windows.Foundation;
using Windows.UI;

namespace PyMCL.Services;

/// <summary>下载飞入：源控件 → 任务导航项抛物线小球 + 落点涟漪。</summary>
public static class FlyAnim
{
    /// <summary>
    /// 在飞的动画连同它的视觉元素。以前只存 <see cref="Storyboard"/>：淘汰时 <c>Stop()</c>
    /// 不触发 <c>Completed</c>，挂在 Completed 上的「移除元素」就永远不执行，overlay 的
    /// 子元素只增不减（Jobs 上限 2 挡不住它）。
    /// </summary>
    private sealed record Job(Storyboard Sb, UIElement El);

    private const int MaxFlies = 2;
    private const int MaxRipples = 8;

    private static readonly List<Job> Jobs = new();
    private static readonly List<Job> Ripples = new();

    /// <summary>停动画 + 摘元素。淘汰路径必须直接调它，不能等 Completed。</summary>
    private static void Retire(Panel overlay, Job job)
    {
        try { job.Sb.Stop(); } catch { }
        try { overlay.Children.Remove(job.El); } catch { }
    }

    public static async Task FlyTo(
        Panel overlay,
        FrameworkElement? source,
        FrameworkElement target,
        string letter,
        Color color,
        int durationMs = 620,
        Action? onLanded = null)
    {
        if (!Motion.AnimationsWanted() || source is null || overlay is null || target is null)
            return;

        var start = CenterIn(overlay, source);
        var end = CenterIn(overlay, target);
        var control = ClampControl(start, end, overlay.ActualWidth, overlay.ActualHeight);

        while (Jobs.Count >= MaxFlies)
        {
            var old = Jobs[0];
            Jobs.RemoveAt(0);
            Retire(overlay, old);
        }

        var ball = new Border
        {
            Width = 44,
            Height = 44,
            CornerRadius = new CornerRadius(10),
            Background = new SolidColorBrush(color),
            IsHitTestVisible = false,
            Child = new TextBlock
            {
                Text = string.IsNullOrEmpty(letter) ? "↓" : letter[..1].ToUpperInvariant(),
                Foreground = new SolidColorBrush(Colors.White),
                FontWeight = Microsoft.UI.Text.FontWeights.Bold,
                FontSize = 16,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center,
            },
            RenderTransformOrigin = new Point(0.5, 0.5),
        };
        var tx = new CompositeTransform { TranslateX = start.X - 22, TranslateY = start.Y - 22 };
        ball.RenderTransform = tx;
        Canvas.SetZIndex(ball, 9999);
        overlay.Children.Add(ball);

        var sb = new Storyboard();
        var frames = 36;
        var ease = new CubicEase { EasingMode = EasingMode.EaseInOut };
        var xAnim = new DoubleAnimationUsingKeyFrames { Duration = TimeSpan.FromMilliseconds(durationMs), EnableDependentAnimation = true };
        var yAnim = new DoubleAnimationUsingKeyFrames { Duration = TimeSpan.FromMilliseconds(durationMs), EnableDependentAnimation = true };
        var sAnim = new DoubleAnimationUsingKeyFrames { Duration = TimeSpan.FromMilliseconds(durationMs), EnableDependentAnimation = true };
        var oAnim = new DoubleAnimationUsingKeyFrames { Duration = TimeSpan.FromMilliseconds(durationMs), EnableDependentAnimation = true };
        for (var i = 0; i <= frames; i++)
        {
            var t = i / (double)frames;
            var p = Bezier(start, control, end, t);
            var kt = KeyTime.FromTimeSpan(TimeSpan.FromMilliseconds(durationMs * t));
            var size = 44 + (14 - 44) * t;
            var scale = size / 44.0;
            xAnim.KeyFrames.Add(new EasingDoubleKeyFrame { KeyTime = kt, Value = p.X - 22, EasingFunction = ease });
            yAnim.KeyFrames.Add(new EasingDoubleKeyFrame { KeyTime = kt, Value = p.Y - 22, EasingFunction = ease });
            sAnim.KeyFrames.Add(new EasingDoubleKeyFrame { KeyTime = kt, Value = scale, EasingFunction = ease });
            var op = t < 0.75 ? 1.0 : Math.Max(0, (1 - t) / 0.25);
            oAnim.KeyFrames.Add(new EasingDoubleKeyFrame { KeyTime = kt, Value = op, EasingFunction = ease });
        }
        Storyboard.SetTarget(xAnim, tx);
        Storyboard.SetTargetProperty(xAnim, "TranslateX");
        Storyboard.SetTarget(yAnim, tx);
        Storyboard.SetTargetProperty(yAnim, "TranslateY");
        Storyboard.SetTarget(sAnim, tx);
        Storyboard.SetTargetProperty(sAnim, "ScaleX");
        var sAnimY2 = new DoubleAnimationUsingKeyFrames { Duration = TimeSpan.FromMilliseconds(durationMs), EnableDependentAnimation = true };
        foreach (var kf in sAnim.KeyFrames)
            sAnimY2.KeyFrames.Add(new EasingDoubleKeyFrame { KeyTime = ((EasingDoubleKeyFrame)kf).KeyTime, Value = ((EasingDoubleKeyFrame)kf).Value, EasingFunction = ease });
        Storyboard.SetTarget(sAnimY2, tx);
        Storyboard.SetTargetProperty(sAnimY2, "ScaleY");
        Storyboard.SetTarget(oAnim, ball);
        Storyboard.SetTargetProperty(oAnim, "Opacity");
        sb.Children.Add(xAnim);
        sb.Children.Add(yAnim);
        sb.Children.Add(sAnim);
        sb.Children.Add(sAnimY2);
        sb.Children.Add(oAnim);

        var job = new Job(sb, ball);
        Jobs.Add(job);

        var tcs = new TaskCompletionSource();
        sb.Completed += (_, _) => tcs.TrySetResult();
        sb.Begin();
        await tcs.Task;
        // 正常走完：Completed 已触发，但淘汰路径可能先把 job 摘掉了（Stop 后 Completed 不会来，
        // 这里也不该重复摘）。用 Remove 的返回值判断是不是自己收的尾。
        if (Jobs.Remove(job))
            overlay.Children.Remove(ball);
        SpawnRipple(overlay, end, color);
        onLanded?.Invoke();
        _ = Motion.PulseOnceAsync(target);
    }

    private static void SpawnRipple(Panel overlay, Point center, Color color)
    {
        var ring = new Ellipse
        {
            Width = 12,
            Height = 12,
            Stroke = new SolidColorBrush(color),
            StrokeThickness = 3,
            Fill = null,
            IsHitTestVisible = false,
            Opacity = 0.55,
            RenderTransformOrigin = new Point(0.5, 0.5),
        };
        var tx = new CompositeTransform { TranslateX = center.X - 6, TranslateY = center.Y - 6, ScaleX = 1, ScaleY = 1 };
        ring.RenderTransform = tx;
        Canvas.SetZIndex(ring, 9998);
        // 涟漪同样登记并设上限：清理挂在 Completed 上，Stop() 后就漏删，反复触发会累积。
        while (Ripples.Count >= MaxRipples)
        {
            var old = Ripples[0];
            Ripples.RemoveAt(0);
            Retire(overlay, old);
        }
        overlay.Children.Add(ring);
        var sb = new Storyboard();
        var dur = new Duration(TimeSpan.FromMilliseconds(420));
        var ease = new CubicEase { EasingMode = EasingMode.EaseOut };
        var sc = new DoubleAnimation { To = 4, Duration = dur, EasingFunction = ease, EnableDependentAnimation = true };
        var scY = new DoubleAnimation { To = 4, Duration = dur, EasingFunction = ease, EnableDependentAnimation = true };
        var op = new DoubleAnimation { To = 0, Duration = dur, EasingFunction = ease };
        Storyboard.SetTarget(sc, tx);
        Storyboard.SetTargetProperty(sc, "ScaleX");
        Storyboard.SetTarget(scY, tx);
        Storyboard.SetTargetProperty(scY, "ScaleY");
        Storyboard.SetTarget(op, ring);
        Storyboard.SetTargetProperty(op, "Opacity");
        sb.Children.Add(sc);
        sb.Children.Add(scY);
        sb.Children.Add(op);
        var job = new Job(sb, ring);
        Ripples.Add(job);
        sb.Completed += (_, _) =>
        {
            // 只有还在册的才由这里摘（被上限淘汰过的已经 Retire 掉了）
            if (Ripples.Remove(job))
                overlay.Children.Remove(ring);
        };
        sb.Begin();
    }

    private static Point CenterIn(UIElement relativeTo, FrameworkElement el)
    {
        try
        {
            var t = el.TransformToVisual(relativeTo);
            var r = t.TransformBounds(new Rect(0, 0, el.ActualWidth, el.ActualHeight));
            return new Point(r.X + r.Width / 2, r.Y + r.Height / 2);
        }
        catch
        {
            return new Point(relativeTo.ActualSize.X / 2, relativeTo.ActualSize.Y - 28);
        }
    }

    private static Point ClampControl(Point p0, Point p1, double w, double h)
    {
        var midX = (p0.X + p1.X) / 2;
        var dist = Math.Sqrt(Math.Pow(p1.X - p0.X, 2) + Math.Pow(p1.Y - p0.Y, 2));
        var arc = Math.Max(48, Math.Min(150, dist * 0.35));
        var cy = Math.Min(p0.Y, p1.Y) - arc;
        const double margin = 8;
        cy = Math.Max(margin, Math.Min(cy, h - margin));
        midX = Math.Max(margin, Math.Min(midX, w - margin));
        return new Point(midX, cy);
    }

    private static Point Bezier(Point p0, Point pc, Point p1, double t)
    {
        var u = 1 - t;
        return new Point(
            u * u * p0.X + 2 * u * t * pc.X + t * t * p1.X,
            u * u * p0.Y + 2 * u * t * pc.Y + t * t * p1.Y);
    }

    public static Color ParseColor(string? hex, Color fallback)
    {
        if (string.IsNullOrWhiteSpace(hex)) return fallback;
        hex = hex.Trim().TrimStart('#');
        try
        {
            if (hex.Length == 6)
            {
                var r = Convert.ToByte(hex[..2], 16);
                var g = Convert.ToByte(hex[2..4], 16);
                var b = Convert.ToByte(hex[4..6], 16);
                return Color.FromArgb(255, r, g, b);
            }
        }
        catch { }
        return fallback;
    }
}

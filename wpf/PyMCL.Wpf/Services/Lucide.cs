using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using Path = System.Windows.Shapes.Path;

namespace PyMCL.Services;

/// <summary>
/// AI 页用的几枚 Lucide 线性图标（ISC）+ 两个小动效，与 Qt 端 app/lucide.py 同一套数据。
/// 24×24 坐标、线宽 2、圆头圆角，按 LayoutTransform 缩到 16px；圆已换成两段圆弧。
/// 只收 AI 页真用到的：思考行 brain + chevron-right，工具行 loader / check / slash / x，
/// 搜索 / 读 / 写三类工具的类型图标。启动器特有的安装 / 启动 / 删除 / 诊断类在 ZCode
/// 里没有对应物，不硬套。
/// </summary>
public static class Lucide
{
    public const string Brain =
        "M12 18V5 M15 13a4.17 4.17 0 0 1-3-4 4.17 4.17 0 0 1-3 4 M17.598 6.5A3 3 0 1 0 12 5a3 3 0 1 0-5.598 1.5 " +
        "M17.997 5.125a4 4 0 0 1 2.526 5.77 M18 18a4 4 0 0 0 2-7.464 M19.967 17.483A4 4 0 1 1 12 18a4 4 0 1 1-7.967-.517 " +
        "M6 18a4 4 0 0 1-2-7.464 M6.003 5.125a4 4 0 0 0-2.526 5.77";
    public const string ChevronRight = "M9 18l6-6-6-6";
    public const string LoaderCircle = "M21 12a9 9 0 1 1-6.219-8.56";
    private const string Circle12 = "M2 12a10 10 0 1 0 20 0a10 10 0 1 0-20 0";
    public const string CircleCheck = Circle12 + " M9 12l2 2 4-4";
    public const string CircleSlash2 = Circle12 + " M22 2L2 22";
    public const string CircleX = Circle12 + " M15 9l-6 6 M9 9l6 6";
    public const string Search = "M21 21l-4.34-4.34 M3 11a8 8 0 1 0 16 0a8 8 0 1 0-16 0";
    public const string FileText =
        "M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z " +
        "M14 2v5a1 1 0 0 0 1 1h5 M10 9H8 M16 13H8 M16 17H8";
    public const string FilePenLine =
        "M14.364 13.634a2 2 0 0 0-.506.854l-.837 2.87a.5.5 0 0 0 .62.62l2.87-.837a2 2 0 0 0 .854-.506l4.013-4.009a1 1 0 0 0-3.004-3.004z " +
        "M14.487 7.858A1 1 0 0 1 14 7V2 M20 19.645V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l2.516 2.516 M8 18h1";
    // ---- 权限管理：档位卡片 / 规则行为 / 确认卡 ----
    public const string ShieldAlert =
        "M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z " +
        "M12 8v4 M12 16h.01";
    public const string Eye =
        "M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0 M9 12a3 3 0 1 0 6 0a3 3 0 1 0-6 0";
    public const string Sparkles =
        "M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z " +
        "M20 2v4 M22 4h-4 M2 20a2 2 0 1 0 4 0a2 2 0 1 0-4 0";
    public const string SlidersHorizontal =
        "M10 5H3 M12 19H3 M14 3v4 M16 17v4 M21 12h-9 M21 19h-5 M21 5h-7 M8 10v4 M8 12H3";
    public const string Ban = Circle12 + " M4.929 4.929L19.07 19.071";
    public const string Trash2 =
        "M10 11v6 M14 11v6 M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6 M3 6h18 M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2";

    /// <summary>工具名 → 类型图标。只映射 ZCode 也有的三类；其余返回 null，由状态图标占位。</summary>
    public static string? ToolIcon(string? tool) => tool switch
    {
        "search_versions" or "search_mods" or "search_modpacks" or "search_content" or "search_worlds" => Search,
        "read_mod_config" or "get_latest_log" or "get_crash_report" or "read_artifact" or "list_mod_configs" => FileText,
        "write_mod_config" => FilePenLine,
        _ => null,
    };

    public static Path Icon(string data, double size = 16, string brushKey = "B.InkMuted")
    {
        var scale = size / 24.0;
        var p = new Path
        {
            Data = Geometry.Parse(data),
            Width = 24,
            Height = 24,
            Stretch = Stretch.None,
            StrokeThickness = 2,
            StrokeStartLineCap = PenLineCap.Round,
            StrokeEndLineCap = PenLineCap.Round,
            StrokeLineJoin = PenLineJoin.Round,
            LayoutTransform = new ScaleTransform(scale, scale),
            RenderTransformOrigin = new Point(0.5, 0.5),
            SnapsToDevicePixels = false,
            IsHitTestVisible = false,
        };
        p.SetResourceReference(Shape.StrokeProperty, brushKey);
        return p;
    }

    /// <summary>loader-circle 一秒一圈；动效关掉时就是静态图标。</summary>
    public static Path Spinner(double size = 16, string brushKey = "B.AccentDeep")
    {
        var p = Icon(LoaderCircle, size, brushKey);
        if (!Motion.Enabled) return p;
        var rot = new RotateTransform(0);
        p.RenderTransform = rot;
        rot.BeginAnimation(RotateTransform.AngleProperty, new DoubleAnimation(0, 360, TimeSpan.FromSeconds(1))
        {
            RepeatBehavior = RepeatBehavior.Forever,
        });
        return p;
    }

    /// <summary>
    /// 生成图标（gpt-image-2.5 出图，base64 内嵌在 LucideAssets）：用位图的 alpha 通道
    /// 做 OpacityMask 套主题色，与线稿图标同一视觉；没有该工具的资产时退回转圈。
    /// </summary>
    public static FrameworkElement Asset(string tool, double size = 16, string brushKey = "B.AccentDeep")
    {
        if (!LucideAssets.Icons.TryGetValue(tool ?? "", out var bytes))
            return Spinner(size, brushKey);
        var bi = new BitmapImage();
        using (var ms = new MemoryStream(bytes))
        {
            bi.BeginInit();
            bi.StreamSource = ms;
            bi.CacheOption = BitmapCacheOption.OnLoad;
            bi.EndInit();
        }
        bi.Freeze();
        var rect = new Rectangle
        {
            Width = size,
            Height = size,
            IsHitTestVisible = false,
        };
        rect.SetResourceReference(Shape.FillProperty, brushKey);
        rect.OpacityMask = new ImageBrush { ImageSource = bi, Stretch = Stretch.Uniform };
        return rect;
    }

    /// <summary>把 chevron 转到 open 对应的角度（右 → 下），带一小段过渡。</summary>
    public static void Rotate(Path chevron, bool open)
    {
        if (chevron.RenderTransform is not RotateTransform rot)
            chevron.RenderTransform = rot = new RotateTransform(0);
        var to = open ? 90 : 0;
        if (!Motion.Enabled)
        {
            rot.BeginAnimation(RotateTransform.AngleProperty, null);
            rot.Angle = to;
            return;
        }
        rot.BeginAnimation(RotateTransform.AngleProperty, new DoubleAnimation(to, TimeSpan.FromMilliseconds(160))
        {
            EasingFunction = new CubicEase { EasingMode = EasingMode.EaseOut },
        });
    }

    /// <summary>
    /// 文字流光：一道淡色光带从左扫到右再停两秒，循环——ZCode 的 .animated-gradient-text。
    /// on=false 恢复原来的资源色。基色取当前 Foreground（资源色的快照，切主题后再开一次即可）。
    /// </summary>
    public static void Shimmer(TextBlock tb, bool on, string restoreKey)
    {
        if (!on || !Motion.Enabled)
        {
            tb.SetResourceReference(TextBlock.ForegroundProperty, restoreKey);
            return;
        }
        var strong = (tb.Foreground as SolidColorBrush)?.Color
                     ?? (tb.TryFindResource(restoreKey) as SolidColorBrush)?.Color
                     ?? Colors.Gray;
        var soft = Color.FromArgb(0x38, strong.R, strong.G, strong.B);
        // 渐变「贴图」宽 3 倍：前 2s 从 X=-2 滑到 0，光带（贴图 50% 处）由 -0.5 扫到 1.5；后 2s 停在屏外
        var slide = new TranslateTransform(-2, 0);
        var brush = new LinearGradientBrush
        {
            StartPoint = new Point(0, 0),
            EndPoint = new Point(1, 0),
            MappingMode = BrushMappingMode.RelativeToBoundingBox,
            RelativeTransform = new TransformGroup
            {
                Children = { new ScaleTransform(3, 1), slide },
            },
        };
        brush.GradientStops.Add(new GradientStop(strong, 0));
        brush.GradientStops.Add(new GradientStop(strong, 0.34));
        brush.GradientStops.Add(new GradientStop(soft, 0.5));
        brush.GradientStops.Add(new GradientStop(strong, 0.66));
        brush.GradientStops.Add(new GradientStop(strong, 1));
        var anim = new DoubleAnimationUsingKeyFrames { RepeatBehavior = RepeatBehavior.Forever };
        anim.KeyFrames.Add(new LinearDoubleKeyFrame(-2, KeyTime.FromTimeSpan(TimeSpan.Zero)));
        anim.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromTimeSpan(TimeSpan.FromSeconds(2))));
        anim.KeyFrames.Add(new LinearDoubleKeyFrame(0, KeyTime.FromTimeSpan(TimeSpan.FromSeconds(4))));
        slide.BeginAnimation(TranslateTransform.XProperty, anim);
        tb.Foreground = brush;
    }
}

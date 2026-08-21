using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Media;

namespace PyMCL.Services;

/// <summary>
/// 代码里建控件时取主题笔刷的统一入口。
///
/// 各页面原先直接 <c>new SolidColorBrush(Color.FromArgb(255, 136, 136, 136))</c> 这样写死颜色，
/// 一份值在浅色/深色/高对比度下共用：#888 压到深色卡片上对比度不足，浅色分隔线在深色下几乎看不见。
/// 走这里取，颜色就统一由 Styles/Theme.xaml 的 ThemeDictionaries 按当前主题给。
/// </summary>
internal static class ThemeBrushes
{
    public static Brush Get(string key) => (Brush)Application.Current.Resources[key];

    /// <summary>次要说明文字（原 #888888）。</summary>
    public static Brush Mute => Get("TextFillColorSecondaryBrush");

    /// <summary>品牌绿填充（进度条、角标底色）。</summary>
    public static Brush Accent => Get("AccentFillColorDefaultBrush");

    /// <summary>品牌绿文字（原 #1B7A54，深色下自动提亮）。</summary>
    public static Brush AccentText => Get("PclGreenText");

    /// <summary>列表行分隔线（原 #EEF3F7）。</summary>
    public static Brush Divider => Get("PclDivider");

    /// <summary>AI 用户气泡底色（原 #E8F6EF）。</summary>
    public static Brush AiUserBubble => Get("PclAiUserBubble");
}

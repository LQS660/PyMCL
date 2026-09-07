using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace PyMCL.Services;

/// <summary>
/// 破坏性操作的二次确认。
///
/// 版本卸载和实例删除本来就各自写了一份 ContentDialog，但账号 / 模组 / AI 会话三处漏了，
/// 点一下就直接删。抽成公共入口，省得每加一个删除按钮就得记得再抄一遍。
/// </summary>
internal static class Dialogs
{
    public static async Task<bool> ConfirmAsync(
        XamlRoot? root, string title, string message, string confirmText = "删除")
    {
        if (root is null) return false;
        var dlg = new ContentDialog
        {
            Title = title,
            Content = new TextBlock { Text = message, TextWrapping = TextWrapping.Wrap },
            PrimaryButtonText = confirmText,
            CloseButtonText = "取消",
            DefaultButton = ContentDialogButton.Close,
            XamlRoot = root,
        };
        return await dlg.ShowAsync() == ContentDialogResult.Primary;
    }
}

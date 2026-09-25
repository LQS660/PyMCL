using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using PyMCL.Models;
using PyMCL.Services;

namespace PyMCL.Pages;

/// <summary>账号管理：离线 / 微软 / 皮肤站（authlib）/ 统一通行证（Nide8），外加离线账号的自定义皮肤。</summary>
public sealed class AccountPage : PageBase
{
    public override string Title => L("账号");

    private readonly SPanel _list = Ui.V(10);
    private readonly TextBlock _count = Ui.Muted("");
    private readonly ThumbTile _heroAvatar = new("?", 96, 14);
    private readonly Image _heroBody = new() { Stretch = Stretch.Uniform, Height = 190 };
    private readonly TextBlock _heroName = Ui.Txt(L("未登录"), 15, true).Trim();
    private readonly TextBlock _heroKind = Ui.Small("");
    private string? _loginTask;
    private string? _authlibTask;
    private string? _nide8Task;
    private Dlg.Layer? _loginLayer;
    private TextBlock? _loginHint, _loginCode;
    private string _loginUri = "";

    public AccountPage()
    {
        var offline = Ui.Btn(L("添加离线账号"), BtnKind.Primary, (_, _) => Run(AddOfflineAsync, L("添加失败")), Ico.Add);
        var ms = Ui.Btn(L("微软登录"), BtnKind.Soft, (_, _) => Run(MicrosoftLoginAsync, L("微软登录失败")), Ico.User);
        var authlib = Ui.Btn(L("皮肤站登录"), BtnKind.Chip, (_, _) => Run(AuthlibLoginAsync, L("皮肤站登录失败")), Ico.Shield);
        var nide8 = Ui.Btn(L("统一通行证"), BtnKind.Chip, (_, _) => Run(Nide8LoginAsync, L("统一通行证登录失败")), Ico.Link);
        var refresh = Ui.IconBtn(Ico.Refresh, L("刷新"), (_, _) => Run(LoadAsync));
        var head = Ui.Section(L("账号"), L("启动游戏时使用标记为「当前」的账号"),
            Ui.H(8, _count.VCenter(), refresh, nide8, authlib, ms, offline));

        // 名字列必须拿到有限宽度 Trim 才会出省略号：放进 H() 这种横向 StackPanel 里宽度无限，
        // 只会被 240 宽的卡片边框硬裁，长名字就成了无省略号的半截。
        var heroInfo = Ui.G(null, "Auto,*");
        heroInfo.Add(_heroAvatar, 0, 0);
        heroInfo.Add(Ui.V(2, _heroName, _heroKind).VCenter().M(10, 0, 0, 0), 0, 1);
        var hero = Ui.Card(Ui.V(10,
            _heroBody,
            heroInfo), 16);
        hero.Width = 240;
        _heroBody.Visibility = Visibility.Collapsed;
        RenderOptions.SetBitmapScalingMode(_heroBody, BitmapScalingMode.NearestNeighbor);

        var cols = Ui.G(null, "Auto,*");
        cols.Add(hero.M(0, 0, 14, 0).VTop(), 0, 0);
        cols.Add(_list, 0, 1);
        Content = ScrollBody(head, cols);
    }

    protected override async Task LoadAsync()
    {
        var rows = await Api.TryCallAsync<List<AccountRow>>("get_account_rows", null, new()) ?? new();
        _list.Children.Clear();
        _count.Text = L("共 {0} 个", rows.Count);
        if (rows.Count == 0)
        {
            _list.Children.Add(Ui.Empty(Ico.User, L("还没有账号"), L("添加离线账号，或用微软 / 皮肤站 / 统一通行证登录")));
            await RenderHeroAsync(null);
            return;
        }
        foreach (var r in rows) _list.Children.Add(Row(r));
        Motion.Stagger(_list, 22, 200, 10);
        await RenderHeroAsync(rows.FirstOrDefault(r => r.Active) ?? rows[0]);
    }

    /// <summary>左侧大图：绑了本地皮肤的离线账号画那张，其余走 skin_urls 拿在线头像 / 全身像。</summary>
    private async Task RenderHeroAsync(AccountRow? acc)
    {
        _heroBody.Source = null;
        _heroBody.Visibility = Visibility.Collapsed;
        if (acc is null)
        {
            _heroName.Text = L("未登录");
            _heroKind.Text = L("先添加一个账号");
            _heroAvatar.SetUrl(null);
            return;
        }
        _heroName.Text = acc.Name;
        _heroKind.Text = TypeLabel(acc);

        if (!string.IsNullOrEmpty(acc.SkinFile))
        {
            var skin = await Api.TryCallAsync<AccountSkin>("get_account_skin", new { name = acc.Name });
            var png = SkinPng.Decode(skin?.DataUrl);
            if (png != null)
            {
                _heroBody.Source = SkinPng.FrontView(png, skin!.Slim);
                _heroBody.Visibility = Visibility.Visible;
                _heroAvatar.SetUrl(null);
                return;
            }
        }

        // 在线头像走 skin_urls：桥知道每种账号该去哪个皮肤站取图，前端不猜 URL。
        var urls = await Api.TryCallAsync<SkinUrls>("skin_urls", new { account_name = acc.Name });
        _heroAvatar.SetUrl(urls?.Avatar ?? acc.Avatar);
        var body = urls?.Body ?? acc.Body;
        if (!string.IsNullOrWhiteSpace(body))
        {
            var bmp = await Thumbs.LoadAsync(body, 190);
            if (bmp != null)
            {
                _heroBody.Source = bmp;
                _heroBody.Visibility = Visibility.Visible;
            }
        }
    }

    private static string TypeLabel(AccountRow acc) => acc.Type switch
    {
        "microsoft" => L("微软"),
        "offline" => L("离线"),
        "authlib" => L("皮肤站"),
        "nide8" => L("统一通行证"),
        _ => string.IsNullOrEmpty(acc.Api)
            ? (string.IsNullOrEmpty(acc.Type) ? L("其他") : acc.Type)
            : L("皮肤站"),
    };

    private UIElement Row(AccountRow acc)
    {
        var avatar = new ThumbTile(acc.Name, 40, 20);
        avatar.SetUrl(string.IsNullOrEmpty(acc.SkinFile) ? acc.Avatar : null);

        var typeText = TypeLabel(acc);
        var nameRow = Ui.H(7,
            Ui.Txt(acc.Name, 13.5, true).Trim().VCenter(),
            acc.Active ? Ui.Tag(L("当前"), "B.OnAccent", "B.Accent") : null,
            Ui.Tag(typeText),
            string.IsNullOrEmpty(acc.SkinFile) ? null : Ui.Tag(L("自定义皮肤"), "B.OnAccent", "B.Ok"));
        var sub = string.IsNullOrEmpty(acc.Uuid) ? typeText + L("账号") : "UUID " + acc.Uuid;
        if (sub.Length > 40) sub = sub.Substring(0, 40) + "…";

        var actions = Ui.H(6);
        if (acc.Type == "offline")
            actions.Children.Add(Ui.Btn(L("皮肤"), BtnKind.Chip,
                (_, _) => Run(() => EditSkinAsync(acc), L("皮肤没能保存")), Ico.Image));
        if (!acc.Active)
            actions.Children.Add(Ui.Btn(L("设为当前"), BtnKind.Soft,
                (_, _) => Run(() => SetActiveAsync(acc.Name), L("切换失败")), Ico.Check));
        actions.Children.Add(Ui.Btn(L("删除"), BtnKind.Ghost,
            (_, _) => Run(() => DeleteAsync(acc), L("删除失败"))));
        actions.VCenter();

        var g = Ui.G(null, "Auto,*,Auto");
        g.Add(avatar.M(0, 0, 12, 0), 0, 0);
        g.Add(Ui.V(3, nameRow, Ui.Small(sub)).VCenter(), 0, 1);
        g.Add(actions, 0, 2);
        var card = Ui.RowCard(g, padding: 12);
        Motion.HoverLift(card, 1.004, 1, 16);
        return card;
    }

    private async Task SetActiveAsync(string name)
    {
        await Api.CallAsync<object>("set_active_account", new { name });
        Toast(L("已切换"), L("当前账号：{0}", name), ToastKind.Success);
        await LoadAsync();
    }

    private async Task DeleteAsync(AccountRow acc)
    {
        if (!await Dlg.Confirm(L("删除账号"),
                L("将删除「{0}」。微软账号的刷新令牌也会一并丢失，需要重新走设备码登录。", acc.Name),
                L("删除"), L("取消"), true)) return;
        await Api.CallAsync<object>("remove_account", new { name = acc.Name });
        Toast(L("已删除"), acc.Name, ToastKind.Success);
        await LoadAsync();
    }

    private async Task AddOfflineAsync()
    {
        var name = Ui.Input(L("例如 Steve"));
        var skin = Ui.Combo(new[] { L("默认"), "Steve", "Alex" });
        var body = Ui.V(8, Ui.Muted(L("离线模式，无正版验证")), name, Ui.Field(L("默认皮肤"), skin, labelWidth: 78));
        if (!await Dlg.Ask(L("添加离线账号"), body, L("添加"))) return;
        if (string.IsNullOrWhiteSpace(name.Text))
        {
            Toast(L("缺少名字"), L("请填写离线角色名"), ToastKind.Warning);
            return;
        }
        await Api.CallAsync<object>("add_offline_account", new
        {
            username = name.Text.Trim(),
            skin = skin.Str() switch { "Steve" => "steve", "Alex" => "alex", _ => "default" },
        });
        Toast(L("已添加"), name.Text.Trim(), ToastKind.Success);
        await LoadAsync();
    }

    // ==================== 离线自定义皮肤 ====================
    private async Task EditSkinAsync(AccountRow acc)
    {
        var message = await EditSkinCoreAsync(acc, "");
        if (!string.IsNullOrEmpty(message)) Toast(L("皮肤已更新"), message, ToastKind.Success);
        await LoadAsync();
    }

    /// <summary>把皮肤拖进窗口时走这条：替用户先挑好那张，开框就能看到预览。</summary>
    internal static async Task<string> EditSkinExternalAsync(AccountRow acc, string presetPath)
    {
        var message = await EditSkinCoreAsync(acc, presetPath);
        if (AppServices.Window?.GetPage("account") is AccountPage page) await page.RefreshAsync();
        return message;
    }

    /// <summary>
    /// 换一张自定义皮肤，或清回游戏默认。只对离线账号有效——正版和皮肤站的皮肤在各自网站上改。
    /// 真正让它显示出来的是启动时拉起的本地 Yggdrasil 服务。
    /// 返回给用户看的一句话；空串 = 什么都没改。
    /// </summary>
    private static async Task<string> EditSkinCoreAsync(AccountRow acc, string presetPath)
    {
        var Api = AppServices.Client;
        var current = await Api.TryCallAsync<AccountSkin>("get_account_skin", new { name = acc.Name }) ?? new AccountSkin();
        var picked = presetPath ?? "";
        var clear = false;

        var preview = new Image { Height = 200, Stretch = Stretch.Uniform };
        RenderOptions.SetBitmapScalingMode(preview, BitmapScalingMode.NearestNeighbor);
        var previewHint = Ui.Muted(L("还没设皮肤")).Center();
        var fileLabel = Ui.Small(string.IsNullOrEmpty(current.SkinFile) ? L("游戏默认皮肤") : current.SkinFile).Center();
        var model = Ui.Combo(new[] { L("宽臂（Steve）"), L("细臂（Alex）") }, current.Slim ? L("细臂（Alex）") : L("宽臂（Steve）"));
        var clearBtn = Ui.Btn(L("清除，用游戏默认"), BtnKind.Chip, null, Ico.Trash);
        clearBtn.IsEnabled = !string.IsNullOrEmpty(current.SkinFile) || picked.Length > 0;
        if (picked.Length > 0) fileLabel.Text = picked;

        byte[]? SourcePng()
        {
            if (picked.Length > 0)
            {
                try { return File.ReadAllBytes(picked); }
                catch { return null; }
            }
            return SkinPng.Decode(current.DataUrl);
        }

        void Refresh()
        {
            if (clear)
            {
                preview.Source = null;
                previewHint.Text = L("保存后清除，恢复游戏默认皮肤");
                previewHint.Visibility = Visibility.Visible;
                return;
            }
            var png = SourcePng();
            var bmp = png is null ? null : SkinPng.FrontView(png, model.SelectedIndex == 1);
            preview.Source = bmp;
            previewHint.Visibility = bmp is null ? Visibility.Visible : Visibility.Collapsed;
            previewHint.Text = png is null ? L("还没设皮肤") : L("这张图读不出来");
        }

        var pick = Ui.Btn(L("选择 PNG"), BtnKind.Primary, (_, _) =>
        {
            var path = Dlg.PickFile(L("PNG 图片 (*.png)|*.png"), L("选择皮肤 PNG"));
            if (path is null) return;
            picked = path;
            clear = false;
            clearBtn.IsEnabled = true;
            fileLabel.Text = path;
            Refresh();
        }, Ico.Image);
        clearBtn.Click += (_, _) =>
        {
            picked = "";
            clear = true;
            clearBtn.IsEnabled = false;
            fileLabel.Text = L("保存后清除，恢复游戏默认皮肤");
            Refresh();
        };
        model.SelectionChanged += (_, _) => Refresh();
        Refresh();

        var previewBox = Ui.Pane(new Grid { Children = { previewHint, preview } }, radius: 10, padding: 10);
        previewBox.Width = 150;
        var body = Ui.V(10,
            Ui.Muted(L("64x64 或 64x32 的 PNG。进游戏后由启动器自带的本地皮肤服务发给游戏，不需要联网。")).Wrap(),
            previewBox.Center(),
            fileLabel,
            Ui.H(8, pick, clearBtn),
            Ui.Field(L("手臂模型"), model, labelWidth: 78));
        if (!await Dlg.Ask(L("「{0}」的皮肤", acc.Name), body, L("保存"), L("取消"), false, 460)) return "";

        if (clear)
        {
            await Api.CallAsync<object>("set_account_skin", new { name = acc.Name });
            return L("已清除，回到游戏默认皮肤");
        }
        var path = picked;
        // 只改了手臂模型：把账号里那张原样再交一遍，后端认得同一个文件。
        if (path.Length == 0 && current.SkinFile.Length == 0) return "";
        await Api.CallAsync<object>("set_account_skin", new
        {
            name = acc.Name,
            path,
            model = model.SelectedIndex == 1 ? "slim" : "classic",
            data = path.Length == 0 ? current.DataUrl : "",
        });
        return L("下次启动游戏时生效");
    }

    // ==================== 微软登录 ====================
    private async Task MicrosoftLoginAsync()
    {
        if (_loginLayer != null) return;
        var hint = Ui.Muted(L("正在获取登录代码…"));
        hint.TextWrapping = TextWrapping.Wrap;
        var code = new TextBlock { FontSize = 26, FontWeight = FontWeights.Bold, Text = "------" };
        code.SetResourceReference(TextBlock.ForegroundProperty, "B.AccentDeep");
        _loginHint = hint;
        _loginCode = code;
        _loginUri = "";
        var copy = Ui.Btn(L("复制代码"), BtnKind.Chip, (_, _) =>
        {
            try
            {
                if (_loginCode is { } c) Clipboard.SetText(c.Text);
                Toast(L("已复制"), L("代码已放进剪贴板"), ToastKind.Success);
            }
            catch { }
        }, Ico.Copy);
        var open = Ui.Btn(L("打开浏览器"), BtnKind.Primary, (_, _) =>
        {
            if (!string.IsNullOrEmpty(_loginUri)) Ui.OpenUrl(_loginUri);
        }, Ico.Link);
        var body = Ui.V(10, hint, code, Ui.H(8, copy, open));
        _loginLayer = Dlg.Panel(L("微软账号登录"), body, 460, () =>
        {
            _loginLayer = null;
            if (_loginTask != null) _ = Api.TryCallAsync<object>("cancel_task", new { task_id = _loginTask });
        });
        _loginTask = await Api.StartTaskAsync("start_microsoft_login");
    }

    // ==================== 皮肤站登录 ====================
    private async Task AuthlibLoginAsync()
    {
        var presets = await Api.TryCallAsync<List<AuthlibPreset>>("authlib_presets", null, new()) ?? new();
        var api = Ui.Input("https://littleskin.cn/api/yggdrasil", presets.FirstOrDefault()?.Api ?? "");
        var user = Ui.Input(L("邮箱 / 用户名"));
        var pw = Ui.Pw();
        var pick = Ui.Combo(presets.Select(p => p.Name));
        pick.SelectionChanged += (_, _) =>
        {
            var hit = presets.FirstOrDefault(p => p.Name == pick.Str());
            if (hit != null) api.Text = hit.Api;
        };
        var body = Ui.V(8, Ui.Muted(L("选择皮肤站，或直接填 Yggdrasil API 地址")), pick, api, user, pw);
        if (!await Dlg.Ask(L("皮肤站登录"), body, L("登录"))) return;
        if (string.IsNullOrWhiteSpace(api.Text) || string.IsNullOrWhiteSpace(user.Text))
        {
            Toast(L("填写不完整"), L("API 地址和用户名都不能为空"), ToastKind.Warning);
            return;
        }
        _authlibTask = await Api.StartTaskAsync("start_authlib_login", new
        {
            api = api.Text.Trim(),
            username = user.Text.Trim(),
            password = pw.Password ?? "",
        });
        Toast(L("正在登录"), L("皮肤站验证中，结果看下载任务"), ToastKind.Info);
    }

    // ==================== 统一通行证（Nide8） ====================
    private async Task Nide8LoginAsync()
    {
        var sid = Ui.Input(L("服务器 ID / 链接"));
        var user = Ui.Input(L("用户名"));
        var pw = Ui.Pw();
        var body = Ui.V(8,
            Ui.Muted(L("填 32 位服务器 ID，或把含该 ID 的链接贴进来")),
            sid, user, pw);
        if (!await Dlg.Ask(L("统一通行证登录"), body, L("登录"))) return;
        if (string.IsNullOrWhiteSpace(sid.Text))
        {
            Toast(L("缺少服务器 ID"), L("请填写统一通行证服务器 ID"), ToastKind.Warning);
            Motion.Shake(sid);
            return;
        }
        _nide8Task = await Api.StartTaskAsync("start_nide8_login", new
        {
            server_id = sid.Text.Trim(),
            username = user.Text?.Trim() ?? "",
            password = pw.Password ?? "",
        });
        Toast(L("正在登录"), L("统一通行证验证中，结果看下载任务"), ToastKind.Info);
    }

    // ==================== 事件 ====================
    public override void OnEvent(BridgeEvent ev)
    {
        switch (ev.Event)
        {
            case "login_code" when _loginLayer != null:
                _loginUri = ev.Uri;
                if (_loginCode != null) _loginCode.Text = ev.Code;
                if (_loginHint != null) _loginHint.Text = L("在浏览器打开下面的地址并输入代码：\n") + ev.Uri;
                break;
            case "login_status" when _loginHint != null:
                _loginHint.Text = ev.Text;
                break;
            case "finished" when ev.TaskId == _loginTask:
                _loginTask = null;
                if (ev.Success)
                {
                    _loginLayer?.Close();
                    _loginLayer = null;
                    Toast(L("登录成功"), L("微软账号已加入列表"), ToastKind.Success);
                    Run(LoadAsync);
                }
                else if (_loginHint != null) _loginHint.Text = ev.Message;
                break;
            case "finished" when ev.TaskId == _authlibTask:
                _authlibTask = null;
                if (ev.Success)
                {
                    Toast(L("登录成功"), L("皮肤站账号已加入列表"), ToastKind.Success);
                    Run(LoadAsync);
                }
                else Toast(L("登录失败"), ev.Message, ToastKind.Error);
                break;
            case "finished" when ev.TaskId == _nide8Task:
                _nide8Task = null;
                if (ev.Success)
                {
                    Toast(L("登录成功"), L("统一通行证账号已加入列表"), ToastKind.Success);
                    Run(LoadAsync);
                }
                else Toast(L("登录失败"), ev.Message, ToastKind.Error);
                break;
        }
    }
}

/// <summary>皮肤 PNG 的解码与正面预览。皮肤是 64x64 / 64x32 的像素图，放大一律用最近邻。</summary>
internal static class SkinPng
{
    public static byte[]? Decode(string? dataUrl)
    {
        if (string.IsNullOrWhiteSpace(dataUrl)) return null;
        var raw = dataUrl.StartsWith("data:", StringComparison.Ordinal)
            ? dataUrl.Substring(dataUrl.IndexOf(',') + 1)
            : dataUrl;
        try { return Convert.FromBase64String(raw); }
        catch (FormatException) { return null; }
    }

    /// <summary>把皮肤图里的头 / 身 / 手 / 腿拼成一个正面小人。读不出来返回 null。</summary>
    public static BitmapSource? FrontView(byte[] png, bool slim)
    {
        var src = Load(png);
        if (src is null) return null;
        var scale = src.PixelWidth / 64.0;
        if (scale <= 0) return null;
        var legacy = src.PixelHeight * 2 <= src.PixelWidth;   // 64x32 的老皮肤没有第二层手腿
        var armW = slim ? 3 : 4;

        var dv = new DrawingVisual();
        // 皮肤是像素画，放大只能用最近邻；默认的线性插值会糊成一团。
        RenderOptions.SetBitmapScalingMode(dv, BitmapScalingMode.NearestNeighbor);
        using (var dc = dv.RenderOpen())
        {
            void Part(int sx, int sy, int sw, int sh, double dx, double dy, bool mirror = false)
            {
                var crop = Crop(src, sx, sy, sw, sh, scale);
                if (crop is null) return;
                var rect = new Rect(dx, dy, sw, sh);
                if (mirror)
                {
                    dc.PushTransform(new ScaleTransform(-1, 1, dx + sw / 2.0, 0));
                    dc.DrawImage(crop, rect);
                    dc.Pop();
                }
                else dc.DrawImage(crop, rect);
            }

            Part(8, 8, 8, 8, 4, 0);                                    // 头
            Part(20, 20, 8, 12, 4, 8);                                 // 身
            Part(44, 20, armW, 12, 4 - armW, 8);                       // 右手
            if (legacy) Part(44, 20, armW, 12, 12, 8, mirror: true);   // 老皮肤左手镜像右手
            else Part(36, 52, armW, 12, 12, 8);
            Part(4, 20, 4, 12, 4, 20);                                 // 右腿
            if (legacy) Part(4, 20, 4, 12, 8, 20, mirror: true);
            else Part(20, 52, 4, 12, 8, 20);

            // 外层。不画的话戴帽子 / 穿外套的皮肤在预览里会少一层，跟进游戏看到的对不上。
            Part(40, 8, 8, 8, 4, 0);                                   // 帽子（两种格式都有）
            if (!legacy)
            {
                Part(20, 36, 8, 12, 4, 8);                             // 外套
                Part(44, 36, armW, 12, 4 - armW, 8);                   // 右袖
                Part(52, 52, armW, 12, 12, 8);                         // 左袖
                Part(4, 36, 4, 12, 4, 20);                             // 右腿外层
                Part(4, 52, 4, 12, 8, 20);                             // 左腿外层
            }
        }

        // 画布是 16x32 个设计单位，放大 8 倍存成 128x256 的位图。dpi 保持 96：
        // RenderTargetBitmap 按 dpi/96 再缩一次，这里改 dpi 会把图放出画布外裁掉。
        const int zoom = 8;
        var scaled = new DrawingVisual();
        RenderOptions.SetBitmapScalingMode(scaled, BitmapScalingMode.NearestNeighbor);
        using (var dc = scaled.RenderOpen())
        {
            dc.PushTransform(new ScaleTransform(zoom, zoom));
            dc.DrawDrawing(dv.Drawing);
            dc.Pop();
        }
        var target = new RenderTargetBitmap(16 * zoom, 32 * zoom, 96, 96, PixelFormats.Pbgra32);
        target.Render(scaled);
        target.Freeze();
        return target;
    }

    private static BitmapSource? Load(byte[] png)
    {
        try
        {
            var bmp = new BitmapImage();
            bmp.BeginInit();
            bmp.CacheOption = BitmapCacheOption.OnLoad;
            bmp.CreateOptions = BitmapCreateOptions.IgnoreColorProfile;
            bmp.StreamSource = new MemoryStream(png);
            bmp.EndInit();
            bmp.Freeze();
            return bmp.PixelWidth >= 64 ? bmp : null;
        }
        catch { return null; }
    }

    private static BitmapSource? Crop(BitmapSource src, int x, int y, int w, int h, double scale)
    {
        var rect = new Int32Rect(
            (int)(x * scale), (int)(y * scale), (int)(w * scale), (int)(h * scale));
        if (rect.X < 0 || rect.Y < 0 || rect.Width <= 0 || rect.Height <= 0 ||
            rect.X + rect.Width > src.PixelWidth || rect.Y + rect.Height > src.PixelHeight) return null;
        var crop = new CroppedBitmap(src, rect);
        crop.Freeze();
        return crop;
    }
}

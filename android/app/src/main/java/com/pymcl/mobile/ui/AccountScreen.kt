package com.pymcl.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.AccountKind
import com.pymcl.mobile.data.AuthAccount
import com.pymcl.mobile.data.AuthLogic
import com.pymcl.mobile.data.AuthRepo
import com.pymcl.mobile.data.DeviceCode
import com.pymcl.mobile.data.SkinRepo
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.LocalPclColors
import com.pymcl.mobile.theme.PclDanger
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private val KIND_TINT = mapOf(
    AccountKind.MICROSOFT to Color(0xFF2E9B6B),
    AccountKind.NIDE8 to Color(0xFFE8862E),
    AccountKind.AUTHLIB to Color(0xFF7C5CD6),
    AccountKind.OFFLINE to Color(0xFF4C8BF5),
)

/**
 * 账号页。对齐 `app/pages/account_page.py`：
 * 微软设备码、离线、皮肤站（authlib-injector）、统一通行证（Nide8），
 * 多账号列表 + 切换 + 删除，离线账号可绑本地皮肤。
 *
 * 不接 `AppViewModel`：这一页的状态只有它自己用，挂到全局 VM 上反而让
 * 每次账号刷新都触发别的页面重组。
 *
 * @param onPickSkinPng 交给宿主去开系统选择器，回调把 PNG 字节递回来。
 */
@Composable
fun AccountScreen(
    modifier: Modifier = Modifier,
    onPickSkinPng: ((ByteArray) -> Unit) -> Unit = {},
    onOpenUri: (String) -> Unit = {},
) {
    val c = LocalPclColors.current
    val scope = rememberCoroutineScope()
    val notice = rememberNotice()

    var rows by remember { mutableStateOf<List<AuthAccount>>(emptyList()) }
    var busy by remember { mutableStateOf(false) }
    var device by remember { mutableStateOf<DeviceCode?>(null) }

    var offlineName by rememberSaveable { mutableStateOf("") }
    var presetName by rememberSaveable { mutableStateOf(AuthLogic.presets.first().name) }
    var api by rememberSaveable { mutableStateOf("") }
    var user by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var nide8Id by rememberSaveable { mutableStateOf("") }
    var nide8User by rememberSaveable { mutableStateOf("") }
    var nide8Pw by rememberSaveable { mutableStateOf("") }
    var skinTarget by remember { mutableStateOf("") }

    // 账号表读的是文件，不能放在组合里同步做
    LaunchedEffect(Unit) {
        rows = withContext(Dispatchers.IO) { AuthRepo.accounts() }
    }

    fun reload() {
        scope.launch {
            rows = withContext(Dispatchers.IO) {
                AuthRepo.reload()
                AuthRepo.accounts()
            }
        }
    }

    fun run(label: String, block: suspend () -> String) {
        if (busy) return
        scope.launch {
            busy = true
            notice.clear()
            try {
                val message = withContext(Dispatchers.IO) { block() }
                notice.ok(message)
                reload()
            } catch (e: Exception) {
                notice.fail(t("{0} 失败：{1}").fmt(label, e.message))
            } finally {
                busy = false
            }
        }
    }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item(key = "head") {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(t("账号"), fontWeight = FontWeight.Bold, fontSize = 20.sp, color = c.text)
                Text(
                    t("微软正版、离线、Little Skin、统一通行证 / 自建 Yggdrasil"),
                    color = c.muted,
                    fontSize = 12.sp,
                )
                PclNotice(notice.text, notice.isError)
            }
        }

        item(key = "saved") {
            PclCard {
                PclSectionTitle(t("已保存账号"), t("点「使用」切换当前账号"))
                if (rows.isEmpty()) PclEmpty(t("还没有任何账号，先在下面加一个"))
            }
        }

        // 账号行单独成 item 并给稳定 key：切换 / 删除只重组动过的那一行
        items(rows, key = { it.type + "/" + it.name }) { account ->
            AccountRow(
                account = account,
                onUse = { run(t("切换账号")) { AuthRepo.activate(account.name); t("已切到 {0}").fmt(account.name) } },
                onDelete = { run(t("删除账号")) { AuthRepo.remove(account.name); t("已删除 {0}").fmt(account.name) } },
                onSkin = { skinTarget = account.name },
            )
        }

        if (skinTarget.isNotBlank()) {
            item(key = "skin-editor") {
                val target = rows.firstOrNull { it.name == skinTarget }
                SkinEditor(
                    account = target,
                    onPick = {
                        onPickSkinPng { bytes ->
                            run(t("保存皮肤")) {
                                val file = SkinRepo.save(skinTarget, bytes)
                                AuthRepo.setSkin(skinTarget, file, SkinRepo.modelOf(target))
                                t("皮肤已更新，下次启动生效")
                            }
                        }
                    },
                    onModel = { model ->
                        run(t("切换手臂模型")) {
                            AuthRepo.setSkin(skinTarget, target?.skinFile.orEmpty(), model)
                            t("手臂模型已改为 {0}").fmt(model)
                        }
                    },
                    onClear = {
                        run(t("清除皮肤")) {
                            SkinRepo.remove(target)
                            AuthRepo.clearSkin(skinTarget)
                            t("已回到游戏默认皮肤")
                        }
                    },
                    onClose = { skinTarget = "" },
                )
            }
        }

        item(key = "microsoft") {
            PclCard {
                PclSectionTitle(t("微软账号"), t("设备码登录：在另一台设备上打开链接输入码"))
                device?.let {
                    Text(
                        t("打开 {0} 输入 {1}").fmt(it.uri, it.userCode),
                        color = c.accent,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 14.sp,
                    )
                    PclLink(t("打开链接")) { onOpenUri(it.uri) }
                }
                PclButton(t("设备码登录"), enabled = !busy && device == null) {
                    scope.launch {
                        busy = true
                        notice.clear()
                        try {
                            val code = withContext(Dispatchers.IO) { AuthRepo.startDeviceCode() }
                            device = code
                            notice.ok(t("在浏览器里输入 {0} 后回到这里等一会").fmt(code.userCode))
                            val account = pollMicrosoft(code)
                            device = null
                            if (account == null) {
                                notice.fail(t("设备码过期了，重新点一次"))
                            } else {
                                notice.ok(t("已登录 {0}").fmt(account.name))
                                reload()
                            }
                        } catch (e: Exception) {
                            device = null
                            notice.fail(t("微软登录失败：{0}").fmt(e.message))
                        } finally {
                            busy = false
                        }
                    }
                }
            }
        }

        item(key = "authlib") {
            PclCard {
                PclSectionTitle(t("皮肤站（authlib-injector）"), t("选一个预设，或自己填 Yggdrasil API"))
                PclOptionRow(
                    label = "",
                    options = AuthLogic.presets.map { it.name to it.name },
                    selected = presetName,
                ) { picked ->
                    presetName = picked
                    AuthLogic.presetApi(picked).takeIf { it.isNotBlank() }?.let { api = it }
                }
                PclTextRow("Yggdrasil API", api, t("到 /api/yggdrasil 为止")) { api = it }
                PclTextRow(t("邮箱 / 用户名"), user) { user = it }
                PclTextRow(t("密码"), password, secret = true) { password = it }
                PclButton(if (busy) t("登录中…") else t("登录皮肤站"), enabled = !busy && api.isNotBlank()) {
                    run(t("皮肤站登录")) {
                        val account = AuthRepo.loginAuthlib(api, user, password)
                        t("已登录 {0}").fmt(account.name)
                    }
                }
            }
        }

        item(key = "nide8") {
            PclCard {
                PclSectionTitle(t("统一通行证（Nide8）"), t("填 32 位服务器 ID，或把含该 ID 的链接贴进来"))
                PclTextRow(t("服务器 ID / 链接"), nide8Id) { nide8Id = it }
                if (nide8Id.isNotBlank()) {
                    val parsed = AuthLogic.parseNide8Id(nide8Id)
                    Text(
                        if (parsed == null) t("这里面没找到 32 位服务器 ID") else t("认出 ID：{0}").fmt(parsed),
                        color = if (parsed == null) PclDanger else c.accent,
                        fontSize = 11.sp,
                    )
                }
                PclTextRow(t("用户名"), nide8User) { nide8User = it }
                PclTextRow(t("密码"), nide8Pw, secret = true) { nide8Pw = it }
                PclButton(if (busy) t("登录中…") else t("登录通行证"), enabled = !busy && nide8Id.isNotBlank()) {
                    run(t("通行证登录")) {
                        val account = AuthRepo.loginNide8(nide8Id, nide8User, nide8Pw)
                        t("已登录 {0}").fmt(account.name)
                    }
                }
            }
        }

        item(key = "offline") {
            PclCard {
                PclSectionTitle(t("离线"), t("只能进离线服；名字限 16 位字母数字下划线"))
                PclTextRow(t("离线角色名"), offlineName) { offlineName = it }
                val valid = AuthLogic.validOfflineName(offlineName.trim())
                if (offlineName.isNotBlank() && !valid) {
                    Text(t("这个名字游戏不认"), color = PclDanger, fontSize = 11.sp)
                }
                PclButton(t("保存离线账号"), enabled = !busy && valid) {
                    run(t("保存离线账号")) {
                        val account = AuthRepo.addOffline(offlineName.trim())
                        offlineName = ""
                        t("已添加 {0}").fmt(account.name)
                    }
                }
            }
        }
    }
}

@Composable
private fun AccountRow(
    account: AuthAccount,
    onUse: () -> Unit,
    onDelete: () -> Unit,
    onSkin: () -> Unit,
) {
    val c = LocalPclColors.current
    val tint = KIND_TINT[account.type] ?: c.accent
    PclCard {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            // 桌面账号页那张 36px 头像：有缓存就显示，拿不到退回字母色块
            ThumbnailTile(account.name, SkinRepo.avatarUrl(account), tint)
            Column(Modifier.weight(1f)) {
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(
                        account.name,
                        fontWeight = FontWeight.SemiBold,
                        color = c.text,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    PclPill(AccountKind.label(account.type), tint)
                    if (account.active) PclPill(t("当前"), Color(0xFF4C8BF5))
                    if (account.skinFile.isNotBlank()) PclPill(t("自定义皮肤"), c.accent)
                }
                if (account.api.isNotBlank()) {
                    Text(account.api, color = c.muted, fontSize = 10.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            if (account.type == AccountKind.OFFLINE) PclLink(t("皮肤"), onClick = onSkin)
            PclLink(t("使用"), enabled = !account.active, onClick = onUse)
            PclLink(t("删除"), onClick = onDelete)
        }
    }
}

@Composable
private fun SkinEditor(
    account: AuthAccount?,
    onPick: () -> Unit,
    onModel: (String) -> Unit,
    onClear: () -> Unit,
    onClose: () -> Unit,
) {
    val c = LocalPclColors.current
    PclCard {
        PclSectionTitle(
            t("「{0}」的皮肤").fmt(account?.name.orEmpty()),
            t("64x64 或 64x32 的 PNG。只对离线账号有效，进游戏后由本地皮肤服务发给游戏，不需要联网。"),
        )
        Text(
            account?.skinFile?.takeIf { it.isNotBlank() } ?: t("游戏默认皮肤"),
            color = c.muted,
            fontSize = 12.sp,
        )
        PclOptionRow(
            label = t("手臂模型"),
            options = listOf(SkinRepo.CLASSIC to t("宽臂（Steve）"), SkinRepo.SLIM to t("细臂（Alex）")),
            selected = SkinRepo.modelOf(account),
            onPick = onModel,
        )
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            PclButton(t("选择 PNG"), onClick = onPick)
            PclLink(t("清除，用游戏默认"), enabled = !account?.skinFile.isNullOrBlank(), onClick = onClear)
            PclLink(t("收起"), onClick = onClose)
        }
    }
}

/** 设备码轮询。间隔由服务端给，别自己缩短——会被限流。 */
private suspend fun pollMicrosoft(code: DeviceCode): AuthAccount? = withContext(Dispatchers.IO) {
    val interval = code.interval.coerceAtLeast(5)
    val rounds = (code.expiresIn / interval).coerceAtLeast(1)
    repeat(rounds) {
        delay(interval * 1000L)
        val token = runCatching { AuthRepo.pollOnce(code.deviceCode) }.getOrNull()
        if (token != null) {
            val account = AuthRepo.exchangeMinecraft(token.optString("access_token"))
            AuthRepo.saveMicrosoft(account, token.optString("refresh_token"))
            return@withContext account
        }
    }
    null
}

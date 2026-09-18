package com.pymcl.mobile.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.CrashReport
import com.pymcl.mobile.data.CrashReporter
import com.pymcl.mobile.data.FeedbackRepo
import com.pymcl.mobile.data.FeedbackRow
import com.pymcl.mobile.data.HelpContent
import com.pymcl.mobile.data.SysInfo
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.LocalPclColors
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 反馈页。对齐 `app/pages/feedback_page.py`：
 * 分类 + 联系方式 + 标题 + 正文 + 「附带本机配置」开关 + 配置预览 + 最近提交。
 *
 * 同意上传那一步是硬闸：没勾就不发，跟桌面一致。
 */
@Composable
fun FeedbackScreen(
    modifier: Modifier = Modifier,
    prefill: CrashReport? = null,
) {
    val c = LocalPclColors.current
    val scope = rememberCoroutineScope()
    val notice = rememberNotice()

    var category by rememberSaveable { mutableStateOf(prefill?.let { "crash" } ?: "bug") }
    var contact by rememberSaveable { mutableStateOf("") }
    var title by rememberSaveable { mutableStateOf(prefill?.headline.orEmpty()) }
    var body by rememberSaveable { mutableStateOf(prefill?.summary.orEmpty()) }
    var attach by rememberSaveable { mutableStateOf(true) }
    var consent by remember { mutableStateOf(FeedbackRepo.hasConsent()) }
    var sending by remember { mutableStateOf(false) }
    var spec by remember { mutableStateOf(t("正在采集本机配置…")) }
    var history by remember { mutableStateOf<List<FeedbackRow>>(emptyList()) }

    suspend fun refresh(force: Boolean) {
        spec = withContext(Dispatchers.IO) { SysInfo.describe(SysInfo.collect(force)) }
        history = withContext(Dispatchers.IO) { FeedbackRepo.history() }
    }

    LaunchedEffect(Unit) { refresh(false) }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item(key = "head") {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(t("反馈"), fontWeight = FontWeight.Bold, fontSize = 20.sp, color = c.text)
                Text(
                    t("发给开发者。需要先同意上传才会发送；可附带本机配置。"),
                    color = c.muted,
                    fontSize = 12.sp,
                )
                PclNotice(notice.text, notice.isError)
            }
        }

        item(key = "consent") {
            PclCard {
                PclSwitchRow(
                    t("同意上传反馈内容"),
                    consent,
                    t("不同意就一条都不发。附带的内容在下面「本机配置预览」里能逐行看到。"),
                ) {
                    consent = it
                    FeedbackRepo.setConsent(it)
                }
            }
        }

        item(key = "form") {
            PclCard {
                PclOptionRow(t("分类"), FeedbackRepo.CATEGORIES, category) { category = it }
                PclTextRow(t("联系方式（QQ / 邮箱，可选）"), contact) { contact = it }
                PclTextRow(t("标题，例如：1.20.1 Fabric 启动黑屏"), title) { title = it }
                OutlinedTextField(
                    value = body,
                    onValueChange = { body = it },
                    label = { Text(t("发生了什么、怎么复现、期望结果")) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 140.dp),
                    colors = pclFieldColors(),
                )
                PclSwitchRow(t("附带本机配置"), attach, t("系统、设备、已装 Java、下载源这些")) { attach = it }
                PclButton(
                    if (sending) t("发送中…") else t("发送反馈"),
                    enabled = !sending && consent && (title.isNotBlank() || body.isNotBlank()),
                ) {
                    scope.launch {
                        sending = true
                        notice.clear()
                        try {
                            val id = withContext(Dispatchers.IO) {
                                FeedbackRepo.submit(
                                    category = category,
                                    title = title,
                                    body = body,
                                    contact = contact,
                                    includeSysinfo = attach,
                                    crash = null,
                                )
                            }
                            title = ""
                            body = ""
                            notice.ok(t("已发送，开发者会实时看到 {0}").fmt(id))
                            refresh(false)
                        } catch (e: Exception) {
                            notice.fail(t("发送失败：{0}").fmt(e.message))
                        } finally {
                            sending = false
                        }
                    }
                }
            }
        }

        if (prefill != null) {
            item(key = "crash") {
                PclCard {
                    PclSectionTitle(t("这次崩溃"), prefill.summary)
                    // 先给人话：用户最需要的是「为什么崩、怎么办」，不是一坨堆栈。
                    // 堆栈折在下面，愿意看的往下滑。
                    if (prefill.advices.isEmpty()) {
                        Text(
                            prefill.help.ifBlank { t("日志里没匹配到已知原因。") },
                            color = c.muted,
                            fontSize = 13.sp,
                        )
                    } else {
                        prefill.advices.forEachIndexed { i, a ->
                            Text(
                                if (i == 0) a.headline else t("此外，{0}").fmt(a.headline),
                                color = c.text,
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 14.sp,
                            )
                            if (a.detail.isNotBlank()) {
                                Text(a.detail, color = c.muted, fontSize = 12.sp)
                            }
                            PclGap(4)
                        }
                        if (prefill.needHelp) {
                            Text(t("按上面试过还不行，就把这条反馈发出来。"), color = c.accent, fontSize = 12.sp)
                        }
                    }
                    PclGap()
                    Text(t("日志片段"), color = c.muted, fontSize = 11.sp)
                    Text(
                        prefill.excerpt.takeLast(1200),
                        fontFamily = FontFamily.Monospace,
                        fontSize = 10.sp,
                        color = c.muted,
                        maxLines = 14,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        PclButton(t("一键上报这次崩溃"), enabled = !sending && consent) {
                            scope.launch {
                                sending = true
                                try {
                                    val id = withContext(Dispatchers.IO) {
                                        FeedbackRepo.submitCrash(prefill, body)
                                    }
                                    notice.ok(t("崩溃已上报 {0}").fmt(id))
                                    refresh(false)
                                } catch (e: Exception) {
                                    notice.fail(t("上报失败：{0}").fmt(e.message))
                                } finally {
                                    sending = false
                                }
                            }
                        }
                        PclLink(t("导出到文件")) {
                            scope.launch {
                                val file = withContext(Dispatchers.IO) { CrashReporter.export(prefill) }
                                notice.ok(t("已导出 {0}").fmt(file.name))
                            }
                        }
                    }
                }
            }
        }

        item(key = "faq") { FaqCard() }

        item(key = "spec") {
            PclCard {
                Row(Modifier.fillMaxWidth()) {
                    Column(Modifier.weight(1f)) { PclSectionTitle(t("本机配置预览")) }
                    PclLink(t("重新采集")) { scope.launch { refresh(true) } }
                }
                Text(
                    spec,
                    fontFamily = FontFamily.Monospace,
                    fontSize = 11.sp,
                    color = c.text,
                )
            }
        }

        item(key = "hist-title") { PclSectionTitle(t("最近提交")) }

        if (history.isEmpty()) {
            item(key = "hist-empty") { PclEmpty(t("暂无")) }
        }

        items(history, key = { it.id }) { row ->
            PclKeyValue(FeedbackRepo.categoryLabel(row.category), "${row.title}  (${row.id})")
        }
    }
}

/**
 * 常见问题卡。对齐 `feedback_page._fill_help` / `_show_help`（`help_articles` / `help_article`）：
 * 桌面是一排标题按钮、点开弹 MessageBox；手机上改成点标题原地展开，同一时刻只展开一篇。
 * 搜索走 `HelpContent.search` 同一口径（标题 + 正文原文的不分大小写子串）；英文界面下
 * 用户敲的是英文，所以再拿译文兜一遍——只多不少，不会把桌面能搜到的漏掉。
 */
@Composable
private fun FaqCard() {
    val c = LocalPclColors.current
    var query by rememberSaveable { mutableStateOf("") }
    var openId by rememberSaveable { mutableStateOf("") }
    val q = query.trim().lowercase()
    val rows = HelpContent.ARTICLES.filter { a ->
        HelpContent.matches(a, q) || (t(a.title) + "\n" + t(a.body)).lowercase().contains(q)
    }

    PclCard {
        PclSectionTitle(t("常见问题"), t("启动、Java、模组、账号、联机的快速说明（点击标题展开）"))
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            label = { Text(t("搜索常见问题")) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            colors = pclFieldColors(),
        )
        if (rows.isEmpty()) {
            PclEmpty(t("没有匹配的常见问题"))
        }
        rows.forEach { a ->
            val open = openId == a.id
            Column(
                Modifier
                    .fillMaxWidth()
                    .clickable { openId = if (open) "" else a.id }
                    .padding(vertical = 6.dp),
            ) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        t(a.title),
                        color = if (open) c.accent else c.text,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 14.sp,
                        modifier = Modifier.weight(1f),
                    )
                    Text(if (open) "▴" else "▾", color = c.muted, fontSize = 12.sp)
                }
                if (open) {
                    PclGap(4)
                    Text(t(a.body), color = c.text, fontSize = 13.sp)
                }
            }
        }
    }
}

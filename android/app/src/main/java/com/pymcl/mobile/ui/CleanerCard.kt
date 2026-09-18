package com.pymcl.mobile.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.pymcl.mobile.data.CleanPlan
import com.pymcl.mobile.data.Cleaner
import com.pymcl.mobile.data.Saves
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 设置页里的清理 / 维护工具，对齐桌面 `settings_page._clean`。
 *
 * 严格两步：先「扫描」列出每一类要删什么、多大，勾掉不想删的，再点「清理」才真删。
 * 两步都在 IO 线程上跑——一个库多的实例要遍历上万个文件，放主线程就是几秒白屏。
 */
@Composable
fun CleanerCard(modifier: Modifier = Modifier) {
    val scope = rememberCoroutineScope()
    val notice = rememberNotice()
    var plan by remember { mutableStateOf<CleanPlan?>(null) }
    var kinds by remember { mutableStateOf(Cleaner.ALL_KINDS.toSet()) }
    var scanning by remember { mutableStateOf(false) }
    var cleaning by remember { mutableStateOf(false) }
    val busy = scanning || cleaning

    PclCard(modifier) {
        PclSectionTitle(t("清理 / 维护"), t("先扫一遍列出要删的东西，确认了才真删"))

        val scanned = plan
        if (scanned == null) {
            PclEmpty(t("还没扫描——点下面的「扫描」看看能腾出多少"))
        } else {
            Cleaner.ALL_KINDS.forEach { kind ->
                val rows = scanned.of(kind)
                PclSwitchRow(
                    label = kindLabel(kind),
                    checked = kind in kinds,
                    hint = t("{0} 个 · {1}").fmt(rows.size, Saves.formatSize(rows.sumOf { it.bytes })),
                ) { on ->
                    kinds = if (on) kinds + kind else kinds - kind
                }
            }
            PclKeyValue(t("本次将删除"), t("{0} 个 · {1}").fmt(scanned.entries(kinds).size, Saves.formatSize(scanned.bytesOf(kinds))))
        }

        PclNotice(notice.text, notice.isError)

        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PclButton(if (scanning) t("扫描中…") else t("扫描"), enabled = !busy) {
                scope.launch {
                    scanning = true
                    notice.clear()
                    try {
                        val out = withContext(Dispatchers.IO) { Cleaner.preview() }
                        plan = out
                        kinds = Cleaner.ALL_KINDS.toSet()
                        notice.ok(t("扫到 {0} 个文件，约 {1}").fmt(out.count, Saves.formatSize(out.bytes)))
                    } catch (e: Exception) {
                        plan = null
                        notice.fail(t("扫描失败：{0}").fmt(e.message))
                    } finally {
                        scanning = false
                    }
                }
            }
            val pending = scanned?.entries(kinds).orEmpty()
            PclButton(if (cleaning) t("清理中…") else t("清理"), enabled = !busy && pending.isNotEmpty()) {
                val target = scanned ?: return@PclButton
                val picked = kinds
                scope.launch {
                    cleaning = true
                    notice.clear()
                    try {
                        val result = withContext(Dispatchers.IO) { Cleaner.apply(target, picked) }
                        // 删完那份清单就过期了：留着会让人以为还能再删一次
                        plan = null
                        notice.ok(t("已删除 {0} 个文件，腾出 {1}").fmt(result.removed, Saves.formatSize(result.bytes)))
                    } catch (e: Exception) {
                        notice.fail(t("清理失败：{0}").fmt(e.message))
                    } finally {
                        cleaning = false
                    }
                }
            }
        }
    }
}

private fun kindLabel(kind: String): String = when (kind) {
    Cleaner.KIND_UNUSED -> t("未被任何版本引用的依赖库")
    Cleaner.KIND_PARTS -> t("下载断在半路的 .part")
    Cleaner.KIND_CACHE -> t("更新缓存")
    else -> kind
}

package com.pymcl.mobile.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.CatalogKinds
import com.pymcl.mobile.data.CatalogSpec
import com.pymcl.mobile.data.ContentEntry
import com.pymcl.mobile.data.ContentLibrary
import com.pymcl.mobile.data.Saves
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.vm.AppViewModel

/**
 * 「已装的内容」一页吃六类：模组 / 整合包 / 资源包 / 光影包 / 数据包 / 世界。
 *
 * 差异全在 [CatalogSpec] 那张表上，页面本身不认类型——照桌面
 * `app/pages/catalog_page.py` 的做法（一份代码 + 六个 spec）。复制六份页面的话，
 * 以后加一列要改六处，总会漏一处。
 */
@Composable
fun ContentLibraryScreen(vm: AppViewModel, modifier: Modifier = Modifier) {
    var deleting by remember { mutableStateOf<Pair<ContentEntry, AppViewModel.LibraryTarget>?>(null) }
    var exporting by remember { mutableStateOf<Pair<ContentEntry, AppViewModel.LibraryTarget>?>(null) }
    val exportFile = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        val request = exporting
        exporting = null
        if (uri != null && request != null) vm.exportFromLibrary(uri, request.first.name, request.second)
    }
    val spec = vm.librarySpec
    var importTarget by remember { mutableStateOf<AppViewModel.LibraryTarget?>(null) }
    val importFile = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        val target = importTarget
        importTarget = null
        if (uri != null && target != null) vm.importIntoLibrary(uri, target)
    }
    // 多选导出：一次写一个 zip，所以走 CreateDocument 而不是目录树授权
    var picking by remember { mutableStateOf(false) }
    val selected = remember { mutableStateListOf<String>() }
    var batch by remember { mutableStateOf<Pair<List<String>, AppViewModel.LibraryTarget>?>(null) }
    val exportBundle = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri ->
        val request = batch
        batch = null
        if (uri != null && request != null) {
            vm.exportManyFromLibrary(uri, request.first, request.second)
            selected.clear()
            picking = false
        }
    }

    LaunchedEffect(vm.instance, vm.libraryTab, vm.modTarget) {
        vm.reloadLibrary()
        // 换了类型或安装目标，勾中的名字就指不到东西了
        selected.clear()
        picking = false
    }

    // 过滤在内存里做：用户每敲一个字都回盘列一次目录会明显掉帧
    val rows = remember(vm.libraryQuery, vm.library.size, vm.library.toList()) { vm.filteredLibrary() }

    Column(modifier.fillMaxSize()) {
        SectionHeader(
            t("内容管理"),
            vm.librarySummary(),
            action = {
                if (spec.kind != com.pymcl.mobile.data.FileKind.MODPACK) {
                    TextButton(onClick = {
                        picking = !picking
                        selected.clear()
                    }) { Text(if (picking) t("退出多选") else t("多选"), color = PclGreen) }
                }
            },
        )
        ChipRow(t("类型"), CatalogKinds.ALL.map { it.title }, spec.title) { title ->
            CatalogKinds.ALL.firstOrNull { it.title == title }?.let { vm.selectLibraryKind(it) }
        }
        if (spec.supportsToggle) {
            ChipRow(
                t("安装目标"),
                vm.modTargets.map { it.label },
                vm.modTargets.firstOrNull { it.value == vm.modTarget }?.label.orEmpty(),
            ) { label ->
                vm.selectModTarget(vm.modTargets.firstOrNull { it.label == label }?.value.orEmpty())
            }
        }
        Text(t("落在 {0}").fmt(vm.libraryTarget().let { it.spec.dirIn(it.dir, it.version) }.absolutePath), color = PclMuted, fontSize = 10.sp)
        Spacer(Modifier.height(6.dp))
        SearchRow(
            value = vm.libraryQuery,
            label = t("按名称筛选"),
            actionText = spec.localLabel,
            onValueChange = { vm.libraryQuery = it },
            // 走 Storage Access Framework，而不是让人手填 /sdcard 路径。Android 10+ 的
            // scoped storage 下，路径字符串往往根本不可读；content:// URI 才是正确入口。
            // 扩展名由数据层按当前内容类型再次校验，选择器这里只做宽松筛选。
            onAction = {
                importTarget = vm.libraryTarget()
                importFile.launch(arrayOf("*/*"))
            },
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = {
                vm.downloadTab = spec.tab
                vm.tab = 3
            }) { Text(spec.searchTitle, color = PclGreen) }
            Text(t("源：{0}").fmt(spec.sources.joinToString(" / ")), color = PclMuted, fontSize = 11.sp)
        }
        ErrorLine(vm)
        if (picking) {
            val allPicked = rows.isNotEmpty() && selected.size == rows.size
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    t("已选 {0} 项").fmt(selected.size),
                    color = PclMuted,
                    fontSize = 12.sp,
                    modifier = Modifier.weight(1f),
                )
                TextButton(onClick = {
                    selected.clear()
                    if (!allPicked) selected.addAll(rows.map { it.name })
                }) { Text(if (allPicked) t("清空") else t("全选"), color = PclGreen) }
                TextButton(
                    enabled = selected.isNotEmpty(),
                    onClick = {
                        batch = selected.toList() to vm.libraryTarget()
                        exportBundle.launch(com.pymcl.mobile.data.ContentExport.bundleName(spec, selected.size))
                    },
                ) { Text(t("批量导出"), color = if (selected.isEmpty()) PclMuted else PclGreen) }
            }
        }
        Spacer(Modifier.height(4.dp))

        if (rows.isEmpty()) {
            EmptyHint(
                if (vm.library.isEmpty()) spec.emptyInstalled else t("没有匹配的{0}").fmt(spec.title),
                Modifier.weight(1f),
            )
            return@Column
        }

        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            items(rows, key = { it.path }) { row ->
                CardBox {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        if (picking) {
                            Checkbox(
                                checked = row.name in selected,
                                onCheckedChange = { on ->
                                    if (on) selected.add(row.name) else selected.remove(row.name)
                                },
                                colors = CheckboxDefaults.colors(checkedColor = PclGreen),
                            )
                        }
                        Column(Modifier.weight(1f)) {
                            Text(
                                row.name,
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 13.sp,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                Saves.formatSize(row.bytes) +
                                    (if (row.isDir) t(" · 目录") else "") +
                                    (if (spec.supportsToggle && !row.enabled) t(" · 已禁用") else ""),
                                color = PclMuted,
                                fontSize = 11.sp,
                            )
                        }
                        if (spec.supportsToggle) {
                            Switch(
                                checked = row.enabled,
                                onCheckedChange = { vm.setModEnabled(row.name, it) },
                                colors = SwitchDefaults.colors(checkedTrackColor = PclGreen),
                            )
                        }
                        // 多选时这一行已经被勾选框和名字占满，单项按钮收起来
                        if (!picking && spec.kind != com.pymcl.mobile.data.FileKind.MODPACK) {
                            TextButton(onClick = {
                                exporting = row to vm.libraryTarget()
                                exportFile.launch(com.pymcl.mobile.data.ContentExport.filename(row.name, spec))
                            }) { Text(t("导出"), color = PclGreen) }
                        }
                        if (!picking) {
                            TextButton(onClick = { deleting = row to vm.libraryTarget() }) { Text(t("删除"), color = ErrorRed) }
                        }
                    }
                }
            }
        }
    }

    deleting?.let { (row, target) ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            title = { Text(t("删除确认")) },
            text = { Text(t("将删除{0}「{1}」，不可恢复。").fmt(target.spec.title, row.name)) },
            confirmButton = {
                TextButton(onClick = {
                    vm.deleteFromLibrary(row.name, target)
                    deleting = null
                }) { Text(t("删除"), color = ErrorRed) }
            },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text(t("取消")) } },
        )
    }
}

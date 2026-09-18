package com.pymcl.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.pymcl.mobile.data.CatalogFavorites
import com.pymcl.mobile.data.CatalogRepo
import com.pymcl.mobile.data.fmt
import com.pymcl.mobile.data.t
import com.pymcl.mobile.theme.PclGreen
import com.pymcl.mobile.theme.PclHover
import com.pymcl.mobile.theme.PclMuted
import com.pymcl.mobile.theme.PclText
import com.pymcl.mobile.vm.AppViewModel

/** 下载商店：分区与桌面 download_hub 一一对应，末位是任务中心。外壳 MainTab 按这个名字接线。 */
@Composable
fun DownloadHub(vm: AppViewModel, modifier: Modifier = Modifier) {
    Column(modifier.fillMaxSize()) {
        Row(
            Modifier
                .fillMaxWidth()
                .horizontalScroll(rememberScrollState())
                .padding(bottom = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            CatalogRepo.KINDS.forEach { kind ->
                val on = vm.downloadTab == kind
                val label = if (kind == CatalogRepo.KIND_TASKS && vm.activeDownloads > 0) {
                    t("{0}（{1}）").fmt(t(kind), vm.activeDownloads)
                } else {
                    t(kind)
                }
                Text(
                    label,
                    modifier = Modifier
                        .background(if (on) PclHover else Color.Transparent, RoundedCornerShape(8.dp))
                        .clickable { vm.downloadTab = kind }
                        .padding(horizontal = 10.dp, vertical = 6.dp),
                    color = if (on) PclGreen else PclText,
                    fontSize = 13.sp,
                    maxLines = 1,
                )
            }
        }
        BusyBar(vm)
        ErrorLine(vm)
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when (vm.downloadTab) {
                CatalogRepo.KIND_VANILLA -> VersionPane(vm)
                CatalogRepo.KIND_TASKS -> TasksScreen(vm)
                CatalogRepo.KIND_MODPACK -> ModpackScreen(vm)
                else -> CatalogPane(vm)
            }
        }
    }
}

@Composable
private fun VersionPane(vm: AppViewModel) {
    // 版本清单上千条，过滤只在过滤条件真的变了时跑一遍
    val rows = remember(vm.query, vm.onlyRelease, vm.versions.size) { vm.filteredVersions() }
    Column(Modifier.fillMaxSize()) {
        SearchRow(
            value = vm.query,
            label = t("过滤版本"),
            actionText = t("刷新"),
            actionEnabled = !vm.busy,
            onValueChange = { vm.query = it },
            onAction = { vm.reloadVersions(true) },
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(
                checked = vm.onlyRelease,
                onCheckedChange = { vm.onlyRelease = it },
                colors = SwitchDefaults.colors(checkedTrackColor = PclGreen),
            )
            Text(t("仅正式版"), fontSize = 13.sp)
            Spacer(Modifier.weight(1f))
            PrimaryBtn(t("安装"), enabled = !vm.busy && vm.versionId.isNotBlank()) { vm.installSelected() }
        }
        Text(
            t("目标实例 {0} · 选中 {1}").fmt(vm.instance, vm.versionId.ifBlank { t("无") }),
            color = PclMuted,
            fontSize = 12.sp,
        )
        if (rows.isEmpty()) {
            EmptyHint(t("清单还没拉下来，点右上角「刷新」"), Modifier.weight(1f))
            return@Column
        }
        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            contentPadding = PaddingValues(vertical = 8.dp),
        ) {
            items(rows, key = { it.id }) { row ->
                val on = row.id == vm.versionId
                Row(
                    Modifier
                        .fillMaxWidth()
                        .background(if (on) PclHover else Color.Transparent)
                        .clickable { vm.versionId = row.id }
                        .padding(vertical = 10.dp, horizontal = 4.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Column {
                        Text(row.id, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal)
                        Text(row.type, color = PclMuted, fontSize = 11.sp)
                    }
                    if (row.id in vm.installed) Text(t("已装"), color = PclGreen, fontSize = 12.sp)
                }
            }
        }
    }
}

@Composable
private fun CatalogPane(vm: AppViewModel) {
    LaunchedEffect(Unit) { vm.reloadFavorites() }
    Column(Modifier.fillMaxSize()) {
        SearchRow(
            value = vm.query,
            label = t("输入名称后点搜索"),
            actionText = t("搜索"),
            actionEnabled = !vm.busy,
            onValueChange = { vm.query = it },
            onAction = { vm.searchCatalog() },
        )
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(
                t("{0} · 不搜索就不联网。源：MCIM 镜像优先，官方垫底").fmt(t(vm.downloadTab)),
                color = PclMuted,
                fontSize = 12.sp,
                modifier = Modifier.weight(1f),
            )
            TextButton(onClick = { vm.showFavorites = !vm.showFavorites }) {
                Text(
                    if (vm.showFavorites) t("回到搜索结果") else t("{0}（{1}）").fmt(t("收藏"), vm.favorites.size),
                    color = PclGreen,
                    fontSize = 12.sp,
                )
            }
        }
        // 世界在 Modrinth 上没有对应的项目类型，只能问 CurseForge；装完是解到 saves/ 而不是落一个包
        if (vm.downloadTab == CatalogRepo.KIND_WORLD) {
            Text(t("世界只有 CurseForge 有，装完直接解进 saves/"), color = PclMuted, fontSize = 11.sp)
        }
        if (vm.showFavorites) {
            FavoritePane(vm)
            return@Column
        }
        if (vm.catalog.isEmpty()) {
            EmptyHint(t("还没有结果，输入关键字搜一下"), Modifier.weight(1f))
            return@Column
        }
        LazyColumn(
            modifier = Modifier.weight(1f).fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            contentPadding = PaddingValues(vertical = 8.dp),
        ) {
            items(vm.catalog, key = { it.source + it.slug + it.name }) { hit ->
                CardBox {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        // 桌面目录页的 52px 缩略图；没图或没下到就是字母色块
                        ThumbnailTile(hit.name, hit.iconUrl, PclGreen, size = 40)
                        Spacer(Modifier.width(8.dp))
                        Text(hit.name, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    Text(
                        hit.description,
                        color = PclMuted,
                        fontSize = 12.sp,
                        maxLines = 3,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            t("{0} · {1} 下载 · {2}").fmt(hit.source, hit.downloads, hit.author.ifBlank { t("未署名") }),
                            color = PclMuted,
                            fontSize = 11.sp,
                            modifier = Modifier.weight(1f),
                        )
                        val starred = vm.isFavorite(hit)
                        TextButton(onClick = { vm.toggleFavorite(hit) }) {
                            Text(
                                if (starred) t("已收藏") else t("收藏"),
                                color = if (starred) PclGreen else PclMuted,
                                fontSize = 12.sp,
                            )
                        }
                        PrimaryBtn(t("安装"), enabled = !vm.busy) { vm.installCatalogHit(hit) }
                    }
                    Text(
                        t("装进 {0}{1}").fmt(vm.instance, if (vm.versionId.isBlank()) "" else " · ${vm.versionId}"),
                        color = PclMuted,
                        fontSize = 10.sp,
                    )
                }
            }
        }
    }
}

/**
 * 收藏夹，对齐桌面商店页那个心形按钮后面的列表。
 *
 * 收藏只记「哪个源的哪个项目」，描述和下载量这些会过期的字段不存；装的时候按
 * **当前分区**走安装那条路，跟桌面一样——收藏是跨分区的一张表，装到哪儿由页面定。
 */
@Composable
private fun ColumnScope.FavoritePane(vm: AppViewModel) {
    if (vm.favorites.isEmpty()) {
        EmptyHint(t("还没有收藏。搜到中意的，点结果右边的「收藏」"), Modifier.weight(1f))
        return
    }
    LazyColumn(
        modifier = Modifier.weight(1f).fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        contentPadding = PaddingValues(vertical = 8.dp),
    ) {
        items(vm.favorites, key = { it.source + it.slug + it.id + it.name }) { fav ->
            CardBox {
                Text(fav.name.ifBlank { fav.slug.ifBlank { fav.id } }, fontWeight = FontWeight.SemiBold)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        fav.source.ifBlank { t("未知来源") },
                        color = PclMuted,
                        fontSize = 11.sp,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = { vm.toggleFavorite(CatalogFavorites.toHit(fav)) }) {
                        Text(t("取消收藏"), color = PclMuted, fontSize = 12.sp)
                    }
                    PrimaryBtn(t("安装"), enabled = !vm.busy) {
                        vm.installCatalogHit(CatalogFavorites.toHit(fav))
                    }
                }
                Text(
                    t("按当前分区「{0}」安装").fmt(t(vm.downloadTab)),
                    color = PclMuted,
                    fontSize = 10.sp,
                )
            }
        }
    }
}

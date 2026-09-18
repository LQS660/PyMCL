package com.pymcl.mobile.data

import com.tungsten.fclcore.download.fabric.FabricAPIInstallTask
import com.tungsten.fclcore.download.fabric.FabricInstallTask
import com.tungsten.fclcore.download.forge.ForgeNewInstallTask
import com.tungsten.fclcore.download.forge.ForgeOldInstallTask
import com.tungsten.fclcore.download.game.GameInstallTask
import com.tungsten.fclcore.download.liteloader.LiteLoaderInstallTask
import com.tungsten.fclcore.download.neoforge.NeoForgeInstallTask
import com.tungsten.fclcore.download.neoforge.NeoForgeOldInstallTask
import com.tungsten.fclcore.download.optifine.OptiFineInstallTask
import com.tungsten.fclcore.download.quilt.QuiltAPIInstallTask
import com.tungsten.fclcore.download.quilt.QuiltInstallTask

/**
 * `:FCLCore` 接进来之后我们能直接用的安装器清单。
 *
 * 写成 `Class<*>` 而不是字符串是有意的：**这份清单本身就是编译期证据**。
 * 哪天上游改了包名或删了某个任务类，这个文件当场编不过，而不是等到运行时
 * 用户点「安装 Forge」才崩。加载器安装的接线归 opus-5-5，这里只负责
 * 「这些类在我们工程里确实解析得到」这一件事。
 */
data class LoaderInstaller(
    val loader: String,
    val label: String,
    val taskClass: Class<*>,
    /** 这个安装器要不要额外跑一遍 JVM（processor），要的话得走安装器宿主。 */
    val needsJvmHost: Boolean,
)

object FclCoreCatalog {
    /**
     * Forge 1.13+ 的新版安装器会在本机跑一串 processor（jar 可执行），
     * 所以它是 [needsJvmHost] = true 的典型；Fabric / Quilt 只下文件、不跑 JVM。
     */
    val installers: List<LoaderInstaller> = listOf(
        LoaderInstaller("forge", "Forge（1.13+）", ForgeNewInstallTask::class.java, needsJvmHost = true),
        LoaderInstaller("forge-old", "Forge（1.12.2 及以下）", ForgeOldInstallTask::class.java, needsJvmHost = false),
        LoaderInstaller("neoforge", "NeoForge", NeoForgeInstallTask::class.java, needsJvmHost = true),
        // 1.20.1 以前 NeoForge 用的是 <mc>-<build> 号段，走这一档
        LoaderInstaller("neoforge-old", "NeoForge（1.20.1 以前）", NeoForgeOldInstallTask::class.java, needsJvmHost = true),
        LoaderInstaller("fabric", "Fabric", FabricInstallTask::class.java, needsJvmHost = false),
        LoaderInstaller("fabric-api", "Fabric API", FabricAPIInstallTask::class.java, needsJvmHost = false),
        LoaderInstaller("quilt", "Quilt", QuiltInstallTask::class.java, needsJvmHost = false),
        LoaderInstaller("quilt-api", "Quilt API", QuiltAPIInstallTask::class.java, needsJvmHost = false),
        LoaderInstaller("optifine", "OptiFine", OptiFineInstallTask::class.java, needsJvmHost = true),
        LoaderInstaller("liteloader", "LiteLoader", LiteLoaderInstallTask::class.java, needsJvmHost = false),
        // 原版本身不是加载器，列进来是为了能拿它跟自家 Installer.installVanilla 对照行为；
        // byLoader("vanilla") 取得到，但它不该出现在「装哪个加载器」那张选单上
        LoaderInstaller("vanilla", "原版（对照用）", GameInstallTask::class.java, needsJvmHost = false),
    )

    /** 真正的加载器，不含原版那一条。界面上列选项用这个。 */
    val loaderOnly: List<LoaderInstaller> get() = installers.filterNot { it.loader == "vanilla" }

    /**
     * 先按表里的键精确找，找不到再走归一化。
     *
     * 顺序不能反：`normalizeLoader("neoforge-old")` 会收敛成 `neoforge`，
     * 先归一化的话 `-old` 那两档永远取不到，而 1.20.1 以前的 NeoForge
     * 和 1.12.2 以下的 Forge 恰恰只能走它们。
     */
    fun byLoader(loader: String): LoaderInstaller? {
        val raw = loader.trim().lowercase()
        installers.firstOrNull { it.loader == raw }?.let { return it }
        val want = VersionPick.normalizeLoader(loader)
        return installers.firstOrNull { it.loader == want }
    }

    /** 需要安装器宿主跑一遍 JVM 的那几个，宿主没做好之前这些装不了。 */
    fun needingJvmHost(): List<LoaderInstaller> = installers.filter { it.needsJvmHost }

    /** 给人看的一行，交付里那份「多了哪些可用类」就是它列出来的。 */
    fun describe(): String = installers.joinToString("\n") {
        "${it.label.padEnd(22)} ${it.taskClass.name}${if (it.needsJvmHost) "  （要 JVM 宿主）" else ""}"
    }
}

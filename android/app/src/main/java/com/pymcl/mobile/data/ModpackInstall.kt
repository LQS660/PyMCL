package com.pymcl.mobile.data

import java.io.File
import java.util.zip.ZipFile

/**
 * 整合包安装编排，对齐桌面 mclauncher/modpack.py 的 install_mrpack / install_cf_zip。
 *
 * 分成两步，故意的：
 * - [plan]  纯函数，把清单变成「下哪些、解哪些、缺哪些、跳哪些」，不碰网络也不落盘；
 * - [execute] 才真的动手，而网络那一下走注入进来的 [PackDownloader]。
 *
 * 这么分是为了单测：编排逻辑（路径穿越、服务端专属文件、overrides 映射、取消、
 * 进度）全都能不联网地验，只有真正的下载那一步要替身。
 *
 * **不在这一层做的事**：装 Minecraft 本体与加载器（那是 [Installer] 与后续的加载器
 * 安装器）、把 CurseForge 的 projectID/fileID 换成下载地址（要打 CF API，见
 * [InstallPlan.unresolved]）、任何 UI。
 */

/** 一步下载：多个候选地址按顺序试，落到内容根下的 [relPath]。 */
data class DownloadStep(
    val relPath: String,
    val urls: List<String>,
    val sha1: String = "",
    val size: Long = 0,
)

/** overrides 里要解出来的一个 zip 条目。 */
data class ExtractStep(
    val entry: String,
    val relPath: String,
)

data class SkippedFile(val path: String, val reason: String)

data class InstallPlan(
    val info: ModpackInfo,
    val downloads: List<DownloadStep> = emptyList(),
    val extracts: List<ExtractStep> = emptyList(),
    /** CurseForge 的模组引用：地址还没解出来，要外面打 API 换完再回来。 */
    val unresolved: List<CursePackRef> = emptyList(),
    val skipped: List<SkippedFile> = emptyList(),
) {
    val totalSteps: Int get() = downloads.size + extracts.size
}

data class InstallReport(
    val downloaded: Int = 0,
    val extracted: Int = 0,
    val skipped: List<SkippedFile> = emptyList(),
    val failed: List<SkippedFile> = emptyList(),
)

/** 下载一个文件。真身见 [HttpPackDownloader]；单测塞自己的替身。 */
fun interface PackDownloader {
    fun fetch(urls: List<String>, dest: File, sha1: String?, onProgress: (Long, Long) -> Unit)
}

object ModpackInstall {

    /**
     * 把清单编排成可执行的步骤。[entryNames] 是整合包 zip 里的条目名（原样，不转小写），
     * 用来找 overrides；不给就当包里没有 overrides。
     */
    fun plan(info: ModpackInfo, entryNames: List<String> = emptyList()): InstallPlan {
        val downloads = ArrayList<DownloadStep>()
        val skipped = ArrayList<SkippedFile>()

        for (f in info.files) {
            if (!f.clientSupported) {
                skipped.add(SkippedFile(f.path, "服务端专属，客户端不需要"))
                continue
            }
            val rel = safeRelPath(f.path)
            if (rel == null) {
                // 路径穿越：`../../` 能把文件写到内容根外面去，整合包是别人给的，不能信。
                skipped.add(SkippedFile(f.path, "路径非法，拒绝写到内容根外面"))
                continue
            }
            if (f.urls.isEmpty()) {
                skipped.add(SkippedFile(f.path, "清单里没给下载地址"))
                continue
            }
            downloads.add(DownloadStep(rel, f.urls, f.sha1, f.size))
        }

        return InstallPlan(
            info = info,
            downloads = downloads,
            extracts = planExtracts(info, entryNames),
            unresolved = info.refs,
            skipped = skipped,
        )
    }

    /** overrides / client-overrides 下的每个文件条目 → 内容根下的相对路径。 */
    fun planExtracts(info: ModpackInfo, entryNames: List<String>): List<ExtractStep> {
        if (entryNames.isEmpty()) return emptyList()
        val normalized = entryNames.map { it.replace('\\', '/') }
        // 按 overridesDirs 的顺序找第一个真的存在的，跟桌面一样只取一个。
        val dir = info.overridesDirs.firstOrNull { d ->
            normalized.any { it.startsWith("$d/", ignoreCase = true) }
        } ?: return emptyList()

        val out = ArrayList<ExtractStep>()
        for (entry in normalized) {
            if (!entry.startsWith("$dir/", ignoreCase = true)) continue
            if (entry.endsWith("/")) continue // 目录条目本身不用解
            val rel = safeRelPath(entry.substring(dir.length + 1)) ?: continue
            out.add(ExtractStep(entry, rel))
        }
        return out
    }

    /**
     * 清一清整合包给的相对路径：`..`、绝对路径、盘符一律拒绝。
     * 合法就返回归一化后的正斜杠路径，非法返回 null。
     */
    fun safeRelPath(raw: String): String? {
        val s = raw.replace('\\', '/').trim()
        if (s.isEmpty()) return null
        if (s.startsWith("/")) return null
        if (s.length >= 2 && s[1] == ':') return null // C:/...
        val parts = s.split('/').filter { it.isNotEmpty() && it != "." }
        if (parts.isEmpty()) return null
        if (parts.any { it == ".." }) return null
        return parts.joinToString("/")
    }

    /**
     * 真动手。
     *
     * @param contentRoot 整合包内容落到哪个目录下（例如 `<实例>/` 或某个版本的隔离目录）
     * @param packZip     整合包本体，解 overrides 要用；plan 里没有 extracts 时可以不给
     * @param onProgress  (已完成步数, 总步数, 这一步在干什么)
     * @param cancelled   每一步之前问一次；返回 true 就抛 [InstallCancelled]
     * @param continueOnError 单个文件下失败要不要接着走。整合包动辄几百个文件，
     *   一个挂掉就整包回滚对用户不友好；默认接着走，失败清单在回执里。
     */
    fun execute(
        plan: InstallPlan,
        contentRoot: File,
        packZip: File? = null,
        downloader: PackDownloader,
        onProgress: (Int, Int, String) -> Unit = { _, _, _ -> },
        onLog: (String) -> Unit = {},
        cancelled: () -> Boolean = { false },
        continueOnError: Boolean = true,
    ): InstallReport {
        val total = plan.totalSteps
        var done = 0
        var downloaded = 0
        var extracted = 0
        val failed = ArrayList<SkippedFile>()

        contentRoot.mkdirs()
        val rootPath = contentRoot.canonicalFile

        for (step in plan.downloads) {
            tick(cancelled)
            val dest = resolveUnder(rootPath, step.relPath)
            if (dest == null) {
                failed.add(SkippedFile(step.relPath, "路径非法，拒绝写到内容根外面"))
                done++
                continue
            }
            onProgress(done, total, "下载 ${step.relPath}")
            try {
                downloader.fetch(step.urls, dest, step.sha1.ifBlank { null }) { _, _ -> }
                downloaded++
            } catch (e: InstallCancelled) {
                throw e
            } catch (e: Exception) {
                onLog("下载失败 ${step.relPath}: ${e.message}")
                failed.add(SkippedFile(step.relPath, e.message ?: "下载失败"))
                if (!continueOnError) throw e
            }
            done++
        }

        if (plan.extracts.isNotEmpty() && packZip != null) {
            ZipFile(packZip).use { zf ->
                for (step in plan.extracts) {
                    tick(cancelled)
                    val dest = resolveUnder(rootPath, step.relPath)
                    if (dest == null) {
                        failed.add(SkippedFile(step.relPath, "路径非法，拒绝写到内容根外面"))
                        done++
                        continue
                    }
                    onProgress(done, total, "解出 ${step.relPath}")
                    val entry = zf.getEntry(step.entry)
                    if (entry == null) {
                        failed.add(SkippedFile(step.relPath, "包里找不到 ${step.entry}"))
                        done++
                        continue
                    }
                    try {
                        dest.parentFile?.mkdirs()
                        zf.getInputStream(entry).use { input ->
                            dest.outputStream().use { out -> input.copyTo(out) }
                        }
                        extracted++
                    } catch (e: Exception) {
                        onLog("解压失败 ${step.relPath}: ${e.message}")
                        failed.add(SkippedFile(step.relPath, e.message ?: "解压失败"))
                        if (!continueOnError) throw e
                    }
                    done++
                }
            }
        } else if (plan.extracts.isNotEmpty()) {
            onLog("有 ${plan.extracts.size} 个 overrides 条目，但没给整合包本体，跳过")
        }

        onProgress(done, total, "完成")
        return InstallReport(downloaded, extracted, plan.skipped, failed)
    }

    /** 把 CurseForge 那些换好地址的引用并回计划里。 */
    fun withResolved(base: InstallPlan, resolved: List<PackFile>): InstallPlan {
        val extra = plan(base.info.copy(files = resolved, refs = emptyList()))
        return base.copy(
            downloads = base.downloads + extra.downloads,
            unresolved = emptyList(),
            skipped = base.skipped + extra.skipped,
        )
    }

    /**
     * 再拦一道：算出真实路径之后确认它还在内容根里面。
     * [safeRelPath] 已经挡过 `..`，这一道挡的是符号链接之类走到外面去的情况。
     */
    private fun resolveUnder(root: File, relPath: String): File? {
        val dest = File(root, relPath)
        val parent = dest.parentFile ?: return null
        parent.mkdirs()
        val canonical = runCatching { dest.canonicalFile }.getOrNull() ?: return null
        val prefix = root.path + File.separator
        return if (canonical.path.startsWith(prefix)) canonical else null
    }

    private fun tick(cancelled: () -> Boolean) {
        if (cancelled()) throw InstallCancelled()
    }
}

package com.pymcl.mobile.data

import java.io.File

/**
 * 离线账号自定义皮肤的文件校验，对齐桌面 mclauncher/skin.py。
 *
 * 两件事：
 * 1. **只收 64x64 与 64x32 的 PNG**。64x32 是 1.8 以前的老格式，之后一律 64x64；
 *    别的尺寸客户端认不出来，与其进游戏才发现不如现在就挡。
 * 2. **文件名一律锁死在 skins/ 目录内**。配置里塞个 `../../` 就能读到外面去，
 *    而这份配置是可以被导入/同步的。
 *
 * 全是 java.io + 纯计算，不碰 Android，所以能直接单测。PNG 尺寸复用
 * [FileKinds.pngSize]，不写第二份。
 */
data class SkinCheck(
    val ok: Boolean,
    val width: Int = 0,
    val height: Int = 0,
    val reason: String = "",
)

object SkinFile {
    const val CLASSIC = "classic"
    const val SLIM = "slim"

    /** 皮肤贴图只有这两种尺寸，跟 [FileKinds.SKIN_SIZES] 是同一套。 */
    val VALID_SIZES = FileKinds.SKIN_SIZES

    /** 一张 64x64 的 PNG 撑死几十 KB；再大的多半是用户选错了图。 */
    const val MAX_BYTES = 2 * 1024 * 1024L

    fun dirIn(root: File): File = File(root, "skins").also { it.mkdirs() }

    fun validate(file: File): SkinCheck {
        if (!file.isFile) return SkinCheck(false, reason = "皮肤文件不存在")
        val len = file.length()
        if (len <= 0L) return SkinCheck(false, reason = "皮肤文件是空的")
        if (len > MAX_BYTES) return SkinCheck(false, reason = "这张图太大了，皮肤贴图只有几十 KB")

        val size = FileKinds.pngSize(file)
            ?: return SkinCheck(false, reason = "读不出 PNG 头，这不是一张 PNG")
        if (size !in VALID_SIZES) {
            return SkinCheck(false, size.first, size.second, "皮肤贴图只能是 64x64 或 64x32，这张是 ${size.first}x${size.second}")
        }
        return SkinCheck(true, size.first, size.second)
    }

    /**
     * 把配置里存的皮肤文件名解析成 skins/ 目录下的真实路径。
     *
     * 只收**单层文件名**：带路径分隔符、`..`、绝对路径、盘符的一律返回 null。
     * 再用 canonical path 兜一道，挡符号链接指到外面去的情况。
     */
    fun resolveIn(skinsDir: File, name: String): File? {
        val raw = name.trim()
        if (raw.isEmpty()) return null
        if (raw.contains('/') || raw.contains('\\')) return null
        if (raw == "." || raw == "..") return null
        if (raw.length >= 2 && raw[1] == ':') return null

        val dir = runCatching { skinsDir.canonicalFile }.getOrNull() ?: return null
        val target = runCatching { File(dir, raw).canonicalFile }.getOrNull() ?: return null
        return if (target.path.startsWith(dir.path + File.separator)) target else null
    }

    /** 保存用的文件名：把用户给的名字压成安全的单层名。 */
    fun safeFileName(raw: String): String {
        val base = Names.sanitize(raw.substringAfterLast('/').substringAfterLast('\\'), fallback = "skin")
        return if (base.endsWith(".png", ignoreCase = true)) base else "$base.png"
    }

    fun modelOf(raw: String?): String = if (raw?.lowercase() == SLIM) SLIM else CLASSIC
}

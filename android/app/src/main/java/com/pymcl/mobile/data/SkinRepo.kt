package com.pymcl.mobile.data

import java.io.File

/**
 * 皮肤：校验、落盘、取用。对齐桌面 `mclauncher/skin.py`。
 *
 * 只对离线账号有效——正版和皮肤站的皮肤在各自网站上改，本地这张送不进去。
 */
object SkinRepo {
    const val CLASSIC = "classic"
    const val SLIM = "slim"

    const val STEVE_AVATAR = "https://mc-heads.net/avatar/Steve/128"
    private const val BODY_TEMPLATE = "https://mc-heads.net/body/%s/180"
    private const val AVATAR_TEMPLATE = "https://mc-heads.net/avatar/%s/128"

    /** Mojang 只认这两种画布尺寸，别的传上去游戏那边直接不画。 */
    val VALID_SIZES = setOf(64 to 64, 64 to 32)

    class SkinError(message: String) : IllegalArgumentException(message)

    fun avatarUrl(account: AuthAccount?): String {
        val name = account?.name.orEmpty()
        return if (name.isBlank()) STEVE_AVATAR else AVATAR_TEMPLATE.format(name)
    }

    fun bodyUrl(account: AuthAccount?): String {
        val name = account?.name.orEmpty().ifBlank { "Steve" }
        return BODY_TEMPLATE.format(name)
    }

    /**
     * 只读 PNG 头，不解码整张图。
     *
     * 8 字节签名 + IHDR 的宽高就在固定偏移上，为了知道尺寸去 decode 一张
     * 64x64 的位图纯属浪费——何况这条路是在挑文件时同步走的。
     */
    fun pngSize(data: ByteArray): Pair<Int, Int>? {
        if (data.size < 24) return null
        val signature = byteArrayOf(
            0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
        )
        for (i in signature.indices) {
            if (data[i] != signature[i]) return null
        }
        if (data[12] != 'I'.code.toByte() || data[13] != 'H'.code.toByte() ||
            data[14] != 'D'.code.toByte() || data[15] != 'R'.code.toByte()
        ) {
            return null
        }
        val width = readInt(data, 16)
        val height = readInt(data, 20)
        if (width <= 0 || height <= 0) return null
        return width to height
    }

    private fun readInt(data: ByteArray, at: Int): Int =
        ((data[at].toInt() and 0xFF) shl 24) or
            ((data[at + 1].toInt() and 0xFF) shl 16) or
            ((data[at + 2].toInt() and 0xFF) shl 8) or
            (data[at + 3].toInt() and 0xFF)

    fun validate(data: ByteArray): Pair<Int, Int> {
        val size = pngSize(data) ?: throw SkinError("这不是一张 PNG，或者文件坏了")
        if (size !in VALID_SIZES) {
            throw SkinError("皮肤要是 64x64 或 64x32，这张是 ${size.first}x${size.second}")
        }
        return size
    }

    /** 64x32 是 1.8 以前的老画布，双层皮肤和细臂都是 64x64 之后才有的。 */
    fun isLegacyCanvas(size: Pair<Int, Int>): Boolean = size == (64 to 32)

    fun fileNameFor(accountName: String): String =
        Paths.sanitizeFileName(accountName, "player") + ".png"

    fun skinFile(fileName: String): File? {
        if (fileName.isBlank()) return null
        val file = File(Paths.skinsRoot, fileName)
        return if (file.isFile) file else null
    }

    /** 落盘并返回文件名（不是全路径）——账号表里存文件名，换目录不会失联。 */
    fun save(accountName: String, data: ByteArray): String {
        validate(data)
        val name = fileNameFor(accountName)
        val dest = File(Paths.skinsRoot, name)
        dest.parentFile?.mkdirs()
        dest.writeBytes(data)
        return name
    }

    fun load(account: AuthAccount?): ByteArray? {
        val file = skinFile(account?.skinFile.orEmpty()) ?: return null
        return runCatching { file.readBytes() }.getOrNull()
    }

    fun remove(account: AuthAccount?) {
        skinFile(account?.skinFile.orEmpty())?.delete()
    }

    fun modelOf(account: AuthAccount?): String =
        if (account?.skinModel == SLIM) SLIM else CLASSIC

    /**
     * 正面小人在皮肤图里的取样框：(左, 上, 宽, 高)。
     *
     * 预览按整数倍放大，别用双线性——像素画糊了就不是那张皮肤了。
     * slim 的手臂只有 3 px 宽，这是 1.8 之后 Alex 模型的固定值。
     */
    fun frontViewRegions(slim: Boolean, legacy: Boolean): Map<String, IntArray> {
        val armWidth = if (slim) 3 else 4
        val regions = linkedMapOf(
            "head" to intArrayOf(8, 8, 8, 8),
            "body" to intArrayOf(20, 20, 8, 12),
            "armRight" to intArrayOf(44, 20, armWidth, 12),
            "legRight" to intArrayOf(4, 20, 4, 12),
        )
        // 64x32 的老画布只有右半边，左臂左腿要靠右边那份镜像出来
        regions["armLeft"] = if (legacy) intArrayOf(44, 20, armWidth, 12) else intArrayOf(36, 52, armWidth, 12)
        regions["legLeft"] = if (legacy) intArrayOf(4, 20, 4, 12) else intArrayOf(20, 52, 4, 12)
        return regions
    }
}

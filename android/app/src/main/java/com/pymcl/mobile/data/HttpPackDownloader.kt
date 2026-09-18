package com.pymcl.mobile.data

import java.io.File

/**
 * [PackDownloader] 的真身：走现有的 [Http.download]（带 sha1 校验、断点落成
 * `.part` 再改名、命中相同 sha1 就跳过重下）。
 *
 * 单独一个文件是为了让 [ModpackInstall] 那一边一行网络代码都不沾——编排逻辑
 * 的单测因此不必把 OkHttp 拖进来，也不会不小心真的联网。
 */
object HttpPackDownloader : PackDownloader {
    override fun fetch(
        urls: List<String>,
        dest: File,
        sha1: String?,
        onProgress: (Long, Long) -> Unit,
    ) {
        if (urls.isEmpty()) throw HttpException("没有可用的下载地址 ${dest.name}")
        var last: Exception? = null
        // 逐个候选试过去：整合包的 downloads 数组本身就是「镜像在前、官方垫底」。
        for (url in urls.flatMap { Names.expand(it) }.distinct()) {
            try {
                Http.download(url, dest, sha1, onProgress)
                return
            } catch (e: Exception) {
                last = e
            }
        }
        throw last ?: HttpException("下载失败 ${dest.name}")
    }
}

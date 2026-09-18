package com.pymcl.mobile.ui

import android.graphics.BitmapFactory
import android.util.LruCache
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import com.pymcl.mobile.data.Thumbnails
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.withContext

/**
 * 带网络图的圆角小方块，对齐桌面 `app/widgets.py` 的 `ThumbnailTile`：
 * 内存缓存（240 张）→ 磁盘缓存（[Thumbnails]，7 天）→ 后台下载，最多 4 条并发；
 * 没图、下不到、还在失败冷却期里，都退成 [PclTile] 那种字母底色，不占位不闪。
 *
 * 下载页的搜索结果图标与账号页的头像都用它。解码走 BitmapFactory 按目标尺寸抽样，
 * 不引第三方图片库——与 `WallpaperLayer` 同一个取舍。
 */
private val thumbMemory = LruCache<String, ImageBitmap>(240)

@OptIn(ExperimentalCoroutinesApi::class)
private val thumbPool = Dispatchers.IO.limitedParallelism(4)

@Composable
fun ThumbnailTile(text: String, url: String, tint: Color, size: Int = 36) {
    if (url.isBlank()) {
        PclTile(text, tint, size)
        return
    }
    val key = "$url|$size"
    val px = with(LocalDensity.current) { size.dp.roundToPx() }
    var image by remember(key) { mutableStateOf(thumbMemory.get(key)) }

    LaunchedEffect(key) {
        if (image != null) return@LaunchedEffect
        val decoded = withContext(thumbPool) {
            // ensureThumb 自己会先看磁盘缓存、再看失败冷却表，命中就不碰网络
            val local = Thumbnails.ensureThumb(url)
            if (local.isBlank()) null else decodeThumb(local, px)
        }
        if (decoded != null) {
            thumbMemory.put(key, decoded)
            image = decoded
        }
    }

    val bitmap = image
    if (bitmap == null) {
        PclTile(text, tint, size)
    } else {
        Image(
            bitmap = bitmap,
            contentDescription = null,
            modifier = Modifier.size(size.dp).clip(RoundedCornerShape(8.dp)),
            contentScale = ContentScale.Crop,
        )
    }
}

/** 先读尺寸再按 2 的幂抽样解码：搜索结果的图标动辄 512×512，原图解出来一屏几十张就是几十 MB。 */
private fun decodeThumb(path: String, targetPx: Int): ImageBitmap? = runCatching {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeFile(path, bounds)
    if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return@runCatching null
    var sample = 1
    val want = targetPx.coerceAtLeast(1) * 2
    while (bounds.outWidth / (sample * 2) >= want && bounds.outHeight / (sample * 2) >= want) sample *= 2
    val opts = BitmapFactory.Options().apply { inSampleSize = sample }
    BitmapFactory.decodeFile(path, opts)?.asImageBitmap()
}.getOrNull()

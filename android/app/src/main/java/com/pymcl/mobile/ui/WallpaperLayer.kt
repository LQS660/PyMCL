package com.pymcl.mobile.ui

import android.graphics.BitmapFactory
import android.os.Build
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.blur
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import com.pymcl.mobile.data.WallpaperKind
import com.pymcl.mobile.data.WallpaperLook
import com.pymcl.mobile.data.WallpaperRef
import com.pymcl.mobile.data.WallpaperState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import java.io.File

/**
 * 壁纸渲染层，对齐桌面 app/background.py 的 BackgroundLayer。
 *
 * 桌面那边的教训是：把背景当 QSS 的 border-image 贴在内容控件上，只盖得住右侧
 * 内容区，侧栏透出来的还是窗口底色。这里照它最后的做法——壁纸是压在所有内容
 * 下面的一整层，顶栏底栏调低不透明度就能透出来。所以 [WallpaperBackdrop] 收
 * content 而不是反过来被塞进某个页面里。
 *
 * 本文件不引任何第三方库：解码走 BitmapFactory，淡入淡出走 compose 自带的
 * Animatable。视频壁纸本轮不做，接口已留位（见 [WallpaperKind.VIDEO]）。
 */

/** 淡入淡出时长，跟桌面换图的观感对齐。 */
private const val FADE_MS = 420

/** blur=100 时的最大模糊半径。再大就只剩一团颜色，认不出是哪张图了。 */
private const val MAX_BLUR_DP = 40f

/**
 * 铺一层壁纸，然后把 [content] 画在它上面。
 *
 * 下一批接主界面时就用它包住现有的 Scaffold，见本文件末尾的接入示例。
 *
 * @param baseColor 壁纸之下的底色。解不出图、清单为空、遇到 VIDEO 都回退到它，
 *   所以任何一条失败路径都不会出现黑屏。
 * @param scrimColor 遮罩用的颜色，一般就是主题底色。
 * @param onUnavailable 某张图解不出来时回调一次，调用方可以据此把它从清单里剔掉。
 */
@Composable
fun WallpaperBackdrop(
    state: WallpaperState,
    baseColor: Color,
    modifier: Modifier = Modifier,
    scrimColor: Color = baseColor,
    onUnavailable: (WallpaperRef) -> Unit = {},
    content: @Composable BoxScope.() -> Unit,
) {
    Box(modifier) {
        WallpaperLayer(
            ref = state.playlist.current(),
            look = state.look,
            baseColor = baseColor,
            modifier = Modifier.fillMaxSize(),
            scrimColor = scrimColor,
            onUnavailable = onUnavailable,
        )
        content()
    }
}

/** 只画壁纸本身，不管上层内容。需要自己控制层级时用这个。 */
@Composable
fun WallpaperLayer(
    ref: WallpaperRef?,
    look: WallpaperLook,
    baseColor: Color,
    modifier: Modifier = Modifier,
    scrimColor: Color = baseColor,
    onUnavailable: (WallpaperRef) -> Unit = {},
) {
    val clamped = look.clamped()
    val report by rememberUpdatedState(onUnavailable)

    BoxWithConstraints(modifier.background(baseColor)) {
        val widthPx = constraints.maxWidth
        val heightPx = constraints.maxHeight
        // API 31 以下 Modifier.blur 是空操作，只能靠降采样再放大凑一个近似的糊。
        val realBlur = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S
        val downsample = if (realBlur) 1 else blurDownsample(clamped.blur)

        val decoded by produceState<ImageBitmap?>(null, ref, widthPx, heightPx, downsample) {
            val target = ref
            if (target == null || target.kind != WallpaperKind.IMAGE || widthPx <= 0 || heightPx <= 0) {
                value = null
                return@produceState
            }
            val bitmap = withContext(Dispatchers.IO) {
                decodeScaled(target.uri, widthPx, heightPx, downsample)
            }
            if (bitmap == null) report(target)
            value = bitmap
        }

        var shown by remember { mutableStateOf<ImageBitmap?>(null) }
        var outgoing by remember { mutableStateOf<ImageBitmap?>(null) }
        val fade = remember { Animatable(1f) }
        LaunchedEffect(decoded) {
            if (decoded === shown) return@LaunchedEffect
            outgoing = shown
            shown = decoded
            fade.snapTo(0f)
            fade.animateTo(1f, tween(FADE_MS))
            outgoing = null
        }

        val blurModifier = if (realBlur && clamped.blur > 0) {
            Modifier.blur((clamped.blur / 100f * MAX_BLUR_DP).dp)
        } else {
            Modifier
        }

        outgoing?.let {
            Image(
                bitmap = it,
                contentDescription = null,
                modifier = Modifier.matchParentSize().then(blurModifier),
                contentScale = ContentScale.Crop,
                alpha = 1f - fade.value,
            )
        }
        shown?.let {
            Image(
                bitmap = it,
                contentDescription = null,
                modifier = Modifier.matchParentSize().then(blurModifier),
                contentScale = ContentScale.Crop,
                alpha = fade.value,
            )
        }
        if (clamped.scrim > 0 && (shown != null || outgoing != null)) {
            Box(
                Modifier
                    .matchParentSize()
                    .background(scrimColor.copy(alpha = clamped.scrim / 100f)),
            )
        }
    }
}

/**
 * 自动轮播的节拍器：到点了叫一次 [onRotate]，由调用方去跑
 * `WallpaperState.rotated()`。翻页动作本身不在这儿做，免得渲染层碰状态。
 */
@Composable
fun WallpaperRotationEffect(state: WallpaperState, onRotate: () -> Unit) {
    val tick by rememberUpdatedState(onRotate)
    val rotates = state.playlist.rotates
    val minutes = state.playlist.intervalMinutes
    LaunchedEffect(rotates, minutes) {
        if (!rotates) return@LaunchedEffect
        while (true) {
            delay(minutes * 60_000L)
            tick()
        }
    }
}

/** 顶栏 / 底栏该用的颜色：面板不透明度调低了，壁纸才透得出来。 */
fun WallpaperLook.panelColor(base: Color): Color =
    base.copy(alpha = panelAlpha.coerceIn(0, 100) / 100f)

/**
 * 按容器尺寸降采样解码。手机上整张原图直接进内存很容易把 largeHeap 也吃穿，
 * 而且壁纸最终是 Crop 铺满，解到屏幕这么大就够了。
 *
 * 只认本地文件路径。SAF 的 content:// 要 ContentResolver，那要改 Activity 与
 * manifest（t-148 里记的 C6 地基），归后续那条活。解不出来一律返回 null，
 * 由调用方回退底色。
 */
private fun decodeScaled(uri: String, targetW: Int, targetH: Int, extraDownsample: Int): ImageBitmap? {
    if (targetW <= 0 || targetH <= 0) return null
    val file = File(uri)
    if (!file.isFile || file.length() <= 0L) return null
    return runCatching {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(uri, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while (bounds.outWidth / (sample * 2) >= targetW && bounds.outHeight / (sample * 2) >= targetH) {
            sample *= 2
        }
        val opts = BitmapFactory.Options().apply {
            inSampleSize = (sample * extraDownsample).coerceAtLeast(1)
        }
        BitmapFactory.decodeFile(uri, opts)?.asImageBitmap()
    }.getOrNull()
}

/** API 31 以下的模糊近似：糊到什么程度就降采样到几分之一。 */
private fun blurDownsample(blur: Int): Int = when {
    blur <= 0 -> 1
    blur < 34 -> 2
    blur < 67 -> 4
    else -> 8
}

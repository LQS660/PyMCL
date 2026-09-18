package com.pymcl.mobile

import android.graphics.SurfaceTexture
import android.os.Bundle
import android.view.Surface
import android.view.TextureView
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.Surface as M3Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import com.pymcl.mobile.data.JvmHost
import com.pymcl.mobile.data.JvmRun
import com.pymcl.mobile.data.Settings
import com.pymcl.mobile.data.SettingsKeys
import com.pymcl.mobile.theme.LocalPclColors
import com.pymcl.mobile.theme.PclDanger
import com.pymcl.mobile.theme.PyMclTheme
import com.pymcl.mobile.ui.PclButton
import com.pymcl.mobile.ui.PclCard
import com.pymcl.mobile.ui.PclLink

/**
 * 安装器 / Jar 执行器的 JVM 宿主。
 *
 * 跟 `GameActivity` 是一对：那个跑游戏、要一整块画面；这个跑安装器，
 * 只要实时日志、退出码和一个取消键。但 JVM 仍然需要一个 Surface 才起得来
 * （内核那边 `execute(Surface, callback)` 是硬要求），所以这里留了一个
 * **1dp 的 TextureView**——它不是给人看的，是给 JVM 拿去当窗口的。
 *
 * 调用方先 `JvmHost.prepare(...)` 把参数备好，再 startActivity 进来。
 */
class JvmHostActivity : ComponentActivity(), TextureView.SurfaceTextureListener {

    private var started = false
    private var onRun: ((JvmRun) -> Unit)? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 装 Forge 要跑好几分钟的 processor，中途锁屏会把 JVM 一起冻住
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        val initial = JvmHost.snapshot()
        if (initial == null) {
            finish()
            return
        }

        setContent {
            PyMclTheme(
                themeColor = Settings.str(SettingsKeys.THEME_COLOR, "#2E9B6B"),
                dark = Settings.bool(SettingsKeys.UI_DARK),
            ) {
                var run by androidx.compose.runtime.remember { mutableStateOf(initial) }
                // 内核在自己的线程上回调，这里切回主线程再改 state
                LaunchedEffect(Unit) {
                    onRun = { next -> runOnUiThread { run = next } }
                }
                M3Surface(Modifier.fillMaxSize()) { HostScreen(run) }
            }
        }
    }

    @Composable
    private fun HostScreen(run: JvmRun) {
        val c = LocalPclColors.current
        val listState = rememberLazyListState()
        // 日志在刷就一直贴着底，用户不用一直往下拨
        LaunchedEffect(run.lines.size) {
            if (run.lines.isNotEmpty()) listState.animateScrollToItem(run.lines.size - 1)
        }
        Column(
            Modifier
                .fillMaxSize()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(run.job.title, fontWeight = FontWeight.Bold, fontSize = 20.sp, color = c.text)
            PclCard {
                Text(
                    JvmHost.exitSummary(run.job, run.exitCode, run.cancelled),
                    color = when {
                        run.cancelled -> c.muted
                        run.exitCode == null -> c.accent
                        run.exitCode == 0 -> c.accent
                        else -> PclDanger
                    },
                    fontSize = 14.sp,
                )
                Text("日志 ${JvmHost.logFile(this@JvmHostActivity, run.job).absolutePath}", color = c.muted, fontSize = 10.sp)
            }

            LazyColumn(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth(),
                state = listState,
            ) {
                // key 带下标：同一行文本会重复出现（下载进度那种），不能只用内容当 key
                itemsIndexed(run.lines, key = { i, line -> "$i-${line.hashCode()}" }) { _, line ->
                    Text(line, fontFamily = FontFamily.Monospace, fontSize = 10.sp, color = c.text)
                }
            }

            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (run.finished) {
                    PclButton("返回") { finish() }
                } else {
                    PclButton("取消") { JvmHost.cancel()?.let { onRun?.invoke(it) } }
                }
                PclLink("复制日志路径") {
                    val cm = getSystemService(CLIPBOARD_SERVICE) as android.content.ClipboardManager
                    cm.setPrimaryClip(
                        android.content.ClipData.newPlainText(
                            "log",
                            JvmHost.logFile(this@JvmHostActivity, run.job).absolutePath,
                        ),
                    )
                }
            }

            // JVM 要一个窗口才起得来；这一块不是给人看的，所以只给 1dp
            Box(Modifier.size(1.dp)) {
                AndroidView(factory = { ctx ->
                    TextureView(ctx).also { it.surfaceTextureListener = this@JvmHostActivity }
                })
            }
        }
    }

    // ------------------------------------------------------- Surface 生命周期
    override fun onSurfaceTextureAvailable(texture: SurfaceTexture, width: Int, height: Int) {
        // 只起一次：转屏会把 Surface 重建一遍，再 execute 一次就是两个 JVM
        if (started) return
        started = true
        texture.setDefaultBufferSize(1, 1)
        JvmHost.attach(Surface(texture)) { next -> onRun?.invoke(next) }
    }

    override fun onSurfaceTextureSizeChanged(texture: SurfaceTexture, width: Int, height: Int) = Unit

    override fun onSurfaceTextureDestroyed(texture: SurfaceTexture): Boolean = true

    override fun onSurfaceTextureUpdated(texture: SurfaceTexture) = Unit

    override fun onDestroy() {
        // 用户直接退出去时也得把 JVM 掐掉，不然它在后台接着跑
        if (JvmHost.snapshot()?.finished == false) JvmHost.cancel()
        onRun = null
        super.onDestroy()
    }
}

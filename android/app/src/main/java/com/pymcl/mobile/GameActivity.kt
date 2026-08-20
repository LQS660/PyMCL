package com.pymcl.mobile

import android.app.Activity
import android.graphics.Color
import android.graphics.SurfaceTexture
import android.os.Bundle
import android.view.Surface
import android.view.TextureView
import android.view.WindowManager
import android.widget.FrameLayout
import android.widget.Toast
import com.pymcl.mobile.data.McLaunch
import com.tungsten.fclauncher.bridge.FCLBridge
import com.tungsten.fclauncher.bridge.FCLBridgeCallback
import com.tungsten.fclauncher.keycodes.LwjglGlfwKeycode
import com.tungsten.fclauncher.utils.FCLPath
import org.lwjgl.glfw.CallbackBridge

class GameActivity : Activity(), TextureView.SurfaceTextureListener, FCLBridgeCallback {
    private lateinit var texture: TextureView
    private lateinit var touch: GameTouchView
    private var running = false
    private val bridge: FCLBridge
        get() = McLaunch.bridge ?: throw IllegalStateException("McLaunch.bridge 空")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        FCLPath.CONTEXT = this
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN)
        val root = FrameLayout(this)
        root.setBackgroundColor(Color.BLACK)
        texture = TextureView(this)
        texture.surfaceTextureListener = this
        touch = GameTouchView(this)
        root.addView(
            texture,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            ),
        )
        root.addView(
            touch,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            ),
        )
        setContentView(root)
    }

    override fun onSurfaceTextureAvailable(surfaceTexture: SurfaceTexture, width: Int, height: Int) {
        val w = if (width > 0) width else FCLBridge.DEFAULT_WIDTH
        val h = if (height > 0) height else FCLBridge.DEFAULT_HEIGHT
        surfaceTexture.setDefaultBufferSize(w, h)
        touch.bridge = bridge
        if (running) {
            bridge.setSurfaceTexture(surfaceTexture)
            CallbackBridge.setupBridgeWindow(Surface(surfaceTexture))
            bridge.pushEventWindow(w, h)
            return
        }
        running = true
        bridge.setSurfaceDestroyed(false)
        bridge.setSurfaceTexture(surfaceTexture)
        bridge.execute(Surface(surfaceTexture), this)
        bridge.pushEventWindow(w, h)
    }

    override fun onSurfaceTextureSizeChanged(surfaceTexture: SurfaceTexture, width: Int, height: Int) {
        surfaceTexture.setDefaultBufferSize(width, height)
        bridge.pushEventWindow(width, height)
    }

    override fun onSurfaceTextureDestroyed(surfaceTexture: SurfaceTexture): Boolean {
        bridge.setSurfaceDestroyed(true)
        return true
    }

    override fun onSurfaceTextureUpdated(surfaceTexture: SurfaceTexture) = Unit

    override fun onCursorModeChange(mode: Int) {
        runOnUiThread {
            touch.cursorCaptured = mode == FCLBridge.CursorDisabled
        }
    }

    override fun onLog(log: String?) {
        if (!log.isNullOrBlank()) android.util.Log.i("PyMCL-MC", log.trim())
    }

    override fun onExit(code: Int) {
        runOnUiThread {
            Toast.makeText(this, "游戏退出 $code", Toast.LENGTH_LONG).show()
            finish()
        }
    }

    override fun onPause() {
        CallbackBridge.nativeSetWindowAttrib(LwjglGlfwKeycode.GLFW_FOCUSED, 0)
        if (touch.cursorCaptured) {
            bridge.pushEventKey(LwjglGlfwKeycode.KEY_ESCAPE.toInt(), 0, true)
            bridge.pushEventKey(LwjglGlfwKeycode.KEY_ESCAPE.toInt(), 0, false)
        }
        super.onPause()
    }

    override fun onResume() {
        super.onResume()
        CallbackBridge.nativeSetWindowAttrib(LwjglGlfwKeycode.GLFW_FOCUSED, 1)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        bridge.pushEventKey(LwjglGlfwKeycode.KEY_ESCAPE.toInt(), 0, true)
        bridge.pushEventKey(LwjglGlfwKeycode.KEY_ESCAPE.toInt(), 0, false)
    }
}

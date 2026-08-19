package com.pymcl.mobile

import android.app.Activity
import android.graphics.Color
import android.graphics.SurfaceTexture
import android.os.Bundle
import android.view.Gravity
import android.view.MotionEvent
import android.view.Surface
import android.view.TextureView
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.Toast
import com.pymcl.mobile.data.McLaunch
import com.tungsten.fclauncher.bridge.FCLBridge
import com.tungsten.fclauncher.bridge.FCLBridgeCallback
import com.tungsten.fclauncher.keycodes.LwjglGlfwKeycode
import com.tungsten.fclauncher.utils.FCLPath
import org.lwjgl.glfw.CallbackBridge

class GameActivity : Activity(), TextureView.SurfaceTextureListener, FCLBridgeCallback {
    private lateinit var texture: TextureView
    private var running = false
    private var cursorCaptured = false
    private var lastX = 0f
    private var lastY = 0f
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
        root.addView(
            texture,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            ),
        )
        root.addView(controls(), FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.WRAP_CONTENT,
            Gravity.BOTTOM,
        ))
        setContentView(root)
        texture.setOnTouchListener { _, event -> handleTouch(event) }
    }

    private fun controls(): View {
        val row = LinearLayout(this)
        row.orientation = LinearLayout.HORIZONTAL
        row.setBackgroundColor(0x66000000)
        row.gravity = Gravity.CENTER
        fun key(label: String, code: Short) {
            val b = Button(this)
            b.text = label
            b.setOnTouchListener { _, e ->
                when (e.actionMasked) {
                    MotionEvent.ACTION_DOWN -> bridge.pushEventKey(code.toInt(), 0, true)
                    MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL ->
                        bridge.pushEventKey(code.toInt(), 0, false)
                }
                true
            }
            row.addView(b, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        }
        key("ESC", LwjglGlfwKeycode.KEY_ESCAPE)
        key("E", LwjglGlfwKeycode.KEY_E)
        key("跳", LwjglGlfwKeycode.KEY_SPACE)
        key("潜", LwjglGlfwKeycode.KEY_LEFT_SHIFT)
        val rmb = Button(this)
        rmb.text = "右键"
        rmb.setOnTouchListener { _, e ->
            val press = e.actionMasked == MotionEvent.ACTION_DOWN
            if (e.actionMasked == MotionEvent.ACTION_DOWN ||
                e.actionMasked == MotionEvent.ACTION_UP ||
                e.actionMasked == MotionEvent.ACTION_CANCEL
            ) {
                bridge.pushEventMouseButton(FCLBridge.Button2, press)
            }
            true
        }
        row.addView(rmb, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        return row
    }

    private fun handleTouch(event: MotionEvent): Boolean {
        val x = event.x
        val y = event.y
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                lastX = x
                lastY = y
                if (!cursorCaptured) {
                    bridge.pushEventPointer(x, y)
                    bridge.pushEventMouseButton(FCLBridge.Button1, true)
                }
            }
            MotionEvent.ACTION_MOVE -> {
                if (cursorCaptured) {
                    val dx = x - lastX
                    val dy = y - lastY
                    CallbackBridge.sendCursorPos(
                        CallbackBridge.mouseX + dx,
                        CallbackBridge.mouseY + dy,
                    )
                } else {
                    bridge.pushEventPointer(x, y)
                }
                lastX = x
                lastY = y
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                if (!cursorCaptured) {
                    bridge.pushEventPointer(x, y)
                    bridge.pushEventMouseButton(FCLBridge.Button1, false)
                } else {
                    bridge.pushEventMouseButton(FCLBridge.Button1, true)
                    bridge.pushEventMouseButton(FCLBridge.Button1, false)
                }
            }
        }
        return true
    }

    override fun onSurfaceTextureAvailable(surfaceTexture: SurfaceTexture, width: Int, height: Int) {
        val w = if (width > 0) width else FCLBridge.DEFAULT_WIDTH
        val h = if (height > 0) height else FCLBridge.DEFAULT_HEIGHT
        surfaceTexture.setDefaultBufferSize(w, h)
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
        cursorCaptured = mode == FCLBridge.CursorDisabled
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
        CallbackBridge.nativeSetWindowAttrib(LwjglGlfwKeycode.GLFW_FOCUSED.toInt(), 0)
        super.onPause()
    }

    override fun onResume() {
        super.onResume()
        CallbackBridge.nativeSetWindowAttrib(LwjglGlfwKeycode.GLFW_FOCUSED.toInt(), 1)
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        bridge.pushEventKey(LwjglGlfwKeycode.KEY_ESCAPE.toInt(), 0, true)
        bridge.pushEventKey(LwjglGlfwKeycode.KEY_ESCAPE.toInt(), 0, false)
    }
}

package com.pymcl.mobile

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.os.Handler
import android.os.Looper
import android.view.MotionEvent
import android.view.View
import com.tungsten.fclauncher.bridge.FCLBridge
import com.tungsten.fclauncher.keycodes.LwjglGlfwKeycode
import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.math.max

/**
 * FCL TouchPad + ControlDirection 的精简重写：
 * 菜单（光标开）：点哪点哪，短按左键，长按右键。
 * 进世界（光标关）：左半屏摇杆 WASD，右半屏滑动视角；短按攻击，长按放置，双击跳。
 * 返回键 ESC 在 Activity 里处理。
 */
class GameTouchView(context: Context) : View(context) {
    var cursorCaptured = false
    lateinit var bridge: FCLBridge

    private val handler = Handler(Looper.getMainLooper())
    private val stickPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 4f
        color = 0x66FFFFFF
    }
    private val knobPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        color = 0x55FFFFFF
    }

    private var lookId = -1
    private var stickId = -1
    private var lookDownX = 0f
    private var lookDownY = 0f
    private var lookAt = 0L
    private var lastTapAt = 0L
    private var holdingLeft = false
    private var holdingRight = false
    private var stickCx = 0f
    private var stickCy = 0f
    private var stickX = 0f
    private var stickY = 0f
    private var wOn = false
    private var aOn = false
    private var sOn = false
    private var dOn = false

    private val longPress = Runnable {
        if (!::bridge.isInitialized) return@Runnable
        if (holdingLeft) click(FCLBridge.Button1, false)
        holdingLeft = false
        click(FCLBridge.Button2, true)
        holdingRight = true
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (!cursorCaptured || stickId < 0) return
        val r = stickRadius()
        canvas.drawCircle(stickCx, stickCy, r, stickPaint)
        canvas.drawCircle(stickX, stickY, r * 0.35f, knobPaint)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (!::bridge.isInitialized) return true
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_POINTER_DOWN -> {
                val i = event.actionIndex
                val id = event.getPointerId(i)
                val x = event.getX(i)
                val y = event.getY(i)
                if (cursorCaptured && x < width * 0.42f && stickId < 0) {
                    stickId = id
                    stickCx = x
                    stickCy = y
                    stickX = x
                    stickY = y
                    invalidate()
                } else if (lookId < 0) {
                    lookId = id
                    lookDownX = x
                    lookDownY = y
                    lookAt = System.currentTimeMillis()
                    if (!cursorCaptured) {
                        bridge.pushEventPointer(x, y)
                        click(FCLBridge.Button1, true)
                        holdingLeft = true
                    }
                    handler.removeCallbacks(longPress)
                    handler.postDelayed(longPress, 400)
                }
            }
            MotionEvent.ACTION_MOVE -> {
                for (i in 0 until event.pointerCount) {
                    val id = event.getPointerId(i)
                    val x = event.getX(i)
                    val y = event.getY(i)
                    if (id == stickId) {
                        updateStick(x, y)
                    } else if (id == lookId) {
                        val dx = x - lookDownX
                        val dy = y - lookDownY
                        if (hypot(dx, dy) > 12f) handler.removeCallbacks(longPress)
                        if (cursorCaptured) {
                            bridge.pushEventPointer(
                                org.lwjgl.glfw.CallbackBridge.mouseX + dx,
                                org.lwjgl.glfw.CallbackBridge.mouseY + dy,
                            )
                            lookDownX = x
                            lookDownY = y
                        } else {
                            bridge.pushEventPointer(x, y)
                        }
                    }
                }
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_POINTER_UP, MotionEvent.ACTION_CANCEL -> {
                val i = event.actionIndex
                val id = event.getPointerId(i)
                val x = event.getX(i)
                val y = event.getY(i)
                if (id == stickId) {
                    stickId = -1
                    setMove(false, false, false, false)
                    invalidate()
                }
                if (id == lookId) {
                    handler.removeCallbacks(longPress)
                    val dt = System.currentTimeMillis() - lookAt
                    val moved = hypot(x - lookDownX, y - lookDownY) > 16f
                    if (cursorCaptured) {
                        if (holdingRight) click(FCLBridge.Button2, false)
                        else if (dt <= 140 && !moved) {
                            val now = System.currentTimeMillis()
                            if (now - lastTapAt < 280) {
                                tapKey(LwjglGlfwKeycode.KEY_SPACE)
                                lastTapAt = 0
                            } else {
                                click(FCLBridge.Button1, true)
                                click(FCLBridge.Button1, false)
                                lastTapAt = now
                            }
                        }
                    } else {
                        if (holdingLeft) click(FCLBridge.Button1, false)
                        if (holdingRight) click(FCLBridge.Button2, false)
                    }
                    holdingLeft = false
                    holdingRight = false
                    lookId = -1
                }
            }
        }
        return true
    }

    private fun updateStick(x: Float, y: Float) {
        val r = stickRadius()
        var dx = x - stickCx
        var dy = y - stickCy
        val len = hypot(dx, dy)
        if (len > r && len > 0f) {
            dx = dx / len * r
            dy = dy / len * r
        }
        stickX = stickCx + dx
        stickY = stickCy + dy
        val nx = if (len < r * 0.22f) 0f else dx / r
        val ny = if (len < r * 0.22f) 0f else dy / r
        val angle = Math.toDegrees(atan2(ny.toDouble(), nx.toDouble())).toFloat()
        val mag = hypot(nx, ny)
        var w = false
        var a = false
        var s = false
        var d = false
        if (mag >= 0.22f) {
            // 0°=右, 90°=下, -90°=上
            when {
                angle in -112.5f..-67.5f -> w = true
                angle in -67.5f..-22.5f -> { w = true; d = true }
                angle in -22.5f..22.5f -> d = true
                angle in 22.5f..67.5f -> { s = true; d = true }
                angle in 67.5f..112.5f -> s = true
                angle in 112.5f..157.5f -> { s = true; a = true }
                angle >= 157.5f || angle <= -157.5f -> a = true
                else -> { w = true; a = true }
            }
        }
        setMove(w, a, s, d)
        invalidate()
    }

    private fun setMove(w: Boolean, a: Boolean, s: Boolean, d: Boolean) {
        key(LwjglGlfwKeycode.KEY_W, w, wOn).also { wOn = w }
        key(LwjglGlfwKeycode.KEY_A, a, aOn).also { aOn = a }
        key(LwjglGlfwKeycode.KEY_S, s, sOn).also { sOn = s }
        key(LwjglGlfwKeycode.KEY_D, d, dOn).also { dOn = d }
    }

    private fun key(code: Short, now: Boolean, was: Boolean) {
        if (now == was) return
        bridge.pushEventKey(code.toInt(), 0, now)
    }

    private fun tapKey(code: Short) {
        bridge.pushEventKey(code.toInt(), 0, true)
        bridge.pushEventKey(code.toInt(), 0, false)
    }

    private fun click(button: Int, press: Boolean) {
        bridge.pushEventMouseButton(button, press)
    }

    private fun stickRadius(): Float = max(width * 0.11f, 90f)

    override fun onDetachedFromWindow() {
        handler.removeCallbacks(longPress)
        setMove(false, false, false, false)
        super.onDetachedFromWindow()
    }
}

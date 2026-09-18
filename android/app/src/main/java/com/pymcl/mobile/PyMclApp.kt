package com.pymcl.mobile

import android.app.Application
import com.pymcl.mobile.data.I18n
import com.pymcl.mobile.data.Paths
import com.pymcl.mobile.data.Settings
import com.pymcl.mobile.data.UpdateCheck

class PyMclApp : Application() {
    override fun onCreate() {
        super.onCreate()
        bind(this)
        Paths.root
        // 词表要在第一帧组合之前就位，否则首屏先闪一遍中文再换语言
        I18n.init(this)
        // 启动器自更新清单：对齐桌面 _boot_extras，`auto_check_update` 开着才查，后台线程、失败静默；
        // 结论落在 UpdateCheck.last，设置页「账号与更新」那一块拿它展示
        UpdateCheck.checkOnStartupAsync()
    }

    /**
     * 退到后台时把攒着的设置改动一次写出去。
     *
     * 设置页每点一个开关只改内存里那份（见 `Settings.set`），
     * 落盘统一在这儿和离开设置页时做——不然滑一次内存滑杆就是几十次写盘。
     */
    override fun onTrimMemory(level: Int) {
        super.onTrimMemory(level)
        if (level >= TRIM_MEMORY_UI_HIDDEN) Settings.flushIfDirty()
    }

    companion object {
        lateinit var instance: Application
            private set

        @JvmStatic
        fun bind(app: Application) {
            instance = app
        }
    }
}

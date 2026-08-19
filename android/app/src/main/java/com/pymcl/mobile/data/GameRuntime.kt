package com.pymcl.mobile.data

import android.content.Context

object GameRuntime {
    const val ENGINE = "PyMCL Runtime / FCLauncher JNI"

    fun installed(context: Context): String {
        return if (RuntimeInstaller.ready(context, "jre17") || RuntimeInstaller.ready(context, "jre21")) {
            ENGINE
        } else {
            "未解压（点启动会自动装 JRE）"
        }
    }
}

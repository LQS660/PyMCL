package com.pymcl.mobile

import com.pymcl.mobile.data.Paths
import com.tungsten.fcl.FCLApplication
import com.tungsten.fclauncher.plugins.DriverPlugin
import com.tungsten.fclauncher.utils.FCLPath

class PyMclApp : FCLApplication() {
    override fun onCreate() {
        super.onCreate()
        bind(this)
        FCLPath.loadPaths(this)
        DriverPlugin.init(this)
        Paths.root
    }

    companion object {
        lateinit var instance: android.app.Application
            private set

        @JvmStatic
        fun bind(app: android.app.Application) {
            instance = app
        }
    }
}

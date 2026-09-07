package com.pymcl.mobile

import android.app.Application
import com.pymcl.mobile.data.AiRepo
import com.pymcl.mobile.data.AuthRepo
import com.pymcl.mobile.data.CatalogRepo
import com.pymcl.mobile.data.InstanceStore
import com.pymcl.mobile.data.LaunchPlanner
import com.pymcl.mobile.data.ManifestRepo
import com.pymcl.mobile.data.Paths

class PyMclApp : Application() {
    lateinit var instanceStore: InstanceStore
        private set
    lateinit var manifestRepo: ManifestRepo
        private set
    lateinit var authRepo: AuthRepo
        private set
    lateinit var catalogRepo: CatalogRepo
        private set
    lateinit var aiRepo: AiRepo
        private set
    lateinit var launchPlanner: LaunchPlanner
        private set

    override fun onCreate() {
        super.onCreate()
        Paths.ensureLayout(this)
        instanceStore = InstanceStore(this)
        manifestRepo = ManifestRepo(this)
        authRepo = AuthRepo(this, instanceStore)
        catalogRepo = CatalogRepo()
        aiRepo = AiRepo()
        launchPlanner = LaunchPlanner(this, manifestRepo, instanceStore)
    }

    companion object {
        fun get(app: Application): PyMclApp = app as PyMclApp
    }
}
: PyMclApp = app as PyMclApp
    }
}

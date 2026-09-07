package com.pymcl.mobile.data

import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

object Http {
    const val USER_AGENT = "PyMCL/1.0.1 (android; +minecraft launcher)"
    const val BMCL_MANIFEST =
        "https://bmclapi2.bangbang93.com/mc/game/version_manifest_v2.json"
    const val OFFICIAL_MANIFEST =
        "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json"
    const val MODRINTH_API = "https://mod.mcimirror.top/modrinth/v2"

    val client: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                chain.proceed(
                    chain.request().newBuilder()
                        .header("User-Agent", USER_AGENT)
                        .build(),
                )
            }
            .build()
    }
}

package com.pymcl.mobile.data

import android.content.Context
import java.io.File

/** 数据根路径：`context.filesDir/pymcl/` ≡ 桌面 `PYMCL_HOME` */
object Paths {
    private const val ROOT = "pymcl"

    fun root(context: Context): File = File(context.filesDir, ROOT)

    fun config(context: Context): File = File(root(context), "config.json")

    fun accounts(context: Context): File = File(root(context), "accounts.json")

    fun versionManifestCache(context: Context): File =
        File(root(context), "cache/version_manifest.json")

    fun minecraftRoot(context: Context): File = File(root(context), ".minecraft")

    fun instanceDir(context: Context, instanceId: String): File =
        File(minecraftRoot(context), instanceId)

    fun instanceMeta(context: Context, instanceId: String): File =
        File(instanceDir(context, instanceId), ".instance.json")

    fun ensureLayout(context: Context) {
        listOf(
            root(context),
            File(root(context), "cache"),
            minecraftRoot(context),
        ).forEach { it.mkdirs() }
    }
}

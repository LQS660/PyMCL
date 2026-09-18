package com.pymcl.mobile

import com.pymcl.mobile.data.JavaRuntime
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Java 多发行版，对照桌面 `mclauncher/java.py` 的 `JAVA_VENDORS` / `java_vendor_list` / `java_vendor_label`：
 * 三家、顺序、显示名、大小写与兜底规则都要一样，Java 页的发行版选项就是从这里来的。
 */
class JavaVendorTest {
    /** 桌面 `JAVA_VENDORS` 原样。 */
    private val desktop = linkedMapOf(
        "adoptium" to "Adoptium Temurin",
        "zulu" to "Azul Zulu",
        "microsoft" to "Microsoft OpenJDK",
    )

    @Test
    fun vendorListIsExactlyTheDesktopOne() {
        assertEquals(desktop.keys.toList(), JavaRuntime.vendorKeys)
        assertEquals(desktop.keys.toList(), JavaRuntime.vendors.map { it.key })
        assertEquals(desktop.values.toList(), JavaRuntime.vendors.map { it.label })
        // 桌面 Java 页默认选 adoptium，所以它必须排第一
        assertEquals("adoptium", JavaRuntime.vendorKeys.first())
    }

    @Test
    fun labelsFollowDesktopRules() {
        for ((key, label) in desktop) assertEquals(label, JavaRuntime.vendorLabel(key))
        // 桌面 `str(vendor or "").lower()`：大小写、首尾空白都收
        assertEquals("Azul Zulu", JavaRuntime.vendorLabel("ZULU"))
        assertEquals("Microsoft OpenJDK", JavaRuntime.vendorLabel(" Microsoft "))
        // 不认识的原样回，空的兜成 adoptium（桌面 `str(vendor or "adoptium")`）
        assertEquals("graal", JavaRuntime.vendorLabel("graal"))
        assertEquals("adoptium", JavaRuntime.vendorLabel(""))
    }

    @Test
    fun everyVendorHasADownloadRoute() {
        for (key in JavaRuntime.vendorKeys) {
            val url = JavaRuntime.downloadUrl(key, 17, "arm64-v8a")
            assertTrue("$key 没有下载地址", url.startsWith("https://"))
        }
        assertTrue(JavaRuntime.downloadUrl("adoptium", 17, "arm64-v8a").contains("api.adoptium.net"))
        assertTrue(JavaRuntime.downloadUrl("zulu", 17, "arm64-v8a").contains("api.azul.com"))
        assertTrue(JavaRuntime.downloadUrl("microsoft", 17, "arm64-v8a").contains("aka.ms/download-jdk"))
        // 键大小写不敏感，跟 vendorLabel 一个脾气；不认识的退回 adoptium
        assertEquals(JavaRuntime.downloadUrl("zulu", 17, "arm64-v8a"), JavaRuntime.downloadUrl("Zulu", 17, "arm64-v8a"))
        assertEquals(JavaRuntime.downloadUrl("adoptium", 21, "x86_64"), JavaRuntime.downloadUrl("nope", 21, "x86_64"))
    }

    @Test
    fun downloadUrlsCarryMajorAndArch() {
        assertTrue(JavaRuntime.downloadUrl("zulu", 21, "arm64-v8a").contains("java_version=21"))
        assertTrue(JavaRuntime.downloadUrl("zulu", 21, "arm64-v8a").contains("arch=aarch64"))
        assertTrue(JavaRuntime.downloadUrl("microsoft", 17, "x86_64").endsWith("microsoft-jdk-17-linux-x64.tar.gz"))
        assertTrue(JavaRuntime.downloadUrl("adoptium", 8, "armeabi-v7a").contains("/8/ga/linux/arm/"))
    }
}

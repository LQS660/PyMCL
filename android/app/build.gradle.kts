import com.android.build.api.variant.FilterConfiguration.FilterType.ABI
import com.android.build.gradle.tasks.MergeSourceSetFolders
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

// 运行时（Java / LWJGL / caciocavallo）都躺在 FCL 那个仓库的 assets 里，
// 跟 settings.gradle.kts 里定位子工程用同一套「先相对、再绝对」的退路。
val fclRoot = rootDir.resolve("../FoldCraftLauncher").normalize().let { cand ->
    if (cand.resolve("FCL").isDirectory) cand else file("D:/pymcl-work/FoldCraftLauncher")
}
val fclApp = fclRoot.resolve("FCL")
val fclLibs = fclApp.resolve("libs")
val fclAssets = fclApp.resolve("src/main/assets")
val fclJreAssets = fclApp.resolve("src/main/jreAssets")

android {
    namespace = "com.pymcl.mobile"
    compileSdk = libs.versions.compileSdk.get().toInt()
    defaultConfig {
        applicationId = "com.pymcl.mobile"
        minSdk = libs.versions.minSdk.get().toInt()
        targetSdk = libs.versions.targetSdk.get().toInt()
        versionCode = 2
        versionName = "0.2.0-runtime"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables.useSupportLibrary = true
        ndk {
            // 只出 arm64：JRE 与 LWJGL 的 .so 一套就有好几百 MB，
            // 多打一个 ABI 等于 APK 翻倍，而这几年的机器都是 arm64
            abiFilters += "arm64-v8a"
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
        debug {
            isMinifyEnabled = false
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    packaging {
        jniLibs {
            // JRE 要在运行时按路径 dlopen，压进 APK 里就找不到了
            useLegacyPackaging = true
            // bytehook 与 libc++_shared 会被多个 aar 各带一份，取第一个即可
            pickFirsts += listOf("**/libbytehook.so", "**/libc++_shared.so")
        }
        resources { excludes += "/META-INF/{AL2.0,LGPL2.1}" }
    }
    lint {
        abortOnError = false
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

abstract class FilterJreAssets : Sync() {
    @get:OutputDirectory
    abstract val outputDir: DirectoryProperty
}

/**
 * jreAssets 里躺着 jre8/17/21/25 四套、四种 ABI 的压缩包。
 * 全打进去 APK 会有好几个 GB，这里只留 arm64 要用的那几份。
 */
val filterJreAssets = tasks.register<FilterJreAssets>("filterJreAssets") {
    inputs.property("arch", "arm64")
    from(fclJreAssets)
    into(outputDir)
    exclude("**/jre8/**")
    exclude("**/jre25/**")
    exclude("**/bin-arm.tar.xz")
    exclude("**/bin-x86.tar.xz")
    exclude("**/bin-x86_64.tar.xz")
}

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(filterJreAssets) { it.outputDir }
        if (fclAssets.isDirectory) {
            variant.sources.assets?.addStaticSourceDirectory(fclAssets.invariantSeparatorsPath)
        }
        val variantName = variant.name.replaceFirstChar { it.uppercaseChar() }
        afterEvaluate {
            tasks.named("merge${variantName}Assets", MergeSourceSetFolders::class.java).configure {
                inputs.property("lwjglArch", "arm64")
                doLast {
                    // LWJGL 的 natives 是按 ABI 分目录的，合并完再把用不上的删掉
                    val assetsDir = outputDir.get().asFile
                    val abi = "arm64-v8a"
                    listOf("3.3.3", "3.4.1").forEach { version ->
                        val nativesDir = File(assetsDir, "app_runtime/lwjgl/$version/natives")
                        if (nativesDir.isDirectory) {
                            nativesDir.listFiles()?.forEach { dir ->
                                if (dir.isDirectory && dir.name != abi) {
                                    dir.deleteRecursively()
                                }
                            }
                        }
                    }
                }
            }
        }
        variant.outputs.forEach { output ->
            if (output is com.android.build.api.variant.impl.VariantOutputImpl) {
                val abi = output.getFilter(ABI)?.identifier ?: "arm64-v8a"
                output.outputFileName = "PyMCL-${variant.buildType}-${android.defaultConfig.versionName}-$abi.apk"
            }
        }
    }
}

dependencies {
    implementation(project(":FCLauncher"))
    implementation(project(":Terracotta"))
    // 上游写好的那批安装器（Forge / NeoForge / Fabric / Quilt / OptiFine /
    // LiteLoader / Cleanroom + 五种整合包格式）都在 FCLCore 里
    implementation(project(":FCLCore"))
    implementation(project(":ZipFileSystem"))
    implementation(fileTree(mapOf("dir" to fclLibs, "include" to listOf("*.aar"))))
    // RuntimeInstaller 解 JRE 的 tar.xz 要这两个
    implementation(libs.commons.compress)
    implementation(libs.xz)
    val composeBom = platform("androidx.compose:compose-bom:2024.10.01")
    implementation(composeBom)
    androidTestImplementation(composeBom)
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.navigation:navigation-compose:2.7.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.7")
    implementation("androidx.core:core-ktx:1.13.1")
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    testImplementation("junit:junit:4.13.2")
    // 单测跑在 JVM 上，android.jar 里那个 org.json 是不做事的桩，要一份真的
    testImplementation("org.json:json:20240303")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
}

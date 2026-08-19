import com.android.build.api.variant.FilterConfiguration.FilterType.ABI
import com.android.build.gradle.tasks.MergeSourceSetFolders
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

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
            useLegacyPackaging = true
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
    implementation(fileTree(mapOf("dir" to fclLibs, "include" to listOf("*.aar"))))
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
    testImplementation("org.json:json:20240303")
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.1")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
}

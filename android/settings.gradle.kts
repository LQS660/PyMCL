pluginManagement {
    repositories {
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/gradle-plugin") }
        maven { url = uri("https://maven.aliyun.com/repository/central") }
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/central") }
        maven { url = uri("https://maven.aliyun.com/repository/public") }
        google()
        mavenCentral()
        maven("https://jitpack.io")
    }
}

rootProject.name = "PyMCL"
include(":app")

// FCL 与 Terracotta 是源码依赖的子工程，不在 Maven 上。
// 这个仓库里没有 FoldCraftLauncher 的副本，所以相对路径解析不到时
// 退回到这台机器上那一份——两条路都试，换机器时只要改后面那个常量。
include(":FCLauncher")
val fclLauncher = file("../FoldCraftLauncher/FCLauncher")
project(":FCLauncher").projectDir =
    if (fclLauncher.resolve("build.gradle.kts").isFile) fclLauncher
    else file("D:/pymcl-work/FoldCraftLauncher/FCLauncher")

include(":Terracotta")
val terracotta = file("../FoldCraftLauncher/Terracotta")
project(":Terracotta").projectDir =
    if (terracotta.resolve("build.gradle.kts").isFile) terracotta
    else file("D:/pymcl-work/FoldCraftLauncher/Terracotta")

// FCLCore 是上游写好的那批安装器（Forge / NeoForge / Fabric / Quilt / OptiFine /
// LiteLoader / Cleanroom，外加五种整合包格式）。它依赖 ZipFileSystem，
// 所以两个必须一起 include，缺一个 FCLCore 自己就配置不起来。
include(":FCLCore")
val fclCore = file("../FoldCraftLauncher/FCLCore")
project(":FCLCore").projectDir =
    if (fclCore.resolve("build.gradle.kts").isFile) fclCore
    else file("D:/pymcl-work/FoldCraftLauncher/FCLCore")

include(":ZipFileSystem")
val zipFileSystem = file("../FoldCraftLauncher/ZipFileSystem")
project(":ZipFileSystem").projectDir =
    if (zipFileSystem.resolve("build.gradle.kts").isFile) zipFileSystem
    else file("D:/pymcl-work/FoldCraftLauncher/ZipFileSystem")

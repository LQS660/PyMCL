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
include(":FCLauncher")
val fclLauncher = file("../FoldCraftLauncher/FCLauncher")
project(":FCLauncher").projectDir =
    if (fclLauncher.resolve("build.gradle.kts").isFile) fclLauncher
    else file("D:/pymcl-work/FoldCraftLauncher/FCLauncher")


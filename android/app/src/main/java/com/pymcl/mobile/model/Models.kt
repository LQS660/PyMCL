package com.pymcl.mobile.model

data class VersionRow(
    val id: String,
    val type: String,
    val url: String,
    val sha1: String = "",
    val releaseTime: String = "",
)

data class InstanceInfo(
    val name: String,
    val versions: List<String>,
    val path: String,
)

data class CatalogHit(
    val name: String,
    val slug: String,
    val description: String,
    val downloads: Long,
    val source: String,
    val author: String = "",
    val projectId: String = "",
)

data class AccountInfo(
    val name: String,
    val type: String,
    val uuid: String = "",
    val accessToken: String = "",
    val refreshToken: String = "",
    val api: String = "",
)

data class TaskInfo(
    val id: String,
    val title: String,
    val current: Long = 0,
    val total: Long = 0,
    val message: String = "",
    val done: Boolean = false,
    val success: Boolean = true,
    val log: List<String> = emptyList(),
)

data class LaunchPlan(
    val instance: String,
    val version: String,
    val mainClass: String,
    val classpath: List<String>,
    val gameArgs: List<String>,
    val jvmArgs: List<String>,
    val missing: List<String>,
    val nativesMissing: Boolean,
    val gameDir: String = "",
)

data class DeviceCode(
    val deviceCode: String,
    val userCode: String,
    val uri: String,
    val interval: Int,
    val expiresIn: Int,
)

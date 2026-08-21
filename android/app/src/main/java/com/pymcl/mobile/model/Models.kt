package com.pymcl.mobile.model

import java.io.File

data class PyMclConfig(
    val defaultInstanceId: String? = null,
    val lastVersionId: String? = null,
)

data class Account(
    val id: String,
    val username: String,
    val uuid: String? = null,
    val accessToken: String? = null,
    val deviceCode: String? = null,
)

data class GameInstance(
    val id: String,
    val name: String,
    val versionId: String,
    val gameDir: File,
    val createdAt: Long = System.currentTimeMillis(),
)

data class VersionManifest(
    val latestRelease: String,
    val latestSnapshot: String,
    val versions: List<VersionEntry>,
)

data class VersionEntry(
    val id: String,
    val type: String,
    val url: String,
    val releaseTime: String,
)

data class DownloadTask(
    val id: String,
    val label: String,
    val progress: Float = 0f,
    val status: DownloadStatus = DownloadStatus.Pending,
)

enum class DownloadStatus {
    Pending,
    Running,
    Completed,
    Failed,
}

data class ModSearchResult(
    val projectId: String,
    val slug: String,
    val title: String,
    val description: String,
    val downloads: Long = 0,
)

data class LaunchPlan(
    val instanceId: String,
    val versionId: String,
    val classpath: List<String> = emptyList(),
    val mainClass: String? = null,
    val ready: Boolean = false,
    val message: String = "运行时里程碑后续接入",
)

data class AiMessage(
    val role: String,
    val content: String,
    val timestamp: Long = System.currentTimeMillis(),
)

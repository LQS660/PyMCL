package com.pymcl.mobile.data

import android.content.Context
import com.pymcl.mobile.model.DownloadStatus
import com.pymcl.mobile.model.DownloadTask
import com.pymcl.mobile.model.GameInstance
import com.pymcl.mobile.model.LaunchPlan
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class LaunchPlanner(
    private val context: Context,
    private val manifestRepo: ManifestRepo = ManifestRepo(context),
    private val instanceStore: InstanceStore = InstanceStore(context),
) {
    private val _tasks = MutableStateFlow<List<DownloadTask>>(emptyList())
    val tasks: StateFlow<List<DownloadTask>> = _tasks.asStateFlow()

    suspend fun planLaunch(instance: GameInstance): LaunchPlan {
        val manifest = manifestRepo.readCached()
        val versionKnown = manifest?.versions?.any { it.id == instance.versionId } == true
        return LaunchPlan(
            instanceId = instance.id,
            versionId = instance.versionId,
            classpath = emptyList(),
            mainClass = null,
            ready = false,
            message = if (versionKnown) {
                "版本 ${instance.versionId} 已识别；GL/JNI 运行时将在后续里程碑接入。"
            } else {
                "版本 ${instance.versionId} 未缓存；请先于下载页拉取清单。"
            },
        )
    }

    fun enqueueDownload(label: String): DownloadTask {
        val task = DownloadTask(
            id = System.currentTimeMillis().toString(),
            label = label,
            progress = 0f,
            status = DownloadStatus.Pending,
        )
        _tasks.value = _tasks.value + task
        return task
    }

    fun updateTask(taskId: String, progress: Float, status: DownloadStatus) {
        _tasks.value = _tasks.value.map { task ->
            if (task.id == taskId) task.copy(progress = progress, status = status) else task
        }
    }

    fun clearCompleted() {
        _tasks.value = _tasks.value.filter { it.status != DownloadStatus.Completed }
    }
}

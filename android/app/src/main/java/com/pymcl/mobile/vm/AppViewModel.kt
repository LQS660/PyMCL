package com.pymcl.mobile.vm

import android.app.Application
import android.os.SystemClock
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.pymcl.mobile.data.AiRepo
import com.pymcl.mobile.data.AuthRepo
import com.pymcl.mobile.data.CatalogRepo
import com.pymcl.mobile.data.GameRuntime
import com.pymcl.mobile.data.HttpException
import com.pymcl.mobile.data.InstallCancelled
import com.pymcl.mobile.data.Installer
import com.pymcl.mobile.data.InstanceStore
import com.pymcl.mobile.data.LaunchPlanner
import com.pymcl.mobile.data.ManifestRepo
import com.pymcl.mobile.data.McLaunch
import com.pymcl.mobile.data.Names
import com.pymcl.mobile.data.Paths
import com.pymcl.mobile.model.CatalogHit
import com.pymcl.mobile.model.DeviceCode
import com.pymcl.mobile.model.InstanceInfo
import com.pymcl.mobile.model.TaskInfo
import com.pymcl.mobile.model.VersionRow
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.util.ArrayDeque

class AppViewModel(app: Application) : AndroidViewModel(app) {
    var tab by mutableIntStateOf(0)
    var downloadTab by mutableStateOf("原版游戏")
    var status by mutableStateOf("就绪")
    var log by mutableStateOf("PyMCL Android")
    var progress by mutableIntStateOf(0)
    var busy by mutableStateOf(false)

    var instances = mutableStateListOf<InstanceInfo>()
    var versions = mutableStateListOf<VersionRow>()
    var installed = mutableStateListOf<String>()
    var catalog = mutableStateListOf<CatalogHit>()
    var tasks = mutableStateListOf<TaskInfo>()
    var accounts = mutableStateListOf<String>()

    var instance by mutableStateOf("default")
    var versionId by mutableStateOf("")
    var username by mutableStateOf("Player")
    var memoryMb by mutableIntStateOf(2048)
    var account by mutableStateOf("离线")
    var query by mutableStateOf("")
    var onlyRelease by mutableStateOf(true)
    var aiInput by mutableStateOf("")
    var aiOut by mutableStateOf("公益助手已接通，直接发消息。")
    var aiUrl by mutableStateOf("")
    var roomCode by mutableStateOf("")
    var skinApi by mutableStateOf("https://littleskin.cn/api/yggdrasil")
    var skinUser by mutableStateOf("")
    var skinPw by mutableStateOf("")
    var device by mutableStateOf<DeviceCode?>(null)
    var error by mutableStateOf<String?>(null)
    var runtimePkg by mutableStateOf<String?>(null)
    var aiBusy by mutableStateOf(false)

    private var pollJob: Job? = null
    private var persistJob: Job? = null
    private var logJob: Job? = null
    private var seq = 0
    private var lastProgAt = 0L
    private val logLines = ArrayDeque<String>(48)

    init {
        viewModelScope.launch(Dispatchers.IO) {
            InstanceStore.ensureDefault()
            val cfg = InstanceStore.loadConfig()
            withContext(Dispatchers.Main) {
                username = cfg.optString("username", "Player")
                memoryMb = cfg.optInt("memory_mb", 2048)
                aiUrl = cfg.optString("ai_url", "")
                runtimePkg = GameRuntime.installed(getApplication())
                refreshLocal()
            }
            runCatching { reloadVersions() }
        }
    }

    fun append(line: String) {
        synchronized(logLines) {
            if (logLines.size >= 40) logLines.removeFirst()
            logLines.addLast(line)
        }
        status = line
        logJob?.cancel()
        logJob = viewModelScope.launch {
            delay(80)
            log = synchronized(logLines) { logLines.joinToString("\n") }
        }
    }

    fun refreshLocal() {
        instances.clear()
        instances.addAll(InstanceStore.list())
        if (instances.none { it.name == instance }) {
            instance = instances.firstOrNull()?.name ?: "default"
        }
        installed.clear()
        installed.addAll(InstanceStore.installedVersions(instance))
        if (versionId.isBlank()) versionId = Names.pickDefaultVersion(versions.toList(), installed.toList())
        accounts.clear()
        accounts.addAll(AuthRepo.accounts().map { if (it.type == "offline") "离线" else it.name })
        if (account !in accounts) account = accounts.firstOrNull() ?: "离线"
        runtimePkg = GameRuntime.installed(getApplication())
    }

    fun persistUiDebounced() {
        persistJob?.cancel()
        persistJob = viewModelScope.launch {
            delay(400)
            persistUi()
        }
    }

    fun persistUi() {
        viewModelScope.launch(Dispatchers.IO) {
            val cfg = InstanceStore.loadConfig()
            cfg.put("username", username)
            cfg.put("memory_mb", memoryMb)
            cfg.put("ai_url", aiUrl)
            InstanceStore.saveConfig(cfg)
        }
    }

    fun selectInstance(name: String) {
        instance = name
        refreshLocal()
    }

    fun reloadVersions(force: Boolean = false) {
        viewModelScope.launch {
            error = null
            append("拉取版本清单…")
            try {
                val rows = withContext(Dispatchers.IO) { ManifestRepo.fetch(force) }
                versions.clear()
                versions.addAll(rows)
                append("版本清单 ${rows.size} 条")
                if (versionId.isBlank() || versions.none { it.id == versionId }) {
                    versionId = Names.pickDefaultVersion(rows, installed.toList())
                }
            } catch (e: Exception) {
                error = e.message
                append("清单失败: ${e.message}")
            }
        }
    }

    fun filteredVersions(): List<VersionRow> {
        val q = query.trim()
        return versions.asSequence()
            .filter {
                (!onlyRelease || it.type == "release") &&
                    (q.isEmpty() || it.id.contains(q, true) || it.type.contains(q, true))
            }
            .take(80)
            .toList()
    }

    fun createInstance(name: String) {
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { InstanceStore.create(name) }
                .onFailure { error = it.message }
            withContext(Dispatchers.Main) { refreshLocal() }
        }
    }

    fun deleteInstance(name: String) {
        viewModelScope.launch(Dispatchers.IO) {
            InstanceStore.delete(name)
            InstanceStore.ensureDefault()
            withContext(Dispatchers.Main) { refreshLocal() }
        }
    }

    fun installSelected() {
        val row = versions.firstOrNull { it.id == versionId } ?: return
        startTask("安装 ${row.id}") { id ->
            Installer.installVanilla(instance, row, { cur, total, msg ->
                progressFor(id, cur, total, msg)
            }, { line ->
                viewModelScope.launch(Dispatchers.Main) {
                    append(line)
                    logTask(id, line)
                }
            })
            withContext(Dispatchers.Main) { refreshLocal() }
        }
    }

    fun searchCatalog() {
        val kind = downloadTab
        viewModelScope.launch {
            busy = true
            error = null
            try {
                val rows = withContext(Dispatchers.IO) {
                    if (kind == "原版游戏") emptyList()
                    else CatalogRepo.searchKind(kind, query)
                }
                catalog.clear()
                catalog.addAll(rows)
                append("搜索 $kind 「$query」 ${rows.size} 条")
            } catch (e: Exception) {
                error = e.message
                append("搜索失败: ${e.message}")
            } finally {
                busy = false
            }
        }
    }

    fun launchGame() {
        persistUi()
        val vid = versionId
        val inst = instance
        val user = username
        val mem = memoryMb
        if (vid.isBlank()) {
            error = "先选版本"
            return
        }
        val known = versions.toList()
        startTask("启动 $vid") { id ->
            var row = known.firstOrNull { it.id == vid }
            var plan = LaunchPlanner.plan(inst, vid, user, mem)
            if (plan.missing.isNotEmpty()) {
                if (row == null) {
                    val rows = ManifestRepo.fetch(false)
                    row = rows.firstOrNull { it.id == vid }
                    withContext(Dispatchers.Main) {
                        if (versions.isEmpty()) {
                            versions.addAll(rows)
                        }
                    }
                }
                if (row == null) throw HttpException("清单没有 $vid，去下载页刷新")
                withContext(Dispatchers.Main) { append("缺 ${plan.missing.size} 个文件，开始安装 $vid") }
                Installer.installVanilla(inst, row, { cur, total, msg ->
                    progressFor(id, cur, total, msg)
                }, { line ->
                    viewModelScope.launch(Dispatchers.Main) {
                        append(line)
                        logTask(id, line)
                    }
                })
                plan = LaunchPlanner.plan(inst, vid, user, mem)
            }
            if (plan.missing.isNotEmpty()) {
                throw HttpException("安装后仍缺 ${plan.missing.size} 个文件")
            }
            val planFile = File(Paths.instanceDir(inst), "pymcl-launch-plan.json")
            planFile.writeText(
                JSONObject()
                    .put("mainClass", plan.mainClass)
                    .put("version", plan.version)
                    .put("nativesMissing", plan.nativesMissing)
                    .put("classpathCount", plan.classpath.size)
                    .toString(2),
            )
            withContext(Dispatchers.Main) {
                refreshLocal()
                append(LaunchPlanner.describe(plan))
                append("启动计划已写入 ${planFile.name}")
                append("文件齐全，开始解压运行时并进游戏")
            }
            val ctx = getApplication<Application>()
            McLaunch.prepare(ctx, inst, vid, user, mem) { line ->
                viewModelScope.launch(Dispatchers.Main) {
                    append(line)
                    logTask(id, line)
                }
            }
            withContext(Dispatchers.Main) {
                runtimePkg = GameRuntime.installed(ctx)
                McLaunch.open(ctx)
                append("已打开游戏画面")
            }
        }
    }

    fun sendAi() {
        val text = aiInput.trim()
        if (text.isEmpty() || aiBusy) return
        aiInput = ""
        viewModelScope.launch {
            aiBusy = true
            aiOut += "\n你: $text"
            try {
                val reply = withContext(Dispatchers.IO) { AiRepo.send(aiUrl, text) }
                aiOut += "\n助手: $reply"
            } catch (e: Exception) {
                aiOut += "\n助手: 失败 ${e.message}"
            } finally {
                aiBusy = false
            }
        }
    }

    fun loginAuthlib() {
        viewModelScope.launch {
            try {
                val name = withContext(Dispatchers.IO) {
                    AuthRepo.loginAuthlib(skinApi, skinUser, skinPw).optString("name")
                }
                append("皮肤站已登录 $name")
                refreshLocal()
            } catch (e: Exception) {
                error = e.message
                append("皮肤站登录失败: ${e.message}")
            }
        }
    }

    fun startMsLogin() {
        viewModelScope.launch {
            try {
                val code = withContext(Dispatchers.IO) { AuthRepo.startDeviceCode() }
                device = code
                append("微软登录码 ${code.userCode} → ${code.uri}")
                pollJob?.cancel()
                pollJob = viewModelScope.launch(Dispatchers.IO) {
                    repeat(code.expiresIn / code.interval.coerceAtLeast(5)) {
                        delay(code.interval.coerceAtLeast(5) * 1000L)
                        val tok = runCatching { AuthRepo.pollOnce(code.deviceCode) }.getOrNull()
                        if (tok != null) {
                            val name = tok.optString("name", "Microsoft")
                            AuthRepo.saveMicrosoft(
                                name.ifBlank { "Microsoft" },
                                tok.optString("access_token"),
                                tok.optString("refresh_token"),
                            )
                            withContext(Dispatchers.Main) {
                                device = null
                                append("微软登录令牌已保存（Xbox/MC 换票在下一里程碑）")
                                refreshLocal()
                            }
                            return@launch
                        }
                    }
                }
            } catch (e: Exception) {
                error = e.message
                append("登录失败: ${e.message}")
            }
        }
    }

    fun cancelTask() {
        Installer.cancelled = true
        busy = false
        append("已请求取消")
    }

    private fun startTask(title: String, block: suspend (String) -> Unit) {
        val id = "task-${++seq}"
        tasks.add(0, TaskInfo(id, title, message = "开始"))
        viewModelScope.launch {
            busy = true
            error = null
            try {
                withContext(Dispatchers.IO) { block(id) }
                updateTask(id) { it.copy(done = true, success = true, message = "完成") }
                append("$title 完成")
            } catch (e: InstallCancelled) {
                updateTask(id) { it.copy(done = true, success = false, message = "已取消") }
            } catch (e: Exception) {
                error = e.message
                updateTask(id) { it.copy(done = true, success = false, message = e.message ?: "失败") }
                append("$title 失败: ${e.message}")
            } finally {
                busy = false
                progress = 0
            }
        }
    }

    private fun progressFor(id: String, cur: Long, total: Long, msg: String) {
        val pct = if (total > 0) ((cur * 100) / total).toInt().coerceIn(0, 100) else 0
        val now = SystemClock.uptimeMillis()
        if (pct < 100 && now - lastProgAt < 80) return
        lastProgAt = now
        viewModelScope.launch(Dispatchers.Main.immediate) {
            progress = pct
            status = msg
            updateTask(id) { it.copy(current = cur, total = total, message = msg) }
        }
    }

    private fun logTask(id: String, line: String) {
        updateTask(id) { it.copy(log = (it.log + line).takeLast(40)) }
    }

    private fun updateTask(id: String, fn: (TaskInfo) -> TaskInfo) {
        val i = tasks.indexOfFirst { it.id == id }
        if (i >= 0) tasks[i] = fn(tasks[i])
    }

}

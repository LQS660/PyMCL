package com.pymcl.mobile.vm

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import com.pymcl.mobile.data.DocumentImport
import kotlinx.coroutines.CancellationException
import android.content.Intent
import android.os.SystemClock
import com.pymcl.mobile.JvmHostActivity
import com.pymcl.mobile.data.JvmHost
import com.pymcl.mobile.data.JvmJob
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.pymcl.mobile.data.CatalogFiles
import com.pymcl.mobile.data.CatalogKeys
import com.pymcl.mobile.data.CatalogKinds
import com.pymcl.mobile.data.CatalogRepo
import com.pymcl.mobile.data.CatalogSpec
import com.pymcl.mobile.data.ContentEntry
import com.pymcl.mobile.data.ContentExport
import com.pymcl.mobile.data.ContentLibrary
import com.pymcl.mobile.data.CatalogSource
import com.pymcl.mobile.data.ContentInstall
import com.pymcl.mobile.data.FileKind
import com.pymcl.mobile.data.FileKinds
import com.pymcl.mobile.data.GameRuntime
import com.pymcl.mobile.data.GlobalMods
import com.pymcl.mobile.data.Http
import com.pymcl.mobile.data.HttpPackDownloader
import com.pymcl.mobile.data.InstallCancelled
import com.pymcl.mobile.data.Installer
import com.pymcl.mobile.data.InstanceStore
import com.pymcl.mobile.data.LaunchPlanner
import com.pymcl.mobile.data.Lan
import com.pymcl.mobile.data.Loader
import com.pymcl.mobile.data.LoaderBuild
import com.pymcl.mobile.data.LoaderInstall
import com.pymcl.mobile.data.ManifestRepo
import com.pymcl.mobile.data.McLaunch
import com.pymcl.mobile.data.ModUpdate
import com.pymcl.mobile.data.ModUpdates
import com.pymcl.mobile.data.ModpackExport
import com.pymcl.mobile.data.ModpackIndex
import com.pymcl.mobile.data.ModpackInfo
import com.pymcl.mobile.data.ModpackInstall
import com.pymcl.mobile.data.ModpackRefs
import com.pymcl.mobile.data.Mods
import com.pymcl.mobile.data.CatalogFavorites
import com.pymcl.mobile.data.FavoriteItem
import com.pymcl.mobile.data.NewsItem
import com.pymcl.mobile.data.NewsRepo
import com.pymcl.mobile.data.ServerPing
import com.pymcl.mobile.data.ServerStatus
import com.pymcl.mobile.data.Names
import com.pymcl.mobile.data.CrashAction
import com.pymcl.mobile.data.CrashActionResult
import com.pymcl.mobile.data.CrashActions
import com.pymcl.mobile.data.CrashReport
import com.pymcl.mobile.data.DirectConnect
import com.pymcl.mobile.data.Paths
import com.pymcl.mobile.data.Playtime
import com.pymcl.mobile.data.Preflight
import com.pymcl.mobile.data.PreflightItem
import com.pymcl.mobile.data.PreflightResult
import com.pymcl.mobile.data.Saves
import com.pymcl.mobile.data.Servers
import com.pymcl.mobile.data.TaskCenter
import com.pymcl.mobile.data.Terracotta
import com.pymcl.mobile.data.TerracottaCore
import com.pymcl.mobile.data.TextFetcher
import com.pymcl.mobile.data.VersionOps
import com.pymcl.mobile.data.VersionSetting
import com.pymcl.mobile.data.VersionSettings
import com.pymcl.mobile.model.BackupEntry
import com.pymcl.mobile.model.CatalogHit
import com.pymcl.mobile.model.InstanceInfo
import com.pymcl.mobile.model.MediaEntry
import com.pymcl.mobile.model.ModEntry
import com.pymcl.mobile.model.ModTarget
import com.pymcl.mobile.model.PlaytimeStat
import com.pymcl.mobile.model.SaveEntry
import com.pymcl.mobile.model.ServerEntry
import com.pymcl.mobile.model.TaskInfo
import com.pymcl.mobile.model.VersionCard
import com.pymcl.mobile.model.VersionRow
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.ArrayDeque

class AppViewModel(app: Application) : AndroidViewModel(app) {
    var tab by mutableIntStateOf(0)
    var downloadTab by mutableStateOf(CatalogRepo.KINDS.first())
    var status by mutableStateOf("就绪")
    var log by mutableStateOf("PyMCL Android")
    var progress by mutableIntStateOf(0)
    var busy by mutableStateOf(false)
    var error by mutableStateOf<String?>(null)

    var instances = mutableStateListOf<InstanceInfo>()
    var versions = mutableStateListOf<VersionRow>()
    var installed = mutableStateListOf<String>()
    var catalog = mutableStateListOf<CatalogHit>()
    var tasks = mutableStateListOf<TaskInfo>()

    var versionCards = mutableStateListOf<VersionCard>()
    var mods = mutableStateListOf<ModEntry>()
    var modTargets = mutableStateListOf<ModTarget>()
    var servers = mutableStateListOf<ServerEntry>()
    var saves = mutableStateListOf<SaveEntry>()
    var backups = mutableStateListOf<BackupEntry>()
    var media = mutableStateListOf<MediaEntry>()
    var playtime by mutableStateOf<Map<String, PlaytimeStat>>(emptyMap())

    var instance by mutableStateOf("default")
    var versionId by mutableStateOf("")
    var username by mutableStateOf("Player")
    var memoryMb by mutableIntStateOf(2048)
    var query by mutableStateOf("")
    var onlyRelease by mutableStateOf(true)
    var showHidden by mutableStateOf(false)
    var modQuery by mutableStateOf("")
    var modTarget by mutableStateOf("")
    var saveKind by mutableStateOf(SAVE_KINDS.first())
    var roomCode by mutableStateOf("")
    var lanPort by mutableIntStateOf(Lan.DEFAULT_PORT)
    var pendingModpack by mutableStateOf<ModpackInfo?>(null)
    var runtimePkg by mutableStateOf<String?>(null)

    private var persistJob: Job? = null
    private var logJob: Job? = null
    private var seq = 0
    private var lastProgAt = 0L
    private var lastPct = -1
    private val logLines = ArrayDeque<String>(LOG_LIMIT)

    /** 当前实例目录；所有仓储都按它取数，换实例只改这一处。 */
    val instDir: File get() = Paths.instanceDir(instance)

    /** 游戏真正读写的目录：选了版本且开了隔离时落在版本目录里。 */
    val gameDir: File
        get() = if (versionId.isBlank()) instDir else VersionSettings.gameDir(instDir, versionId)

    init {
        viewModelScope.launch(Dispatchers.IO) {
            InstanceStore.ensureDefault()
            val cfg = InstanceStore.loadConfig()
            val user = cfg.optString("username", "Player")
            val mem = cfg.optInt("memory_mb", 2048)
            val hidden = cfg.optBoolean("show_hidden_versions", false)
            val runtime = GameRuntime.installed()
            withContext(Dispatchers.Main) {
                username = user
                memoryMb = mem
                showHidden = hidden
                runtimePkg = runtime
                refreshLocal()
            }
            runCatching { reloadVersions() }
        }
    }

    // ---- 日志与任务 ------------------------------------------------------

    /**
     * 追加一行日志。日志用定长环形缓冲装着，并且**只在 80ms 静默后**才拼一次整串——
     * 安装整合包时日志能一秒刷上百行，每行都拼一次几十 KB 的字符串会直接卡住主线程。
     */
    fun append(line: String) {
        synchronized(logLines) {
            if (logLines.size >= LOG_LIMIT) logLines.removeFirst()
            logLines.addLast(line)
        }
        status = line
        logJob?.cancel()
        logJob = viewModelScope.launch {
            delay(LOG_DEBOUNCE_MS)
            log = synchronized(logLines) { logLines.joinToString("\n") }
        }
    }

    fun cancelTask() {
        Installer.cancelled = true
        busy = false
        append("已请求取消")
    }

    fun clearFinishedTasks() {
        val kept = TaskCenter.clearFinished(tasks.toList())
        tasks.clear()
        tasks.addAll(kept)
    }

    val activeDownloads: Int get() = TaskCenter.activeCount(tasks.toList())

    private fun startTask(title: String, block: suspend (String) -> Unit) {
        val id = "task-${++seq}"
        tasks.add(0, TaskInfo(id, title, message = "开始"))
        viewModelScope.launch {
            busy = true
            error = null
            Installer.cancelled = false
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
                lastPct = -1
            }
        }
    }

    /**
     * 进度回调。安装器每收到一个网络分片就回调一次，一秒能上千次；
     * 这里按 80ms 节流，并且**百分比没变就整个跳过**——否则每一次回调都触发一轮重组。
     */
    private fun progressFor(id: String, cur: Long, total: Long, msg: String) {
        val pct = TaskCenter.percent(cur, total)
        val now = SystemClock.uptimeMillis()
        if (pct == lastPct && pct < 100) return
        if (pct < 100 && now - lastProgAt < PROGRESS_THROTTLE_MS) return
        lastProgAt = now
        lastPct = pct
        viewModelScope.launch(Dispatchers.Main.immediate) {
            progress = pct
            status = msg
            updateTask(id) { it.copy(current = cur, total = total, message = msg) }
        }
    }

    private fun logTask(id: String, line: String) {
        updateTask(id) { TaskCenter.appendLog(it, line) }
    }

    private fun updateTask(id: String, fn: (TaskInfo) -> TaskInfo) {
        val i = tasks.indexOfFirst { it.id == id }
        if (i >= 0) tasks[i] = fn(tasks[i])
    }

    private fun onMainLog(id: String): (String) -> Unit = { line ->
        viewModelScope.launch(Dispatchers.Main) {
            append(line)
            logTask(id, line)
        }
    }

    // ---- 实例与版本 ------------------------------------------------------

    fun refreshLocal() {
        instances.clear()
        instances.addAll(InstanceStore.list())
        if (instances.none { it.name == instance }) {
            instance = instances.firstOrNull()?.name ?: "default"
        }
        installed.clear()
        installed.addAll(InstanceStore.installedVersions(instance))
        if (versionId.isBlank() || versionId !in installed) {
            versionId = Names.pickDefaultVersion(versions.toList(), installed.toList())
        }
        runtimePkg = GameRuntime.installed()
        reloadVersionCards()
    }

    fun selectInstance(name: String) {
        instance = name
        refreshLocal()
    }

    fun createInstance(name: String) {
        viewModelScope.launch(Dispatchers.IO) {
            val created = runCatching { InstanceStore.create(name) }.getOrElse {
                withContext(Dispatchers.Main) { error = it.message }
                null
            }
            withContext(Dispatchers.Main) {
                created?.let { instance = it.name }
                refreshLocal()
            }
        }
    }

    fun deleteInstance(name: String) {
        viewModelScope.launch(Dispatchers.IO) {
            InstanceStore.delete(name)
            InstanceStore.ensureDefault()
            withContext(Dispatchers.Main) { refreshLocal() }
        }
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
            .take(VERSION_PAGE)
            .toList()
    }

    fun installSelected() {
        val row = versions.firstOrNull { it.id == versionId } ?: return
        startTask("安装游戏 ${row.id}") { id ->
            Installer.installVanilla(
                instance,
                row,
                { cur, total, msg -> progressFor(id, cur, total, msg) },
                onMainLog(id),
            )
            withContext(Dispatchers.Main) { refreshLocal() }
        }
    }

    // ---- 版本管理 --------------------------------------------------------

    fun reloadVersionCards() {
        val dir = instDir
        val hidden = showHidden
        viewModelScope.launch(Dispatchers.IO) {
            val rows = runCatching { VersionOps.cards(dir, hidden) }.getOrDefault(emptyList())
            withContext(Dispatchers.Main) {
                versionCards.clear()
                versionCards.addAll(rows)
            }
        }
    }

    fun updateShowHidden(on: Boolean) {
        showHidden = on
        persistUiDebounced()
        reloadVersionCards()
    }

    fun toggleIsolation(version: String, isolated: Boolean, seed: Boolean) {
        val dir = instDir
        viewModelScope.launch(Dispatchers.IO) {
            runCatching {
                val mode = if (isolated) VersionSettings.ISOLATED_DEFAULT else VersionSettings.NONE
                VersionSettings.setIsolation(dir, version, mode, seed)
            }.onFailure { withContext(Dispatchers.Main) { error = it.message } }
            withContext(Dispatchers.Main) {
                append("「$version」已切到 ${if (isolated) "独立" else "大锅饭"}")
                reloadVersionCards()
                reloadMods()
            }
        }
    }

    fun setIsolationMode(version: String, mode: String, seed: Boolean) {
        val dir = instDir
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { VersionSettings.setIsolation(dir, version, mode, seed) }
                .onFailure { withContext(Dispatchers.Main) { error = it.message } }
            withContext(Dispatchers.Main) {
                append("「$version」隔离档位 ${VersionSettings.LABELS[mode]}")
                reloadVersionCards()
            }
        }
    }

    fun renameVersion(version: String, newId: String) = versionAction("重命名") {
        VersionOps.rename(instDir, version, newId)
    }

    fun copyVersion(version: String, newId: String) = versionAction("复制") {
        VersionOps.copy(instDir, version, newId)
    }

    fun toggleVersionHidden(version: String) = versionAction("隐藏") {
        VersionOps.toggleHidden(instDir, version)
    }

    fun uninstallVersion(version: String) = versionAction("卸载") {
        VersionOps.uninstall(instDir, version)
    }

    private fun versionAction(what: String, block: () -> Unit) {
        viewModelScope.launch(Dispatchers.IO) {
            val failure = runCatching(block).exceptionOrNull()
            withContext(Dispatchers.Main) {
                if (failure != null) {
                    error = failure.message
                    append("$what 失败: ${failure.message}")
                } else {
                    append("$what 完成")
                }
                refreshLocal()
            }
        }
    }

    fun repairVersion(version: String) {
        startTask("安装游戏 $version（修复）") { id ->
            val missing = VersionOps.missingFiles(instDir, version)
            if (missing.isEmpty()) {
                onMainLog(id)("「$version」文件齐全，无需修复")
                return@startTask
            }
            onMainLog(id)("缺 ${missing.size} 个文件，重新下载 $version")
            val row = versions.firstOrNull { it.id == version }
                ?: ManifestRepo.fetch(false).firstOrNull { it.id == version }
                ?: throw IllegalStateException("清单里没有 $version")
            Installer.installVanilla(
                instance,
                row,
                { cur, total, msg -> progressFor(id, cur, total, msg) },
                onMainLog(id),
            )
            withContext(Dispatchers.Main) { refreshLocal() }
        }
    }

    fun exportLaunchScript(version: String): String =
        VersionOps.launchScript(instDir, version, username, memoryMb)

    // ---- 模组 ------------------------------------------------------------

    fun reloadMods() {
        val dir = instDir
        val target = modTarget
        viewModelScope.launch(Dispatchers.IO) {
            val targets = Mods.targets(dir)
            val rows = Mods.list(dir, target)
            withContext(Dispatchers.Main) {
                modTargets.clear()
                modTargets.addAll(targets)
                if (modTargets.none { it.value == modTarget }) modTarget = ""
                mods.clear()
                mods.addAll(rows)
            }
        }
    }

    fun selectModTarget(value: String) {
        modTarget = value
        reloadMods()
    }

    /** 过滤只碰内存里那份列表，不再回盘——用户每敲一个字都重新 listFiles 会明显掉帧。 */
    fun filteredMods(): List<ModEntry> = Mods.filter(mods.toList(), modQuery)

    fun modsSummary(): String = Mods.summary(mods.toList())

    fun setModEnabled(filename: String, enabled: Boolean) = libraryAction { _, dir, version ->
        Mods.setEnabled(dir, filename, enabled, version)
    }

    fun deleteMod(filename: String) = modAction {
        Mods.delete(instDir, filename, modTarget)
    }

    fun importMod(src: File) = modAction {
        Mods.install(instDir, src, modTarget)
    }

    fun exportMod(filename: String, destDir: File) = modAction {
        Mods.export(instDir, filename, destDir, modTarget)
    }

    // ---- 全局（共享）模组池 -----------------------------------------------

    var globalMods = mutableStateListOf<ModEntry>()

    /** 会吃到共享池的已装版本，页面拿它说清「对谁生效」。 */
    var globalModVersions = mutableStateListOf<String>()

    fun reloadGlobalMods() {
        val dir = instDir
        viewModelScope.launch(Dispatchers.IO) {
            val rows = GlobalMods.list(dir)
            val consumers = GlobalMods.consumers(dir)
            withContext(Dispatchers.Main) {
                globalMods.clear()
                globalMods.addAll(rows)
                globalModVersions.clear()
                globalModVersions.addAll(consumers)
            }
        }
    }

    fun setGlobalModEnabled(filename: String, enabled: Boolean) = globalModAction {
        GlobalMods.setEnabled(instDir, filename, enabled)
    }

    fun deleteGlobalMod(filename: String) = globalModAction {
        GlobalMods.delete(instDir, filename)
    }

    /**
     * 往共享池里放一个 jar。桌面那边是打开 `shared/mods` 让人自己拖进去，
     * 手机上共享池在应用私有目录里、文件管理器进不来，只能从 SAF 选一份复制进去。
     */
    fun importGlobalMod(uri: Uri) {
        val app = getApplication<Application>()
        val dir = instDir
        viewModelScope.launch(Dispatchers.IO) {
            val failure = try {
                val resolver = app.contentResolver
                DocumentImport.consume(app.cacheDir, displayNameOf(uri), Mods.JAR_EXTS,
                    open = { resolver.openInputStream(uri) },
                    consumeFile = { GlobalMods.install(dir, it) })
                null
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (failure: Exception) {
                failure
            }
            withContext(Dispatchers.Main) {
                failure?.let {
                    error = it.message
                    append("全局模组导入失败: ${it.message}")
                }
                reloadGlobalMods()
            }
        }
    }

    private fun globalModAction(block: () -> Unit) {
        viewModelScope.launch(Dispatchers.IO) {
            val failure = runCatching(block).exceptionOrNull()
            withContext(Dispatchers.Main) {
                failure?.let {
                    error = it.message
                    append("全局模组操作失败: ${it.message}")
                }
                reloadGlobalMods()
            }
        }
    }

    // ---- 通用内容库（六类共用） -------------------------------------------

    var libraryTab by mutableStateOf(CatalogKinds.MOD.title)
    var libraryQuery by mutableStateOf("")
    var library = mutableStateListOf<ContentEntry>()

    val librarySpec: CatalogSpec
        get() = CatalogKinds.ALL.firstOrNull { it.title == libraryTab } ?: CatalogKinds.MOD

    fun selectLibraryKind(spec: CatalogSpec) {
        libraryTab = spec.title
        libraryQuery = ""
        reloadLibrary()
    }

    data class LibraryTarget(val dir: File, val spec: CatalogSpec, val version: String)

    fun libraryTarget() = LibraryTarget(instDir, librarySpec,
        if (librarySpec.supportsToggle) modTarget else "")

    private var libraryGeneration = 0L
    private var libraryReloadJob: kotlinx.coroutines.Job? = null

    fun reloadLibrary() {
        val target = libraryTarget()
        val generation = ++libraryGeneration
        libraryReloadJob?.cancel()
        libraryReloadJob = viewModelScope.launch {
            try {
                val (targets, rows, modRows) = withContext(Dispatchers.IO) {
                    Triple(Mods.targets(target.dir),
                        ContentLibrary.list(target.dir, target.version, target.spec),
                        if (target.spec.supportsToggle) Mods.list(target.dir, target.version) else emptyList())
                }
                if (generation != libraryGeneration || target != libraryTarget()) return@launch
                modTargets.clear()
                modTargets.addAll(targets)
                library.clear()
                library.addAll(rows)
                if (target.spec.supportsToggle) {
                    mods.clear()
                    mods.addAll(modRows)
                }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (failure: Exception) {
                if (generation == libraryGeneration && target == libraryTarget()) {
                    library.clear()
                    error = failure.message
                    append("${target.spec.title}读取失败: ${failure.message}")
                }
            }
        }
    }

    fun filteredLibrary(): List<ContentEntry> = ContentLibrary.filter(library.toList(), libraryQuery)

    fun librarySummary(): String = ContentLibrary.summary(library.toList(), librarySpec)

    fun deleteFromLibrary(name: String, target: LibraryTarget = libraryTarget()) = libraryAction(target) { spec, dir, version ->
        ContentLibrary.delete(dir, version, spec, name)
    }

    fun importIntoLibrary(src: File) = libraryAction { spec, dir, version ->
        ContentLibrary.importLocal(dir, version, spec, src)
    }

    /**
     * Android 的系统文件选择器返回 content:// URI，不保证能还原成磁盘路径。
     * 先流式复制到应用缓存，再复用六类内容共同的 importLocal；finally 清掉临时文件。
     * 这样 Android 10+ 的 scoped storage、网盘 provider、Downloads provider 都能用。
     */
    fun importIntoLibrary(uri: Uri, target: LibraryTarget = libraryTarget()) {
        val (dir, spec, version) = target
        val app = getApplication<Application>()
        viewModelScope.launch(Dispatchers.IO) {
            val failure = try {
                val resolver = app.contentResolver
                DocumentImport.consume(app.cacheDir, displayNameOf(uri), spec.extensions,
                    open = { resolver.openInputStream(uri) },
                    consumeFile = { ContentLibrary.importLocal(dir, version, spec, it) })
                null
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (failure: Exception) {
                failure
            }
            withContext(Dispatchers.Main) {
                failure?.let {
                    error = it.message
                    append("${spec.title}导入失败: ${it.message}")
                }
                reloadLibrary()
            }
        }
    }

    fun exportFromLibrary(uri: Uri, name: String, target: LibraryTarget) {
        val resolver = getApplication<Application>().contentResolver
        libraryAction(target) { spec, dir, version ->
            val output = resolver.openOutputStream(uri, "wt") ?: error("无法写入所选位置")
            output.use { ContentExport.write(dir, version, spec, name, it) }
        }
    }

    /**
     * 多选导出。桌面 export_contents 往一个文件夹里逐个落地，安卓的保存选择器只给一个
     * content:// 目标，所以打成一个 zip；跟桌面一样，单项失败不打断其余，只在日志里点名。
     */
    fun exportManyFromLibrary(uri: Uri, names: List<String>, target: LibraryTarget) {
        val resolver = getApplication<Application>().contentResolver
        libraryAction(target) { spec, dir, version ->
            val output = resolver.openOutputStream(uri, "wt") ?: error("无法写入所选位置")
            val result = output.use { ContentExport.writeMany(dir, version, spec, names, it) }
            val skipped = if (result.failed.isEmpty()) {
                ""
            } else {
                "，跳过 ${result.failed.size} 个：" +
                    result.failed.joinToString("；") { "${it.name}（${it.reason}）" }
            }
            append("已导出 ${result.exported.size} 个${spec.title}$skipped")
            // 一个都没导出去 = 这次点击白点了，得让页面红一行，而不是只在日志里
            if (result.exported.isEmpty()) error(result.failed.firstOrNull()?.reason ?: "没有可导出的内容")
        }
    }

    /** provider 给的 content:// 还原不回磁盘路径，文件名只能问 provider 要，问不到就退回末段。 */
    private fun displayNameOf(uri: Uri): String {
        val resolver = getApplication<Application>().contentResolver
        return resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
            ?.use { cursor ->
                val col = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (col >= 0 && cursor.moveToFirst()) cursor.getString(col) else null
            }
            ?.takeIf { it.isNotBlank() }
            ?: uri.lastPathSegment?.substringAfterLast('/')?.takeIf { it.isNotBlank() }
            ?: error("无法识别所选文件名")
    }

    private fun libraryAction(target: LibraryTarget = libraryTarget(), block: (CatalogSpec, File, String) -> Unit) {
        val (dir, spec, version) = target
        viewModelScope.launch(Dispatchers.IO) {
            val failure = try {
                block(spec, dir, version)
                null
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (failure: Exception) { failure }
            withContext(Dispatchers.Main) {
                failure?.let {
                    error = it.message
                    append("${spec.title}操作失败: ${it.message}")
                }
                reloadLibrary()
            }
        }
    }

    // ---- 版本设置 --------------------------------------------------------

    /** 绑定账号那一栏的候选。账号仓储归设置域，这里只读名字。 */
    fun accountNames(): List<String> =
        runCatching { InstanceStore.loadAccounts().mapNotNull { it.optString("name").takeIf { n -> n.isNotBlank() } } }
            .getOrDefault(emptyList())

    fun saveVersionSetting(version: String, setting: VersionSetting, onResult: (Boolean) -> Unit = {}) {
        val dir = instDir
        viewModelScope.launch(Dispatchers.IO) {
            val failure = runCatching {
                VersionSettings.save(dir, version, setting)
                VersionSettings.applyLayout(dir, version, setting)
            }.exceptionOrNull()
            withContext(Dispatchers.Main) {
                if (failure != null) {
                    error = failure.message
                    append("版本设置保存失败: ${failure.message}")
                } else {
                    append("「$version」的版本设置已保存")
                }
                onResult(failure == null)
                reloadVersionCards()
            }
        }
    }

    // ---- Mod 查更新 ------------------------------------------------------

    var modUpdates = mutableStateListOf<ModUpdate>()
    var modUpdateBusy by mutableStateOf(false)
    var modUpdateSummary by mutableStateOf("")

    /** 拿当前选中版本的 MC 版本与加载器去问，这样查到的就是能装上的那一版。 */
    fun checkModUpdates() {
        if (modUpdateBusy) return
        val dir = instDir
        val version = modTarget.ifBlank { versionId }
        val rows = mods.toList()
        viewModelScope.launch {
            modUpdateBusy = true
            modUpdates.clear()
            try {
                val mc = if (version.isBlank()) "" else VersionOps.mcVersionOf(dir, version)
                val loader = if (version.isBlank()) {
                    ""
                } else {
                    VersionOps.loaderOf(LaunchPlanner.resolveJson(dir, version))
                }
                val out = withContext(Dispatchers.IO) {
                    ModUpdates.check(rows, mc, loader, textFetcher)
                }
                modUpdates.addAll(out)
                modUpdateSummary = ModUpdates.summary(out)
                append("检查更新：$modUpdateSummary")
            } catch (e: Exception) {
                error = e.message
                append("检查更新失败: ${e.message}")
            } finally {
                modUpdateBusy = false
            }
        }
    }

    /** 装一个查到的新版。旧的那份先禁用而不是删——新版起不来时还能换回去。 */
    fun applyModUpdate(row: ModUpdate) {
        val file = row.file ?: return
        val dir = instDir
        val target = modTarget
        startTask("安装模组 ${file.path}") { id ->
            ContentInstall.install(
                instDir = dir,
                version = target,
                kind = FileKind.MOD,
                file = file,
                downloader = HttpPackDownloader,
                onProgress = { cur, total -> progressFor(id, cur, total, "下载 ${file.path}") },
            )
            runCatching { Mods.setEnabled(dir, row.entry.filename, false, target) }
                .onFailure { onMainLog(id)("旧版停用失败（新版已装上）：${it.message}") }
            withContext(Dispatchers.Main) {
                modUpdates.remove(row)
                reloadMods()
            }
        }
    }

    private fun modAction(block: () -> Unit) {
        viewModelScope.launch(Dispatchers.IO) {
            val failure = runCatching(block).exceptionOrNull()
            withContext(Dispatchers.Main) {
                failure?.let {
                    error = it.message
                    append("模组操作失败: ${it.message}")
                }
                reloadMods()
            }
        }
    }

    // ---- 整合包 ----------------------------------------------------------

    fun inspectModpack(archive: File) {
        viewModelScope.launch(Dispatchers.IO) {
            val info = ModpackIndex.probe(archive)
            withContext(Dispatchers.Main) {
                pendingModpack = info
                if (info == null) {
                    error = "认不出这个整合包的格式"
                    append("整合包读取失败：既没有 modrinth.index.json 也没有 manifest.json")
                } else {
                    append("${info.name} · Minecraft ${info.mcVersion} · ${info.loaderLabel} · ${info.files.size} 个文件")
                }
            }
        }
    }

    fun installModpack(archive: File, versionName: String) {
        val dir = instDir
        startTask("安装整合包 $versionName") { id ->
            val info = ModpackIndex.probe(archive) ?: throw IllegalStateException("认不出这个整合包的格式")
            val target = File(dir, "versions/$versionName").also { it.mkdirs() }
            VersionSettings.setIsolation(dir, versionName, VersionSettings.ALL)
            val entries = FileKinds.entryNames(archive).orEmpty()
            var plan = ModpackInstall.plan(info, entries)
            // CurseForge 的清单只给 projectID/fileID，不解开这一批，装完会是一个
            // 「报成功但一个 mod 都没有」的空壳——CF 整合包的 mod 几乎全在 refs 里
            if (info.refs.isNotEmpty()) {
                onMainLog(id)("解析 ${info.refs.size} 个 CurseForge 引用…")
                val report = ModpackRefs.resolve(info.refs, CatalogKeys.fromConfig(), textFetcher)
                onMainLog(id)(ModpackRefs.describe(report))
                if (report.allFailed) {
                    throw IllegalStateException(
                        "这个整合包的 ${report.total} 个 CurseForge 引用一个都没解到地址，装了也是空的：" +
                            report.failures.first().reason,
                    )
                }
                report.failures.take(5).forEach { onMainLog(id)("跳过 ${it.ref.projectId}/${it.ref.fileId}：${it.reason}") }
                plan = ModpackRefs.merge(plan, report)
            }
            onMainLog(id)("清单 ${plan.downloads.size} 个下载 + ${plan.extracts.size} 个解包")
            val report = ModpackInstall.execute(
                plan = plan,
                contentRoot = target,
                packZip = archive,
                downloader = HttpPackDownloader,
                onProgress = { done, total, what -> progressFor(id, done.toLong(), total.toLong(), what) },
                onLog = onMainLog(id),
                cancelled = { Installer.cancelled },
            )
            onMainLog(id)("下载 ${report.downloaded} · 解包 ${report.extracted} · 跳过 ${report.skipped.size} · 失败 ${report.failed.size}")
            report.failed.take(8).forEach { onMainLog(id)("失败 ${it.path}: ${it.reason}") }
            withContext(Dispatchers.Main) {
                pendingModpack = null
                refreshLocal()
            }
        }
    }

    /**
     * 对齐桌面 `export_modpack`：把实例打成 `exports/<实例>.mrpack`。
     * 当前实例按选中版本的隔离目录取内容；别的实例取它第一个已装版本，没有就按实例根目录导。
     */
    fun exportModpack(name: String = instance, dest: File? = null) {
        val dir = Paths.instanceDir(name)
        val version = if (name == instance) versionId else InstanceStore.installedVersions(name).firstOrNull().orEmpty()
        val root = if (version.isBlank()) dir else VersionSettings.gameDir(dir, version)
        val out = dest ?: ModpackExport.defaultDest(name)
        startTask("导出整合包 $name") { id ->
            val json = if (version.isBlank()) null else runCatching { LaunchPlanner.resolveJson(dir, version) }.getOrNull()
            val meta = ModpackExport.metaFor(dir, name, version, json)
            ModpackExport.export(root, meta, out, ModpackExport.lookupWith(textFetcher)) { what, cur, total ->
                progressFor(id, cur.toLong(), total.toLong(), what)
            }
            onMainLog(id)("已导出: ${out.absolutePath}")
        }
    }

    // ---- 商店真下载 ------------------------------------------------------

    /**
     * 把一条搜索结果装下来。目标 MC 版本与加载器取当前选中的版本，
     * 这样「在 Fabric 版本下搜 mod」拿到的就是 Fabric 版，不用再问一遍。
     */
    fun installCatalogHit(hit: CatalogHit) {
        val dir = instDir
        val version = versionId
        val tab = downloadTab
        val mc = if (version.isBlank()) "" else VersionOps.mcVersionOf(dir, version)
        val loader = if (version.isBlank()) "" else VersionOps.loaderOf(LaunchPlanner.resolveJson(dir, version))
        startTask("安装${tab} ${hit.name}") { id ->
            val out = ContentInstall.installFromCatalog(
                instDir = dir,
                version = version,
                tab = tab,
                slug = hit.slug,
                projectId = hit.projectId,
                source = if (hit.source == "CurseForge") CatalogSource.CURSEFORGE else CatalogSource.MODRINTH,
                mcVersion = mc,
                loader = loader,
                keys = CatalogKeys.fromConfig(),
                fetcher = textFetcher,
                downloader = HttpPackDownloader,
                onProgress = { cur, total -> progressFor(id, cur, total, "下载 ${hit.name}") },
            )
            onMainLog(id)("已装到 ${out.path}")
            if (out.warning.isNotBlank()) onMainLog(id)("提醒：${out.warning}")
            withContext(Dispatchers.Main) {
                reloadMods()
                reloadSaves()
            }
        }
    }

    /** 候选地址按顺序试，全挂了给 null——上层据此给一句人话，而不是抛栈。 */
    private val textFetcher = TextFetcher { urls, headers ->
        urls.firstNotNullOfOrNull { url -> runCatching { Http.getText(url, headers) }.getOrNull() }
    }

    // ---- 加载器安装 ------------------------------------------------------

    var loaderKind by mutableStateOf(Loader.FABRIC)
    var loaderBuilds = mutableStateListOf<LoaderBuild>()
    var loaderBusy by mutableStateOf(false)

    fun reloadLoaderBuilds(mc: String) {
        val loader = loaderKind
        viewModelScope.launch {
            loaderBusy = true
            loaderBuilds.clear()
            try {
                val rows = withContext(Dispatchers.IO) { fetchLoaderBuilds(loader, mc) }
                loaderBuilds.addAll(rows)
                append("${loader.label} 有 ${rows.size} 个构建可选")
            } catch (e: Exception) {
                error = e.message
                append("拉 ${loader.label} 构建号失败: ${e.message}")
            } finally {
                loaderBusy = false
            }
        }
    }

    private fun fetchLoaderBuilds(loader: Loader, mc: String): List<LoaderBuild> {
        val urls = LoaderInstall.buildListUrls(loader, mc)
        val body = textFetcher.get(urls, CatalogFiles.JSON_HEADERS).orEmpty()
        return when (loader) {
            Loader.FABRIC, Loader.QUILT -> LoaderInstall.parseLoaderBuilds(body)
            Loader.FORGE -> {
                val ids = LoaderInstall.parseBmclForge(body, mc)
                    .ifEmpty { LoaderInstall.filterForgeVersions(LoaderInstall.parseMavenVersions(body), mc) }
                ids.map { LoaderBuild(it, it, !it.contains("-pre", true)) }
            }
            Loader.NEOFORGE ->
                LoaderInstall.filterNeoForgeVersions(LoaderInstall.parseMavenVersions(body), mc)
                    .map { LoaderBuild(it, it, !it.contains("beta", true)) }
            Loader.OPTIFINE -> emptyList()
        }
    }

    /**
     * 装一个加载器。
     *
     * Fabric / Quilt 走元数据那条路：上游直接给现成的 profile json，不用起 JVM，几秒完事。
     * Forge / NeoForge / OptiFine 得先在本机跑一遍 processors，交给 [JvmHost] 起真 JVM——
     * 这一段会慢好几分钟，所以整条都在任务中心里跑，有实时日志也能取消。
     */
    fun installLoader(mc: String, build: String) {
        val dir = instDir
        val loader = loaderKind
        val ctx = getApplication<Application>()
        startTask("安装 ${loader.label} $build") { id ->
            val log = onMainLog(id)
            val newId = if (LoaderInstall.isMetaOnly(loader)) {
                LoaderInstall.installMetaLoader(
                    instDir = dir,
                    loader = loader,
                    mc = mc,
                    build = build,
                    fetcher = textFetcher,
                    downloader = HttpPackDownloader,
                    onLog = log,
                    onProgress = { cur, total -> progressFor(id, cur.toLong(), total.toLong(), "补库 $cur/$total") },
                )
            } else {
                LoaderInstall.installProcessorLoader(
                    instDir = dir,
                    loader = loader,
                    mc = mc,
                    build = build,
                    downloader = HttpPackDownloader,
                    runJvm = jvmStepRunner(ctx, log),
                    onLog = log,
                    onProgress = { cur, total -> progressFor(id, cur.toLong(), total.toLong(), "$cur/$total") },
                )
            }
            withContext(Dispatchers.Main) {
                versionId = newId
                refreshLocal()
            }
        }
    }

    /**
     * 把一步 processor 交给 JVM 宿主跑完，返回退出码。
     *
     * 宿主要一个 Surface 才能起 JVM（内核 `execute(Surface, callback)` 是硬要求），
     * 所以真正的执行在 `JvmHostActivity` 里；这里 `prepare` 好之后把它拉起来，
     * 然后等宿主把这一帧标成 finished。轮询而不是回调，是因为宿主的回调发生在
     * 内核线程上、而且它明说不替调用方切线程。
     */
    private fun jvmStepRunner(ctx: Application, log: (String) -> Unit) =
        LoaderInstall.JvmStepRunner { step, index, total ->
            JvmHost.reset()
            JvmHost.prepare(
                context = ctx,
                job = JvmJob.API_INSTALLER,
                args = step.commandLine(),
                workingDir = instDir,
                jreDirName = GameRuntime.installedMajor()?.let { "jre$it" } ?: "jre17",
            )
            log("第 $index/$total 步交给 JVM 宿主：${step.mainClass}")
            ctx.startActivity(
                Intent(ctx, JvmHostActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
            var run = JvmHost.snapshot()
            while (run == null || !run.finished) {
                if (Installer.cancelled) {
                    JvmHost.cancel()
                    throw InstallCancelled()
                }
                Thread.sleep(JVM_POLL_MS)
                run = JvmHost.snapshot()
            }
            log(JvmHost.exitSummary(JvmJob.API_INSTALLER, run.exitCode, run.cancelled))
            if (run.cancelled) throw InstallCancelled()
            run.exitCode ?: -1
        }

    // ---- 存档 ------------------------------------------------------------

    fun reloadSaves() {
        val dir = gameDir
        val kind = saveKind
        viewModelScope.launch(Dispatchers.IO) {
            val saveRows = runCatching { Saves.list(dir) }.getOrDefault(emptyList())
            val backupRows = runCatching { Saves.listBackups(dir) }.getOrDefault(emptyList())
            val mediaRows = Saves.MEDIA_KINDS.keys.firstOrNull { it == mediaKindOf(kind) }
                ?.let { runCatching { Saves.listMedia(dir, it) }.getOrDefault(emptyList()) }
                ?: emptyList()
            withContext(Dispatchers.Main) {
                saves.clear()
                saves.addAll(saveRows)
                backups.clear()
                backups.addAll(backupRows)
                media.clear()
                media.addAll(mediaRows)
            }
        }
    }

    fun selectSaveKind(kind: String) {
        saveKind = kind
        reloadSaves()
    }

    fun deleteSave(name: String) = saveAction { Saves.delete(gameDir, name) }

    fun renameSave(name: String, newName: String) = saveAction { Saves.rename(gameDir, name, newName) }

    fun deleteBackup(name: String) = saveAction { Saves.deleteBackup(gameDir, name) }

    fun restoreBackup(name: String) = saveAction {
        val out = Saves.restore(gameDir, name)
        append("已还原为存档「${out.name}」")
    }

    fun backupSave(name: String) {
        val dir = gameDir
        startTask("备份存档 $name") { id ->
            val row = Saves.backup(dir, name) { cur, total -> progressFor(id, cur.toLong(), total.toLong(), "打包 $name") }
            onMainLog(id)("备份完成 ${row.name}（${Saves.formatSize(row.bytes)}）")
            withContext(Dispatchers.Main) { reloadSaves() }
        }
    }

    fun exportSave(name: String, dest: File) {
        val dir = gameDir
        startTask("导出存档 $name") { id ->
            val out = Saves.export(dir, name, dest) { cur, total ->
                progressFor(id, cur.toLong(), total.toLong(), "打包 $name")
            }
            onMainLog(id)("已导出到 ${out.absolutePath}")
        }
    }

    fun installDatapack(filename: String, saveName: String) = saveAction {
        Saves.installDatapack(gameDir, instDir, filename, saveName)
    }

    fun datapacks(): List<String> =
        File(instDir, "datapacks").listFiles()?.filter { it.isFile }?.map { it.name }?.sorted() ?: emptyList()

    private fun saveAction(block: () -> Unit) {
        viewModelScope.launch(Dispatchers.IO) {
            val failure = runCatching(block).exceptionOrNull()
            withContext(Dispatchers.Main) {
                failure?.let {
                    error = it.message
                    append("存档操作失败: ${it.message}")
                }
                reloadSaves()
            }
        }
    }

    private fun mediaKindOf(kind: String): String = when (kind) {
        "截图" -> "screenshots"
        "崩溃报告" -> "crash-reports"
        "日志" -> "logs"
        else -> ""
    }

    // ---- 服务器 ----------------------------------------------------------

    fun reloadServers() {
        val dir = gameDir
        viewModelScope.launch(Dispatchers.IO) {
            val rows = runCatching { Servers.list(dir) }.getOrDefault(emptyList())
            withContext(Dispatchers.Main) {
                servers.clear()
                servers.addAll(rows)
            }
        }
    }

    fun addServer(name: String, address: String) = serverAction {
        Servers.add(gameDir, name, address)
    }

    fun updateServer(index: Int, name: String, address: String) = serverAction {
        Servers.update(gameDir, index, name = name, ip = address)
    }

    fun deleteServer(index: Int) = serverAction { Servers.delete(gameDir, index) }

    fun moveServer(from: Int, to: Int) = serverAction { Servers.move(gameDir, from, to) }

    fun importServers(text: String) = serverAction {
        val n = if (text.trimStart().startsWith("[")) {
            Servers.importJson(gameDir, text)
        } else {
            Servers.importText(gameDir, text)
        }
        append("已导入 $n 个服务器")
    }

    fun exportServers(): String = Servers.exportText(gameDir)

    /** `ip:port` → 上一次 ping 的结果。列表按这个键取，加删服务器不会错位。 */
    var serverStatus by mutableStateOf<Map<String, ServerStatus>>(emptyMap())
    var pingBusy by mutableStateOf(false)

    fun pingServers() {
        if (pingBusy) return
        val rows = servers.toList()
        if (rows.isEmpty()) return
        viewModelScope.launch {
            pingBusy = true
            try {
                // 串行而不是并发：手机上一次开十几个 socket 不划算，
                // 而且每 ping 完一个就刷一次，用户能看着它一条条亮起来
                for (s in rows) {
                    val status = withContext(Dispatchers.IO) { ServerPing.ping(s.ip, s.port) }
                    serverStatus = serverStatus + ("${s.ip}:${s.port}" to status)
                }
            } finally {
                pingBusy = false
            }
        }
    }

    fun statusOf(ip: String, port: Int): ServerStatus? = serverStatus["$ip:$port"]

    private fun serverAction(block: () -> Unit) {
        viewModelScope.launch(Dispatchers.IO) {
            val failure = runCatching(block).exceptionOrNull()
            withContext(Dispatchers.Main) {
                failure?.let {
                    error = it.message
                    append("服务器操作失败: ${it.message}")
                }
                reloadServers()
            }
        }
    }

    // ---- 游玩时长 --------------------------------------------------------

    fun reloadPlaytime() {
        viewModelScope.launch(Dispatchers.IO) {
            val data = Playtime.load(Paths.root)
            withContext(Dispatchers.Main) { playtime = data }
        }
    }

    fun clearPlaytime(instanceName: String = "") {
        viewModelScope.launch(Dispatchers.IO) {
            Playtime.clear(Paths.root, instanceName)
            val data = Playtime.load(Paths.root)
            withContext(Dispatchers.Main) {
                playtime = data
                append(if (instanceName.isEmpty()) "已清除全部游玩记录" else "已清除「$instanceName」的游玩记录")
            }
        }
    }

    fun totalPlaytimeText(): String = Playtime.format(Playtime.totalOf(playtime))

    fun formatPlaytime(seconds: Long): String = Playtime.format(seconds)

    // ---- 联机 ------------------------------------------------------------

    fun lanHint(): String = Lan.hint(lanPort)

    /** 粘一整段聊天记录也能认出房间号，认不出就原样留着让用户自己看。 */
    fun normalizeRoomCode(): String? {
        val parsed = Terracotta.parseRoom(roomCode)
        if (parsed != null) roomCode = parsed
        return parsed
    }

    /** 传给内核的会合节点。第一条永远是 HMCL_CUSTOM_NODE，漏了会报成 PingHostFail（d-157）。 */
    fun multiplayerNodes(): List<String> = Terracotta.extraNodes()

    // ---- 下载商店 --------------------------------------------------------

    fun searchCatalog() {
        val kind = downloadTab
        val q = query
        viewModelScope.launch {
            busy = true
            error = null
            try {
                val rows = withContext(Dispatchers.IO) { CatalogRepo.searchKind(kind, q) }
                catalog.clear()
                catalog.addAll(rows)
                append("搜索 $kind 「$q」 ${rows.size} 条")
            } catch (e: Exception) {
                error = e.message
                append("搜索失败: ${e.message}")
            } finally {
                busy = false
            }
        }
    }

    // ---- 收藏夹 ----------------------------------------------------------

    var favorites = mutableStateListOf<FavoriteItem>()

    /** 商店页此刻列的是收藏还是搜索结果。跟桌面那个心形按钮一个作用。 */
    var showFavorites by mutableStateOf(false)

    fun reloadFavorites() {
        viewModelScope.launch(Dispatchers.IO) {
            val rows = runCatching { CatalogFavorites.list() }.getOrDefault(emptyList())
            withContext(Dispatchers.Main) {
                favorites.clear()
                favorites.addAll(rows)
            }
        }
    }

    fun isFavorite(hit: CatalogHit): Boolean =
        CatalogFavorites.contains(favorites.toList(), CatalogFavorites.of(hit))

    fun toggleFavorite(hit: CatalogHit) {
        val item = CatalogFavorites.of(hit)
        viewModelScope.launch(Dispatchers.IO) {
            val rows = runCatching { CatalogFavorites.toggle(item) }.getOrElse { failure ->
                withContext(Dispatchers.Main) {
                    error = failure.message
                    append("收藏失败: ${failure.message}")
                }
                return@launch
            }
            withContext(Dispatchers.Main) {
                favorites.clear()
                favorites.addAll(rows)
                append(if (CatalogFavorites.contains(rows, item)) "已收藏 ${item.name}" else "已取消收藏 ${item.name}")
            }
        }
    }

    // ---- 启动页资讯 ------------------------------------------------------

    var news = mutableStateListOf<NewsItem>()
    var newsBusy by mutableStateOf(false)
    private var newsLoaded = false

    /**
     * 先把缓存铺上去，再后台拉一次覆盖——对齐桌面 `launch_page._load_news`：
     * 断网时看到的是上次那几条，而不是一张空卡。
     */
    fun reloadNews(force: Boolean = false) {
        if (newsBusy || (newsLoaded && !force)) return
        newsLoaded = true
        viewModelScope.launch {
            newsBusy = true
            try {
                val cached = withContext(Dispatchers.IO) { NewsRepo.loadCached() }
                if (cached.isNotEmpty() && news.isEmpty()) {
                    news.addAll(cached)
                }
                val rows = withContext(Dispatchers.IO) { NewsRepo.fetch(textFetcher) }
                if (rows.isNotEmpty()) {
                    news.clear()
                    news.addAll(rows)
                } else if (cached.isEmpty()) {
                    append("资讯没拉到，也没有缓存")
                }
            } catch (e: Exception) {
                append("资讯刷新失败: ${e.message}")
            } finally {
                newsBusy = false
            }
        }
    }

    // ---- 启动前体检 / 崩溃一键修复 / 陶瓦直连 ---------------------------------

    /** 最近一次体检结果；null = 还没跑过或已经关掉那张卡。 */
    var preflight by mutableStateOf<PreflightResult?>(null)

    /** 「我的」下面要跳去的二级页（java / feedback…），外壳 MainTab 消费后清空。 */
    var pendingMineRoute by mutableStateOf<String?>(null)

    /** 对齐桌面 `preflight_launch`：只体检不启动，结果摆在启动页那张卡上，每条带「去修」落点。 */
    fun runPreflight() {
        val dir = instDir
        val vid = versionId
        val mem = memoryMb
        viewModelScope.launch(Dispatchers.IO) {
            val result = runCatching { Preflight.check(dir, vid, mem) }
                .getOrElse { PreflightResult(listOf(PreflightItem(Preflight.ERROR, "check_failed", it.message.orEmpty()))) }
            withContext(Dispatchers.Main) { preflight = result }
        }
    }

    /**
     * 对齐桌面 `apply_crash_action`：停用模组 / 清 JVM 参数这类文件操作在这里做完；
     * 改内存、修版本直接落到本 ViewModel 的状态与任务上；换页面的 route 原样交回界面。
     */
    fun applyCrashAction(action: CrashAction, report: CrashReport, onDone: (CrashActionResult) -> Unit) {
        val dir = Paths.instanceDir(report.instance.ifBlank { instance })
        val version = report.version
        viewModelScope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { CrashActions.apply(action, dir, version) }
                    .getOrElse { CrashActionResult(false, CrashActions.R_UNKNOWN, detail = it.message.orEmpty()) }
            }
            // 换页面的（java / mods / crash）由界面按 route 自己跳，这里只动本 ViewModel 管得到的状态
            when (result.route) {
                CrashActions.ROUTE_MEMORY -> {
                    memoryMb = result.count
                    persistUi()
                }
                CrashActions.ROUTE_REPAIR -> if (version.isNotBlank()) repairVersion(version)
            }
            if (result.code == CrashActions.R_DISABLED) reloadMods()
            onDone(result)
        }
    }

    /** 对齐桌面 `terracotta_direct_connect`：地址不合法当场拦住；合法就带着 `--server/--port` 启动。 */
    fun launchDirect(address: String, port: String = "") {
        val target = TerracottaCore.parseDirect(address, port)
        if (target.error.isNotEmpty()) {
            error = when (target.error) {
                TerracottaCore.DIRECT_LOOPBACK -> "请输入房主的公网地址，例如 1.2.3.4:25565"
                TerracottaCore.DIRECT_BAD_PORT -> "端口号必须在 1-65535 之间"
                else -> "还没有联机地址。"
            }
            return
        }
        launchGame(server = DirectConnect.address(target.host, target.port))
    }

    // ---- 启动 ------------------------------------------------------------

    /** @param server 陶瓦公网直连地址（`host:port`），空 = 正常启动到主菜单。 */
    fun launchGame(server: String = "") {
        persistUi()
        val vid = versionId
        if (vid.isBlank()) {
            error = "先选版本"
            return
        }
        val inst = instance
        val user = username
        val mem = memoryMb
        val known = versions.toList()
        startTask("启动游戏 $vid") { id ->
            var plan = LaunchPlanner.plan(inst, vid, user, mem)
            if (plan.missing.isNotEmpty()) {
                val row = known.firstOrNull { it.id == vid }
                    ?: ManifestRepo.fetch(false).firstOrNull { it.id == vid }
                    ?: throw IllegalStateException("清单没有 $vid，去下载页刷新")
                onMainLog(id)("缺 ${plan.missing.size} 个文件，开始安装 $vid")
                Installer.installVanilla(
                    inst,
                    row,
                    { cur, total, msg -> progressFor(id, cur, total, msg) },
                    onMainLog(id),
                )
                plan = LaunchPlanner.plan(inst, vid, user, mem)
            }
            if (plan.missing.isNotEmpty()) {
                throw IllegalStateException("安装后仍缺 ${plan.missing.size} 个文件")
            }
            VersionSettings.applyLayout(Paths.instanceDir(inst), vid)
            onMainLog(id)(LaunchPlanner.describe(plan))
            val ctx = getApplication<Application>()
            // 对齐桌面 _launch_into_server：直连前把地址写成多人列表里的「陶瓦联机大厅」那一行
            val direct = TerracottaCore.parseDirect(server)
            if (server.isNotBlank() && direct.error.isEmpty()) {
                val lobbyDir = LaunchPlanner.gameDirOf(Paths.instanceDir(inst), vid)
                runCatching { Servers.writeAll(lobbyDir, TerracottaCore.withLobby(Servers.list(lobbyDir), direct.host, direct.port)) }
                    .onFailure { onMainLog(id)("写入「${TerracottaCore.LOBBY_NAME}」失败: ${it.message}") }
                onMainLog(id)("直连 ${direct.host}:${direct.port}")
            }
            McLaunch.prepare(ctx, inst, vid, user, mem, onMainLog(id), server)
            GameRuntime.beginSession(inst, vid)
            withContext(Dispatchers.Main) {
                runtimePkg = GameRuntime.installed()
                McLaunch.open(ctx)
                refreshLocal()
                append("已打开游戏画面")
            }
        }
    }

    // ---- 配置落盘 --------------------------------------------------------

    fun persistUiDebounced() {
        persistJob?.cancel()
        persistJob = viewModelScope.launch {
            delay(PERSIST_DEBOUNCE_MS)
            persistUi()
        }
    }

    fun persistUi() {
        val user = username
        val mem = memoryMb
        val hidden = showHidden
        viewModelScope.launch(Dispatchers.IO) {
            val cfg = InstanceStore.loadConfig()
            cfg.put("username", user)
            cfg.put("memory_mb", mem)
            cfg.put("show_hidden_versions", hidden)
            InstanceStore.saveConfig(cfg)
        }
    }

    companion object {
        /** 存档页顶部两种有专属列表的类型。UI 层分流时引用常量，显示名另走词表。 */
        const val SAVE_KIND_SAVES = "存档"
        const val SAVE_KIND_BACKUPS = "备份"
        val SAVE_KINDS = listOf(SAVE_KIND_SAVES, SAVE_KIND_BACKUPS, "截图", "崩溃报告", "日志")

        private const val LOG_LIMIT = 40
        private const val LOG_DEBOUNCE_MS = 80L
        private const val PERSIST_DEBOUNCE_MS = 400L
        private const val PROGRESS_THROTTLE_MS = 80L
        private const val VERSION_PAGE = 80

        /** 等 JVM 宿主那一帧的轮询间隔。processor 动辄跑几分钟，不用问得太勤。 */
        private const val JVM_POLL_MS = 400L
    }
}

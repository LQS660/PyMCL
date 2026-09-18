package com.pymcl.mobile.data

import com.pymcl.mobile.model.ServerEntry
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

class ServerError(message: String) : RuntimeException(message)

/**
 * 服务器列表：以游戏真正读的 `servers.dat` 为准，`servers.json` 只负责存
 * 游戏那边放不下的字段（描述、图标）以及导入导出，语义与桌面 `mclauncher/servers.py` 一致。
 */
object Servers {
    const val JSON_FILE = "servers.json"
    const val GAME_FILE = "servers.dat"
    const val DEFAULT_PORT = 25565

    fun jsonFile(gameDir: File): File = File(gameDir, JSON_FILE)

    fun datFile(gameDir: File): File = File(gameDir, GAME_FILE)

    /**
     * `example.com:19132` / `[fe80::1]:19132` / `example.com` + 独立端口，都归一成 (host, port)。
     *
     * 裸 IPv6 字面量不拆：`fe80::1` 里最后一段也是数字，按「末段是端口」去切会把它
     * 截成 `fe80:` + 端口 1。要带端口就得按 RFC 3986 写成方括号形式。
     */
    fun splitAddress(ip: String, port: Any? = null): Pair<String, Int> {
        val text = ip.trim()
        val explicit = when (port) {
            is Int -> port
            is String -> port.trim().toIntOrNull()
            else -> null
        }
        if (explicit != null && explicit in 1..65535) return hostOf(text) to explicit
        if (text.startsWith("[")) {
            val close = text.indexOf(']')
            if (close > 0) {
                val host = text.substring(1, close)
                val rest = text.substring(close + 1)
                val parsed = rest.removePrefix(":").toIntOrNull()
                if (rest.startsWith(":") && parsed != null && parsed in 1..65535) return host to parsed
                return host to DEFAULT_PORT
            }
        }
        if (text.count { it == ':' } == 1) {
            val host = text.substringBefore(':')
            val tail = text.substringAfter(':')
            val parsed = tail.toIntOrNull()
            if (tail.isNotEmpty() && tail.all { it.isDigit() } && parsed != null && parsed in 1..65535) {
                return host to parsed
            }
        }
        return text to DEFAULT_PORT
    }

    private fun hostOf(text: String): String {
        if (text.startsWith("[")) {
            val close = text.indexOf(']')
            if (close > 0) return text.substring(1, close)
        }
        return if (text.count { it == ':' } == 1) text.substringBefore(':') else text
    }

    fun list(gameDir: File): List<ServerEntry> {
        val fromDat = readDat(datFile(gameDir))
        val extras = readJson(jsonFile(gameDir))
        if (fromDat.isEmpty()) return extras.mapIndexed { i, row -> row.copy(index = i) }
        val byAddress = extras.associateBy { it.ip to it.port }
        return fromDat.mapIndexed { i, row ->
            val extra = byAddress[row.ip to row.port]
            row.copy(
                name = row.name.ifBlank { extra?.name ?: row.ip },
                description = extra?.description.orEmpty(),
                icon = extra?.icon.orEmpty(),
                index = i,
            )
        }
    }

    /** [port] 留空就从地址里读；`mc.example.com:25570` 这种粘贴进来的整串也认。 */
    fun add(
        gameDir: File,
        name: String,
        ip: String,
        port: Int? = null,
        description: String = "",
        icon: String = "",
    ): ServerEntry {
        if (ip.isBlank()) throw ServerError("服务器地址不能为空")
        if (port != null && port !in 1..65535) throw ServerError("端口号必须在 1-65535 之间")
        val (host, resolved) = splitAddress(ip, port)
        if (host.isBlank()) throw ServerError("服务器地址不能为空")
        val rows = list(gameDir).toMutableList()
        val entry = ServerEntry(
            name = name.trim().ifBlank { host },
            ip = host,
            port = resolved,
            description = description.trim(),
            icon = icon,
            index = rows.size,
        )
        rows += entry
        writeAll(gameDir, rows)
        return entry
    }

    fun update(
        gameDir: File,
        index: Int,
        name: String? = null,
        ip: String? = null,
        port: Int? = null,
        description: String? = null,
        hidden: Boolean? = null,
    ): ServerEntry {
        val rows = list(gameDir).toMutableList()
        if (index !in rows.indices) throw ServerError("服务器索引 $index 不存在")
        if (ip != null && ip.isBlank()) throw ServerError("服务器地址不能为空")
        if (port != null && port !in 1..65535) throw ServerError("端口号必须在 1-65535 之间")
        val old = rows[index]
        // 只改名字时端口要保持不动；新地址自带端口时才让它盖掉旧的
        val rawIp = ip ?: old.ip
        val (host, parsed) = splitAddress(rawIp)
        val resolved = port ?: if (parsed != DEFAULT_PORT) parsed else old.port
        val updated = old.copy(
            name = name?.trim() ?: old.name,
            ip = host,
            port = resolved,
            description = description?.trim() ?: old.description,
            hidden = hidden ?: old.hidden,
        )
        rows[index] = updated
        writeAll(gameDir, rows)
        return updated
    }

    fun delete(gameDir: File, index: Int) {
        val rows = list(gameDir).toMutableList()
        if (index !in rows.indices) throw ServerError("服务器索引 $index 不存在")
        rows.removeAt(index)
        writeAll(gameDir, rows)
    }

    fun move(gameDir: File, from: Int, to: Int) {
        val rows = list(gameDir).toMutableList()
        if (from !in rows.indices) throw ServerError("服务器索引 $from 不存在")
        val target = to.coerceIn(0, rows.size - 1)
        if (target == from) return
        rows.add(target, rows.removeAt(from))
        writeAll(gameDir, rows)
    }

    /**
     * 纯文本批量导入。每行 `名字<TAB>地址:端口` / `地址:端口` / `地址`，
     * 空行与 `#` 注释跳过，地址端口都相同的重复项跳过。返回真正新增了几条。
     */
    fun importText(gameDir: File, text: String): Int {
        val rows = list(gameDir).toMutableList()
        val seen = rows.map { it.ip to it.port }.toMutableSet()
        var added = 0
        for (raw in text.lines()) {
            val line = raw.trim()
            if (line.isEmpty() || line.startsWith("#")) continue
            val name: String
            val addr: String
            if (line.contains('\t')) {
                name = line.substringBefore('\t').trim()
                addr = line.substringAfter('\t').trim()
            } else {
                name = ""
                addr = line
            }
            val (host, port) = splitAddress(addr)
            if (host.isBlank() || (host to port) in seen) continue
            rows += ServerEntry(name.ifBlank { host }, host, port, index = rows.size)
            seen += host to port
            added++
        }
        if (added > 0) writeAll(gameDir, rows)
        return added
    }

    fun exportText(gameDir: File): String {
        val rows = list(gameDir)
        val lines = mutableListOf("# PyMCL 服务器列表导出", "# 共 ${rows.size} 个服务器", "")
        rows.forEach { s ->
            lines += if (s.name.isNotBlank() && s.name != s.ip) {
                "${s.name}\t${s.ip}:${s.port}"
            } else {
                "${s.ip}:${s.port}"
            }
        }
        return lines.joinToString("\n")
    }

    fun importJson(gameDir: File, text: String): Int {
        val arr = runCatching { JSONArray(text) }.getOrElse { throw ServerError("导入数据必须是 JSON 数组") }
        val rows = list(gameDir).toMutableList()
        val seen = rows.map { it.ip to it.port }.toMutableSet()
        var added = 0
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val (host, port) = splitAddress(o.optString("ip"), o.opt("port"))
            if (host.isBlank() || (host to port) in seen) continue
            rows += ServerEntry(
                name = o.optString("name").ifBlank { host },
                ip = host,
                port = port,
                description = o.optString("description"),
                icon = o.optString("icon"),
                index = rows.size,
            )
            seen += host to port
            added++
        }
        if (added > 0) writeAll(gameDir, rows)
        return added
    }

    fun exportJson(gameDir: File): String {
        val arr = JSONArray()
        list(gameDir).forEach { s ->
            arr.put(
                JSONObject()
                    .put("name", s.name)
                    .put("ip", s.ip)
                    .put("port", s.port)
                    .put("description", s.description)
                    .put("icon", s.icon),
            )
        }
        return arr.toString(2)
    }

    fun writeAll(gameDir: File, rows: List<ServerEntry>) {
        gameDir.mkdirs()
        val arr = JSONArray()
        rows.forEach { s ->
            arr.put(
                JSONObject()
                    .put("name", s.name)
                    .put("ip", s.ip)
                    .put("port", s.port)
                    .put("description", s.description)
                    .put("icon", s.icon)
                    .put("hidden", s.hidden),
            )
        }
        jsonFile(gameDir).writeText(arr.toString(2), Charsets.UTF_8)
        writeDat(datFile(gameDir), rows)
    }

    internal fun readJson(file: File): List<ServerEntry> {
        if (!file.isFile) return emptyList()
        val arr = runCatching { JSONArray(file.readText()) }.getOrNull() ?: return emptyList()
        return (0 until arr.length()).mapNotNull { i ->
            val o = arr.optJSONObject(i) ?: return@mapNotNull null
            val (host, port) = splitAddress(o.optString("ip"), o.opt("port"))
            if (host.isBlank()) return@mapNotNull null
            ServerEntry(
                name = o.optString("name").ifBlank { host },
                ip = host,
                port = port,
                description = o.optString("description"),
                icon = o.optString("icon"),
                hidden = o.optBoolean("hidden"),
                index = i,
            )
        }
    }

    internal fun readDat(file: File): List<ServerEntry> {
        if (!file.isFile) return emptyList()
        val root = runCatching { Nbt.read(file.readBytes()) }.getOrNull() ?: return emptyList()
        val list = root["servers"] as? Nbt.NbtList ?: return emptyList()
        return list.items.mapIndexedNotNull { i, item ->
            val row = item as? Map<*, *> ?: return@mapIndexedNotNull null
            val raw = row["ip"] as? String ?: return@mapIndexedNotNull null
            val (host, port) = splitAddress(raw)
            if (host.isBlank()) return@mapIndexedNotNull null
            ServerEntry(
                name = (row["name"] as? String).orEmpty().ifBlank { host },
                ip = host,
                port = port,
                icon = (row["icon"] as? String).orEmpty(),
                hidden = ((row["hidden"] as? Byte)?.toInt() ?: 0) != 0,
                index = i,
            )
        }
    }

    internal fun writeDat(file: File, rows: List<ServerEntry>) {
        val items = rows.map { s ->
            linkedMapOf<String, Any>(
                "name" to s.name,
                // 默认端口不写进地址：游戏自己会补，写了反而和原版存的形状对不上
                "ip" to if (s.port == DEFAULT_PORT) s.ip else "${s.ip}:${s.port}",
                "icon" to s.icon,
                "hidden" to (if (s.hidden) 1 else 0).toByte(),
            )
        }
        val root = linkedMapOf<String, Any>("servers" to Nbt.NbtList(Nbt.TAG_COMPOUND, items))
        file.parentFile?.mkdirs()
        file.writeBytes(Nbt.write(root))
    }
}

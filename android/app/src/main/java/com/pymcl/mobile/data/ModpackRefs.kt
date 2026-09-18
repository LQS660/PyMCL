package com.pymcl.mobile.data

import org.json.JSONObject

/** 一条 CurseForge 引用解出来的结果：要么拿到文件，要么拿到一句能给用户看的原因。 */
sealed class RefResult {
    data class Ok(val ref: CursePackRef, val file: PackFile) : RefResult()

    data class Failed(val ref: CursePackRef, val reason: String) : RefResult()
}

data class RefReport(
    val resolved: List<PackFile> = emptyList(),
    val failures: List<RefResult.Failed> = emptyList(),
) {
    val total: Int get() = resolved.size + failures.size

    /** 必需的那些一个都没解出来时，这趟安装不能报成功。 */
    val allFailed: Boolean get() = resolved.isEmpty() && failures.isNotEmpty()
}

/**
 * CurseForge 整合包的 `manifest.json` 只给 `projectID` / `fileID`，不给下载地址。
 * 这个文件负责把那一批引用换成真能下的 [PackFile]。
 *
 * 没有这一步，CF 整合包会**报成功但一个 mod 都没装**——它的 mod 几乎全在 refs 里，
 * `files` 那一段通常是空的。解不出来的必须逐条说清原因，不能悄悄跳过。
 */
object ModpackRefs {
    /** CF 允许作者关掉第三方下载，这时 `downloadUrl` 是 null。这不是网络问题，得单独说。 */
    const val BLOCKED_MESSAGE = "作者在 CurseForge 上关闭了第三方下载，只能去官网手动下"

    fun fileUrls(projectId: Long, fileId: Long): List<String> {
        val tail = "v1/mods/$projectId/files/$fileId"
        return listOf("${Paths.MCIM}/curseforge/$tail", "${CatalogFiles.CURSEFORGE_OFFICIAL.removeSuffix("/v1")}/$tail")
    }

    /** CF 的 `/files/{id}` 返回 `{"data":{…}}`；包一层数组就能复用已有的解析。 */
    internal fun parseSingle(body: String): PackFile? {
        val data = runCatching { JSONObject(body).optJSONObject("data") }.getOrNull() ?: return null
        val wrapped = JSONObject().put("data", org.json.JSONArray().put(data))
        return CatalogFiles.parseCurseForgeFiles(wrapped.toString())
            .firstOrNull()
            ?.files
            ?.firstOrNull()
    }

    /** 作者关了第三方下载时 CF 照样返 200，只是 `downloadUrl` 为空。 */
    internal fun isBlocked(body: String): Boolean {
        val data = runCatching { JSONObject(body).optJSONObject("data") }.getOrNull() ?: return false
        return data.has("downloadUrl") && data.isNull("downloadUrl")
    }

    /**
     * 逐条解。
     *
     * @param keys 没填 CurseForge API key 时**直接整批失败并说清楚**，而不是一条条超时。
     * @param subdir refs 都是 mod，落在 `mods/` 下；CF 的清单本身不带路径。
     */
    fun resolve(
        refs: List<CursePackRef>,
        keys: CatalogKeys,
        fetcher: TextFetcher,
        subdir: String = "mods",
    ): RefReport {
        if (refs.isEmpty()) return RefReport()
        if (!keys.hasCurseForge) {
            return RefReport(failures = refs.map { RefResult.Failed(it, CatalogFiles.NEED_KEY_MESSAGE) })
        }
        val headers = CatalogFiles.JSON_HEADERS + ("x-api-key" to keys.curseForgeApiKey)
        val ok = ArrayList<PackFile>(refs.size)
        val bad = ArrayList<RefResult.Failed>()
        for (ref in refs) {
            val body = fetcher.get(fileUrls(ref.projectId, ref.fileId), headers)
            if (body.isNullOrBlank()) {
                bad += RefResult.Failed(ref, "问不到 ${ref.projectId}/${ref.fileId} 的下载地址")
                continue
            }
            if (isBlocked(body)) {
                bad += RefResult.Failed(ref, BLOCKED_MESSAGE)
                continue
            }
            val file = parseSingle(body)
            if (file == null || file.urls.isEmpty()) {
                bad += RefResult.Failed(ref, "CurseForge 没给 ${ref.projectId}/${ref.fileId} 的下载地址")
                continue
            }
            // 清单里不带路径，按它本来的角色落进 mods/
            ok += file.copy(path = "$subdir/${file.path.substringAfterLast('/')}")
        }
        return RefReport(ok, bad)
    }

    /** 把解出来的并回计划里；解不出来的转成跳过记录，最后会出现在安装回执上。 */
    fun merge(plan: InstallPlan, report: RefReport): InstallPlan {
        val merged = ModpackInstall.withResolved(plan, report.resolved)
        if (report.failures.isEmpty()) return merged
        return merged.copy(
            skipped = merged.skipped + report.failures.map {
                SkippedFile("${it.ref.projectId}/${it.ref.fileId}", it.reason)
            },
        )
    }

    /** 给用户看的一句话。 */
    fun describe(report: RefReport): String = when {
        report.total == 0 -> "这个整合包没有 CurseForge 引用"
        report.failures.isEmpty() -> "CurseForge 引用 ${report.resolved.size} 个全部解到地址"
        else -> "CurseForge 引用 ${report.total} 个，解到 ${report.resolved.size} 个，" +
            "失败 ${report.failures.size} 个：${report.failures.first().reason}"
    }
}

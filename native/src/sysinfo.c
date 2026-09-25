#include "pymcl.h"
#include <ctype.h>
#include <math.h>
#include <pthread.h>
#include <winsock2.h>

/* mclauncher/sysinfo.py 的移植：系统 / CPU / 内存 / 显卡 / 磁盘 / 分辨率 / Java / 实例。
   CPU 核数与显卡跟 Python 一样走 PowerShell 的 Win32_Processor / Win32_VideoController，
   结果缓存半小时；整份快照缓存 120 秒。 */

#define APP_VERSION "1.0.1"

static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static cJSON *g_cache;
static ULONGLONG g_cache_t;
static cJSON *g_cpu, *g_gpus;
static ULONGLONG g_cpu_t, g_gpus_t;

/* 跑一个命令，收齐 stdout+stderr（到进程退出且管道读空为止） */
static char *run_capture(const char **argv, int argc, int timeout_sec) {
    HANDLE rd = NULL;
    HANDLE proc = pymcl_spawn_process(argv, argc, NULL, &rd);
    if (!proc) return NULL;
    size_t cap = 8192, len = 0;
    char *out = (char *)malloc(cap);
    if (!out) { CloseHandle(rd); CloseHandle(proc); return NULL; }
    ULONGLONG deadline = GetTickCount64() + (ULONGLONG)timeout_sec * 1000;
    for (;;) {
        DWORD avail = 0, got = 0;
        int exited = WaitForSingleObject(proc, 0) == WAIT_OBJECT_0;
        if (PeekNamedPipe(rd, NULL, 0, NULL, &avail, NULL) && avail) {
            if (len + avail + 1 > cap) {
                while (len + avail + 1 > cap) cap *= 2;
                char *nb = (char *)realloc(out, cap);
                if (!nb) break;
                out = nb;
            }
            if (ReadFile(rd, out + len, avail, &got, NULL)) len += got;
            continue;
        }
        if (exited) break;
        if (GetTickCount64() > deadline) { TerminateProcess(proc, 1); break; }
        Sleep(20);
    }
    out[len] = 0;
    CloseHandle(rd);
    CloseHandle(proc);
    return out;
}

static cJSON *ps_json(const char *script, int timeout) {
    char full[2048];
    snprintf(full, sizeof(full), "[Console]::OutputEncoding=[Text.UTF8Encoding]::new();"
             "$OutputEncoding=[Console]::OutputEncoding;%s", script);
    const char *argv[] = {"powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", full};
    char *text = run_capture(argv, 7, timeout);
    if (!text) return NULL;
    char *a = strchr(text, '['), *b = strchr(text, '{');
    char *start = (!a || (b && b < a)) ? b : a;
    cJSON *j = start ? cJSON_Parse(start) : NULL;
    free(text);
    return j;
}

static void reg_str(const wchar_t *path, const wchar_t *name, char *out, size_t n, const char *def) {
    snprintf(out, n, "%s", def ? def : "");
    HKEY k;
    if (RegOpenKeyExW(HKEY_LOCAL_MACHINE, path, 0, KEY_READ, &k) != ERROR_SUCCESS) return;
    DWORD type = 0, size = 0;
    if (RegQueryValueExW(k, name, NULL, &type, NULL, &size) == ERROR_SUCCESS && size) {
        BYTE *buf = (BYTE *)calloc(1, size + 4);
        if (buf && RegQueryValueExW(k, name, NULL, &type, buf, &size) == ERROR_SUCCESS) {
            if (type == REG_SZ || type == REG_EXPAND_SZ) {
                char *u = pymcl_wide_to_u8((wchar_t *)buf);
                if (u) { if (u[0]) snprintf(out, n, "%s", u); free(u); }
            } else if (type == REG_DWORD) {
                snprintf(out, n, "%lu", (unsigned long)*(DWORD *)buf);
            }
        }
        free(buf);
    }
    RegCloseKey(k);
}

typedef LONG (WINAPI *rtl_get_version_fn)(PRTL_OSVERSIONINFOW);

static cJSON *os_info(void) {
    RTL_OSVERSIONINFOW v;
    memset(&v, 0, sizeof(v));
    v.dwOSVersionInfoSize = sizeof(v);
    rtl_get_version_fn fn = (rtl_get_version_fn)(void *)GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "RtlGetVersion");
    if (fn) fn(&v);
    char release[32], version[64], platform[128], display[512];
    snprintf(release, sizeof(release), "%lu", (unsigned long)v.dwMajorVersion);
    if (v.dwMajorVersion == 10 && v.dwBuildNumber >= 22000) snprintf(release, sizeof(release), "11");
    snprintf(version, sizeof(version), "%lu.%lu.%lu", (unsigned long)v.dwMajorVersion,
             (unsigned long)v.dwMinorVersion, (unsigned long)v.dwBuildNumber);
    snprintf(platform, sizeof(platform), "Windows-%s-%s-SP0", release, version);
    snprintf(display, sizeof(display), "%s", platform);
    const wchar_t *key = L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion";
    char product[256], disp[64], build_n[64], ubr[32];
    reg_str(key, L"ProductName", product, sizeof(product), "");
    reg_str(key, L"DisplayVersion", disp, sizeof(disp), "");
    reg_str(key, L"CurrentBuild", build_n, sizeof(build_n), "");
    if (!build_n[0]) reg_str(key, L"CurrentBuildNumber", build_n, sizeof(build_n), "");
    reg_str(key, L"UBR", ubr, sizeof(ubr), "");
    char bits[512] = "";
    if (product[0]) snprintf(bits + strlen(bits), sizeof(bits) - strlen(bits), "%s", product);
    if (disp[0]) snprintf(bits + strlen(bits), sizeof(bits) - strlen(bits), "%s%s", bits[0] ? " " : "", disp);
    if (build_n[0]) {
        snprintf(bits + strlen(bits), sizeof(bits) - strlen(bits), "%s%s", bits[0] ? " " : "", build_n);
        if (ubr[0]) snprintf(bits + strlen(bits), sizeof(bits) - strlen(bits), ".%s", ubr);
    }
    if (bits[0]) snprintf(display, sizeof(display), "%s", bits);
    SYSTEM_INFO si;
    GetNativeSystemInfo(&si);
    const char *machine = si.wProcessorArchitecture == PROCESSOR_ARCHITECTURE_AMD64 ? "AMD64"
                        : si.wProcessorArchitecture == PROCESSOR_ARCHITECTURE_ARM64 ? "ARM64"
                        : si.wProcessorArchitecture == PROCESSOR_ARCHITECTURE_INTEL ? "x86" : "";
    const char *arch = !strcmp(machine, "x86") ? "x86" : !strcmp(machine, "ARM64") ? "arm64" : "x64";
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "name", "windows");
    cJSON_AddStringToObject(o, "platform", platform);
    cJSON_AddStringToObject(o, "system", "Windows");
    cJSON_AddStringToObject(o, "release", disp[0] ? disp : release);
    cJSON_AddStringToObject(o, "version", build_n[0] ? build_n : version);
    cJSON_AddStringToObject(o, "display", display);
    cJSON_AddStringToObject(o, "arch", arch);
    cJSON_AddStringToObject(o, "machine", machine);
    return o;
}

static void squeeze_spaces(const char *in, char *out, size_t n) {
    size_t o = 0;
    int space = 0;
    for (const char *p = in; *p && o + 1 < n; p++) {
        if (isspace((unsigned char)*p)) { space = o > 0; continue; }
        if (space) { out[o++] = ' '; space = 0; }
        out[o++] = *p;
    }
    out[o] = 0;
}

static cJSON *probe_cpu(void) {
    char name[512];
    reg_str(L"HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0", L"ProcessorNameString", name, sizeof(name), "");
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    long long logical = si.dwNumberOfProcessors, physical = 0;
    cJSON *data = ps_json("Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors | "
                          "ConvertTo-Json -Compress", 6);
    cJSON *rows = cJSON_IsArray(data) ? data : NULL;
    long long cores = 0, logicals = 0;
    cJSON *single[1] = {cJSON_IsObject(data) ? data : NULL};
    cJSON *it;
    if (rows) {
        cJSON_ArrayForEach(it, rows) {
            if (!cJSON_IsObject(it)) continue;
            cores += py_int_or(cJSON_GetObjectItem(it, "NumberOfCores"), 0);
            logicals += py_int_or(cJSON_GetObjectItem(it, "NumberOfLogicalProcessors"), 0);
            const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(it, "Name"));
            if (nm && nm[0]) snprintf(name, sizeof(name), "%s", nm);
        }
    } else if (single[0]) {
        it = single[0];
        cores += py_int_or(cJSON_GetObjectItem(it, "NumberOfCores"), 0);
        logicals += py_int_or(cJSON_GetObjectItem(it, "NumberOfLogicalProcessors"), 0);
        const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(it, "Name"));
        if (nm && nm[0]) snprintf(name, sizeof(name), "%s", nm);
    }
    cJSON_Delete(data);
    physical = cores;
    if (logicals) logical = logicals;
    char sq[512];
    squeeze_spaces(name, sq, sizeof(sq));
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "name", sq);
    cJSON_AddNumberToObject(o, "cores_logical", (double)logical);
    cJSON_AddNumberToObject(o, "cores_physical", (double)physical);
    return o;
}

static const char *k_virtual_gpu[] = {"virtual", "basic render", "basic display", "remote desktop",
                                      "mumu", "parsec", "spacedesk", "usb display", NULL};

static int gpu_rank(cJSON *g) {
    char low[512];
    snprintf(low, sizeof(low), "%s", cJSON_GetStringValue(cJSON_GetObjectItem(g, "name")) ?: "");
    for (char *p = low; *p; p++) *p = (char)tolower((unsigned char)*p);
    for (int i = 0; k_virtual_gpu[i]; i++) if (strstr(low, k_virtual_gpu[i])) return 1;
    return 0;
}

static cJSON *probe_gpus(void) {
    cJSON *data = ps_json("Get-CimInstance Win32_VideoController | Where-Object { $_.Name } | "
                          "Select-Object Name,DriverVersion,AdapterRAM,PNPDeviceID | ConvertTo-Json -Compress", 8);
    cJSON *list = cJSON_CreateArray();
    if (cJSON_IsObject(data)) {
        cJSON *arr = cJSON_CreateArray();
        cJSON_AddItemToArray(arr, data);
        data = arr;
    }
    cJSON *it;
    cJSON_ArrayForEach(it, data) {
        if (!cJSON_IsObject(it)) continue;
        char name[512] = "";
        const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(it, "Name"));
        if (nm) {
            while (*nm && isspace((unsigned char)*nm)) nm++;
            snprintf(name, sizeof(name), "%s", nm);
            size_t len = strlen(name);
            while (len && isspace((unsigned char)name[len - 1])) name[--len] = 0;
        }
        if (!name[0]) continue;
        long long vram = py_int_or(cJSON_GetObjectItem(it, "AdapterRAM"), 0);
        char drv[256] = "", pnp[512] = "";
        cJSON *d = cJSON_GetObjectItem(it, "DriverVersion"), *p = cJSON_GetObjectItem(it, "PNPDeviceID");
        if (py_truthy(d)) py_str(d, drv, sizeof(drv));
        if (py_truthy(p)) py_str(p, pnp, sizeof(pnp));
        cJSON *g = cJSON_CreateObject();
        cJSON_AddStringToObject(g, "name", name);
        cJSON_AddStringToObject(g, "driver", drv);
        cJSON_AddNumberToObject(g, "vram_mb", vram > 0 ? (double)(vram / (1024 * 1024)) : 0);
        cJSON_AddStringToObject(g, "pnp", pnp);
        cJSON_AddItemToArray(list, g);
    }
    cJSON_Delete(data);
    /* sorted(key=rank) 是稳定排序：物理卡在前，各自保持原顺序 */
    cJSON *out = cJSON_CreateArray();
    for (int pass = 0; pass < 2; pass++)
        cJSON_ArrayForEach(it, list) if (gpu_rank(it) == pass) cJSON_AddItemToArray(out, cJSON_Duplicate(it, 1));
    cJSON_Delete(list);
    return out;
}

static cJSON *cached_static(cJSON **slot, ULONGLONG *t, cJSON *(*probe)(void)) {
    ULONGLONG now = GetTickCount64();
    pthread_mutex_lock(&g_mu);
    if (*slot && now - *t < 1800ULL * 1000) {
        cJSON *r = cJSON_Duplicate(*slot, 1);
        pthread_mutex_unlock(&g_mu);
        return r;
    }
    pthread_mutex_unlock(&g_mu);
    cJSON *fresh = probe();
    pthread_mutex_lock(&g_mu);
    cJSON_Delete(*slot);
    *slot = cJSON_Duplicate(fresh, 1);
    *t = GetTickCount64();
    pthread_mutex_unlock(&g_mu);
    return fresh;
}

static cJSON *memory_info(void) {
    MEMORYSTATUSEX m;
    memset(&m, 0, sizeof(m));
    m.dwLength = sizeof(m);
    unsigned long long total = 0, avail = 0;
    unsigned long load = 0;
    if (GlobalMemoryStatusEx(&m)) { total = m.ullTotalPhys; avail = m.ullAvailPhys; load = m.dwMemoryLoad; }
    cJSON *o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "total_mb", total ? (double)(total / (1024 * 1024)) : 0);
    cJSON_AddNumberToObject(o, "avail_mb", avail ? (double)(avail / (1024 * 1024)) : 0);
    cJSON_AddNumberToObject(o, "load_percent", load);
    cJSON_AddNumberToObject(o, "total_bytes", (double)total);
    cJSON_AddNumberToObject(o, "avail_bytes", (double)avail);
    return o;
}

/* round(x, 1)：Python 的 round 是银行家舍入，按 repr 最短值再舍 */
static double py_round1(double x) {
    char buf[64];
    snprintf(buf, sizeof(buf), "%.1f", x);
    return strtod(buf, NULL);
}

static cJSON *disk_info(void) {
    cJSON *out = cJSON_CreateArray(), *seen = cJSON_CreateObject();
    char anchor[8] = "";
    if (isalpha((unsigned char)g_root[0]) && g_root[1] == ':') snprintf(anchor, sizeof(anchor), "%c:\\", g_root[0]);
    const char *cands[3] = {g_root, anchor[0] ? anchor : NULL, "C:\\"};
    for (int i = 0; i < 3; i++) {
        if (!cands[i]) continue;
        wchar_t *w = pymcl_u8_to_wide(cands[i]);
        ULARGE_INTEGER freeb, total, tfree;
        BOOL ok = w && GetDiskFreeSpaceExW(w, &freeb, &total, &tfree);
        free(w);
        if (!ok) continue;
        char key[8];
        if (isalpha((unsigned char)cands[i][0]) && cands[i][1] == ':') snprintf(key, sizeof(key), "%c:\\", cands[i][0]);
        else snprintf(key, sizeof(key), "%.7s", cands[i]);
        if (cJSON_GetObjectItemCaseSensitive(seen, key)) continue;
        cJSON_AddTrueToObject(seen, key);
        cJSON *d = cJSON_CreateObject();
        cJSON_AddStringToObject(d, "path", key);
        cJSON_AddNumberToObject(d, "total_gb", py_round1((double)total.QuadPart / (1024.0 * 1024.0 * 1024.0)));
        cJSON_AddNumberToObject(d, "free_gb", py_round1((double)tfree.QuadPart / (1024.0 * 1024.0 * 1024.0)));
        cJSON_AddItemToArray(out, d);
    }
    cJSON_Delete(seen);
    return out;
}

static cJSON *display_info(void) {
    cJSON *o = cJSON_CreateObject();
    int screens = GetSystemMetrics(80);
    cJSON_AddNumberToObject(o, "width", GetSystemMetrics(0));
    cJSON_AddNumberToObject(o, "height", GetSystemMetrics(1));
    cJSON_AddNumberToObject(o, "screens", screens ? screens : 1);
    return o;
}

static cJSON *java_info(int scan_system) {
    cJSON *rows = cJSON_CreateArray();
    cJSON *javas = scan_system ? java_all() : java_list_installed();
    int i = 0;
    cJSON *j;
    cJSON_ArrayForEach(j, javas) {
        if (i++ >= 16) break;
        cJSON *r = cJSON_CreateObject();
        const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(j, "name"));
        cJSON_AddStringToObject(r, "name", nm ? nm : "");
        cJSON *maj = cJSON_GetObjectItem(j, "major");
        cJSON_AddItemToObject(r, "major", maj ? cJSON_Duplicate(maj, 1) : cJSON_CreateNull());
        const char *exe = cJSON_GetStringValue(cJSON_GetObjectItem(j, "exe"));
        if (!exe || !exe[0]) exe = cJSON_GetStringValue(cJSON_GetObjectItem(j, "path"));
        cJSON_AddStringToObject(r, "path", exe ? exe : "");
        cJSON_AddItemToArray(rows, r);
    }
    cJSON_Delete(javas);
    return rows;
}

static cJSON *instance_info(void) {
    cJSON *rows = cJSON_CreateArray();
    cJSON *names = NULL;
    instance_list(&names);
    int n = 0;
    cJSON *nm;
    cJSON_ArrayForEach(nm, names) {
        if (n++ >= 24) break;
        cJSON *ids = NULL;
        instance_installed_ids(nm->valuestring, &ids);
        while (cJSON_GetArraySize(ids) > 16) cJSON_DeleteItemFromArray(ids, 16);
        char ip[PYMCL_PATH], mods[PYMCL_PATH];
        instance_path(nm->valuestring, ip, sizeof(ip));
        pymcl_path_join(mods, sizeof(mods), ip, "mods");
        int mod_count = 0;
        cJSON *files = pymcl_dir_exists(mods) ? pymcl_list_dir(mods, 0, 0) : cJSON_CreateArray();
        cJSON *f;
        cJSON_ArrayForEach(f, files) if (pymcl_endswith(f->valuestring, ".jar")) mod_count++;
        cJSON_Delete(files);
        char jp[PYMCL_PATH];
        instance_java_pref(nm->valuestring, jp, sizeof(jp));
        cJSON *r = cJSON_CreateObject();
        cJSON_AddStringToObject(r, "name", nm->valuestring);
        cJSON_AddItemToObject(r, "versions", ids);
        cJSON_AddNumberToObject(r, "mod_count", mod_count);
        cJSON_AddStringToObject(r, "java", jp);
        cJSON_AddItemToArray(rows, r);
    }
    cJSON_Delete(names);
    return rows;
}

static void summarize(cJSON *info, char *out, size_t n) {
    cJSON *osd = cJSON_GetObjectItem(info, "os");
    const char *disp = cJSON_GetStringValue(cJSON_GetObjectItem(osd, "display"));
    if (!disp || !disp[0]) disp = cJSON_GetStringValue(cJSON_GetObjectItem(osd, "platform"));
    char cpu[512] = "";
    const char *cn = cJSON_GetStringValue(cJSON_GetObjectItem(cJSON_GetObjectItem(info, "cpu"), "name"));
    if (cn) {
        while (*cn && isspace((unsigned char)*cn)) cn++;
        snprintf(cpu, sizeof(cpu), "%s", cn);
        size_t len = strlen(cpu);
        while (len && isspace((unsigned char)cpu[len - 1])) cpu[--len] = 0;
    }
    long long total_mb = py_int_or(cJSON_GetObjectItem(cJSON_GetObjectItem(info, "memory"), "total_mb"), 0);
    char ram[32] = "";
    if (total_mb) snprintf(ram, sizeof(ram), "%.0fGB", nearbyint((double)total_mb / 1024.0));
    cJSON *gpus = cJSON_GetObjectItem(info, "gpus");
    const char *gpu = cJSON_GetArraySize(gpus) ? cJSON_GetStringValue(cJSON_GetObjectItem(cJSON_GetArrayItem(gpus, 0), "name")) : "";
    const char *parts[4] = {disp ? disp : "", cpu, ram, gpu ? gpu : ""};
    out[0] = 0;
    for (int i = 0; i < 4; i++) {
        if (!parts[i][0]) continue;
        if (out[0]) strncat(out, " · ", n - strlen(out) - 1);
        strncat(out, parts[i], n - strlen(out) - 1);
    }
}

cJSON *sysinfo_collect(int force, int scan_system_java, double max_age) {
    ULONGLONG now = GetTickCount64();
    pthread_mutex_lock(&g_mu);
    if (!force && g_cache && (double)(now - g_cache_t) / 1000.0 < max_age) {
        cJSON *r = cJSON_Duplicate(g_cache, 1);
        pthread_mutex_unlock(&g_mu);
        return r;
    }
    pthread_mutex_unlock(&g_mu);
    cJSON *info = cJSON_CreateObject();
    char stamp[32];
    time_t t = time(NULL);
    struct tm lt;
    localtime_s(&lt, &t);
    strftime(stamp, sizeof(stamp), "%Y-%m-%dT%H:%M:%S", &lt);
    cJSON_AddStringToObject(info, "collected_at", stamp);
    char host[256] = "";
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
    if (gethostname(host, sizeof(host)) != 0) host[0] = 0;
    cJSON_AddStringToObject(info, "hostname", host);
    cJSON_AddItemToObject(info, "os", os_info());
    cJSON_AddItemToObject(info, "cpu", cached_static(&g_cpu, &g_cpu_t, probe_cpu));
    cJSON_AddItemToObject(info, "memory", memory_info());
    cJSON_AddItemToObject(info, "gpus", cached_static(&g_gpus, &g_gpus_t, probe_gpus));
    cJSON_AddItemToObject(info, "disks", disk_info());
    cJSON_AddItemToObject(info, "display", display_info());
    cJSON_AddItemToObject(info, "java", java_info(scan_system_java));
    cJSON *launcher = cJSON_CreateObject();
    cJSON_AddStringToObject(launcher, "name", "PyMCL");
    cJSON_AddStringToObject(launcher, "version", APP_VERSION);
    cJSON_AddBoolToObject(launcher, "frozen", 1);
    cJSON_AddStringToObject(launcher, "python", "");
    cJSON_AddStringToObject(launcher, "root", g_root);
    cJSON *mm = config_get("memory_mb"), *dt = config_get("download_threads");
    cJSON_AddNumberToObject(launcher, "memory_mb", (double)(py_truthy(mm) ? py_int_or(mm, 0) : 0));
    cJSON_AddNumberToObject(launcher, "download_threads", (double)(py_truthy(dt) ? py_int_or(dt, 0) : 0));
    cJSON_AddItemToObject(launcher, "download_source", py_or(config_get("download_source"), cJSON_CreateString("auto")));
    cJSON_AddItemToObject(launcher, "community_source", py_or(config_get("community_source"), cJSON_CreateString("auto")));
    cJSON_AddItemToObject(info, "launcher", launcher);
    cJSON_AddItemToObject(info, "instances", instance_info());
    char summary[2048];
    summarize(info, summary, sizeof(summary));
    cJSON_AddStringToObject(info, "summary", summary);
    pthread_mutex_lock(&g_mu);
    cJSON_Delete(g_cache);
    g_cache = cJSON_Duplicate(info, 1);
    g_cache_t = GetTickCount64();
    pthread_mutex_unlock(&g_mu);
    return info;
}

cJSON *sysinfo_smart_recommendation(void) {
    cJSON *rec = cJSON_CreateObject();
    cJSON_AddNumberToObject(rec, "memory_mb", 4096);
    cJSON_AddNumberToObject(rec, "java_major", 17);
    cJSON_AddNumberToObject(rec, "window_width", 854);
    cJSON_AddNumberToObject(rec, "window_height", 480);
    cJSON_AddStringToObject(rec, "gc_preset", "auto");
    cJSON_AddNumberToObject(rec, "cpu_count", 4);
    cJSON_AddNumberToObject(rec, "total_ram_gb", 8.0);
    cJSON *info = sysinfo_collect(0, 0, 120);
    double total_bytes = cJSON_GetNumberValue(cJSON_GetObjectItem(cJSON_GetObjectItem(info, "memory"), "total_bytes"));
    if (total_bytes > 0) {
        double gb = total_bytes / (1024.0 * 1024.0 * 1024.0);
        int mem = gb >= 32 ? 12288 : gb >= 16 ? 8192 : gb >= 8 ? 4096 : 2048;
        int safe = (int)(gb * 0.75 * 1024);
        if (mem > safe) mem = safe > 1024 ? safe : 1024;
        cJSON_ReplaceItemInObject(rec, "memory_mb", cJSON_CreateNumber(mem));
        cJSON_ReplaceItemInObject(rec, "total_ram_gb", cJSON_CreateNumber(py_round1(gb)));
    }
    cJSON *cpu = cJSON_GetObjectItem(info, "cpu");
    cJSON *cl = cJSON_GetObjectItem(cpu, "cores_logical"), *cp = cJSON_GetObjectItem(cpu, "cores_physical");
    cJSON *pick = py_truthy(cl) ? cl : py_truthy(cp) ? cp : NULL;
    if (pick) cJSON_ReplaceItemInObject(rec, "cpu_count", cJSON_Duplicate(pick, 1));
    cJSON_Delete(info);
    return rec;
}

static void append_line(char *out, size_t cap, const char *line) {
    if (!line[0]) return;
    if (out[0]) strncat(out, "\n", cap - strlen(out) - 1);
    strncat(out, line, cap - strlen(out) - 1);
}

static void num_or(cJSON *v, const char *def, char *out, size_t n) {
    if (py_truthy(v)) py_str(v, out, n);
    else snprintf(out, n, "%s", def);
}

char *sysinfo_format_text(cJSON *info_in) {
    cJSON *data = py_truthy(info_in) ? cJSON_Duplicate(info_in, 1) : sysinfo_collect(0, 0, 120);
    size_t cap = 8192;
    char *out = (char *)calloc(1, cap);
    if (!out) { cJSON_Delete(data); return NULL; }
#define LINE(...) do { char _l[1024]; snprintf(_l, sizeof(_l), __VA_ARGS__); append_line(out, cap, _l); } while (0)
    const char *summary = cJSON_GetStringValue(cJSON_GetObjectItem(data, "summary"));
    LINE("%s", summary ? summary : "");
    cJSON *cpu = cJSON_GetObjectItem(data, "cpu"), *mem = cJSON_GetObjectItem(data, "memory");
    cJSON *disp = cJSON_GetObjectItem(data, "display");
    char a[256], b[64], c[64];
    num_or(cJSON_GetObjectItem(cpu, "name"), "?", a, sizeof(a));
    num_or(cJSON_GetObjectItem(cpu, "cores_physical"), "?", b, sizeof(b));
    num_or(cJSON_GetObjectItem(cpu, "cores_logical"), "?", c, sizeof(c));
    LINE("CPU %s  %sC/%sT", a, b, c);
    char m1[64], m2[64], m3[64];
    num_or(cJSON_GetObjectItem(mem, "total_mb"), "0", m1, sizeof(m1));
    num_or(cJSON_GetObjectItem(mem, "avail_mb"), "0", m2, sizeof(m2));
    num_or(cJSON_GetObjectItem(mem, "load_percent"), "0", m3, sizeof(m3));
    LINE("内存 %s MB  可用 %s MB  占用 %s%%", m1, m2, m3);
    cJSON *gpus = cJSON_GetObjectItem(data, "gpus");
    cJSON *g;
    cJSON_ArrayForEach(g, gpus) {
        char nm[256], vram[64] = "", drv[300] = "";
        py_str(cJSON_GetObjectItem(g, "name"), nm, sizeof(nm));
        cJSON *vr = cJSON_GetObjectItem(g, "vram_mb"), *dv = cJSON_GetObjectItem(g, "driver");
        if (py_truthy(vr)) { char t[32]; py_str(vr, t, sizeof(t)); snprintf(vram, sizeof(vram), "  %s MB", t); }
        if (py_truthy(dv)) { char t[256]; py_str(dv, t, sizeof(t)); snprintf(drv, sizeof(drv), "  驱动 %s", t); }
        LINE("显卡 %s%s%s", nm, vram, drv);
    }
    if (!cJSON_GetArraySize(gpus)) LINE("显卡 未检测到");
    if (py_truthy(cJSON_GetObjectItem(disp, "width"))) {
        char w[32], h[32], s[32];
        py_str(cJSON_GetObjectItem(disp, "width"), w, sizeof(w));
        py_str(cJSON_GetObjectItem(disp, "height"), h, sizeof(h));
        num_or(cJSON_GetObjectItem(disp, "screens"), "1", s, sizeof(s));
        LINE("分辨率 %s×%s  屏幕 %s", w, h, s);
    }
    cJSON *d;
    cJSON_ArrayForEach(d, cJSON_GetObjectItem(data, "disks")) {
        char p[64], f[64], t2[64];
        py_str(cJSON_GetObjectItem(d, "path"), p, sizeof(p));
        py_str(cJSON_GetObjectItem(d, "free_gb"), f, sizeof(f));
        py_str(cJSON_GetObjectItem(d, "total_gb"), t2, sizeof(t2));
        LINE("磁盘 %s  %s / %s GB 可用", p, f, t2);
    }
    cJSON *javas = cJSON_GetObjectItem(data, "java");
    if (cJSON_GetArraySize(javas)) {
        char line[1024] = "Java ";
        int i = 0;
        cJSON *j;
        cJSON_ArrayForEach(j, javas) {
            if (i >= 6) break;
            char maj[32], item[400];
            num_or(cJSON_GetObjectItem(j, "major"), "?", maj, sizeof(maj));
            const char *p = cJSON_GetStringValue(cJSON_GetObjectItem(j, "path"));
            snprintf(item, sizeof(item), "%s%s(%s)", i ? ", " : "", maj, pymcl_basename(p ? p : ""));
            strncat(line, item, sizeof(line) - strlen(line) - 1);
            i++;
        }
        LINE("%s", line);
    }
    cJSON *launch = cJSON_GetObjectItem(data, "launcher");
    char lv[64], lp[64], lm[64];
    py_str(cJSON_GetObjectItem(launch, "version"), lv, sizeof(lv));
    py_str(cJSON_GetObjectItem(launch, "python"), lp, sizeof(lp));
    py_str(cJSON_GetObjectItem(launch, "memory_mb"), lm, sizeof(lm));
    LINE("启动器 %s  Python %s  内存默认 %s MB", lv, lp, lm);
    cJSON *inst;
    cJSON_ArrayForEach(inst, cJSON_GetObjectItem(data, "instances")) {
        char vers[1024] = "";
        cJSON *v;
        cJSON_ArrayForEach(v, cJSON_GetObjectItem(inst, "versions")) {
            if (vers[0]) strncat(vers, ", ", sizeof(vers) - strlen(vers) - 1);
            strncat(vers, v->valuestring ? v->valuestring : "", sizeof(vers) - strlen(vers) - 1);
        }
        char nm[256], mc[32];
        py_str(cJSON_GetObjectItem(inst, "name"), nm, sizeof(nm));
        num_or(cJSON_GetObjectItem(inst, "mod_count"), "0", mc, sizeof(mc));
        LINE("实例 %s  %s  mods=%s", nm, vers[0] ? vers : "无版本", mc);
    }
#undef LINE
    cJSON_Delete(data);
    return out;
}

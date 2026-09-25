#include "pymcl.h"
#include <bcrypt.h>
#include <ctype.h>
#include <pthread.h>
#include <shellapi.h>
#include <stdarg.h>
#include <zlib.h>

/* mclauncher/terracotta.py 与 bridge/api.py 里陶瓦联机 11 个方法的移植
   （docs/GOAL-c-bridge-no-python.md M4）。状态机、文案、端口文件、节点表、
   servers.dat 的写法都照 Python 参考实现；terracotta.py 里的文案本来就不走 tr()，
   只有 api.py 那几句走。 */

#define TC_VERSION "0.4.2"
#define TC_NODE_LIST_URL "https://terracotta.glavo.site/nodes"
#define TC_HMCL_CUSTOM_NODE "https://terracotta.glavo.site/acebc7d8-1208-47fd-b212-d03ac49e36e0"
#define TC_HOME "https://github.com/burningtnt/Terracotta"
#define TC_COPYRIGHT "Terracotta | 陶瓦联机  © burningtnt  ·  基于 EasyTier"
#define TC_LOBBY_NAME "陶瓦联机大厅"

static const char ROOM_CHARS[] = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ";

typedef struct { const char *name, *sha512; } tc_file;
typedef struct { const char *cls, *hash, *exe; tc_file files[2]; } tc_pkg;

/* SHA-512，与 HMCL terracotta.json 0.4.2 一致（C 桥只跑 Windows，只留 Windows 两个包） */
static const tc_pkg PKGS[] = {
    {"windows-x86_64",
     "6a98f524d4f00373696517306af8aa50d01d55ce4eadb27e9e4bc2f882707a0b5f20d5d4c33371d1459dcf5bf144ffed9beb414202d9ccf32b11dbbfcf19d650",
     "terracotta-0.4.2-windows-x86_64.exe",
     {{"VCRUNTIME140.DLL",
       "3d4b24061f72c0e957c7b04a0c4098c94c8f1afb4a7e159850b9939c7210d73398be6f27b5ab85073b4e8c999816e7804fef0f6115c39cd061f4aaeb4dcda8cf"},
      {"terracotta-0.4.2-windows-x86_64.exe",
       "6e98d1f2380ed22fb5a2dd4aafce6c773e9cf69100c8bb8e49e7d6983756bdb9a31f80e06bcfbe5a2742144fe806d3d687dec54d8f09d87c659341f99dd9fd80"}}},
    {"windows-arm64",
     "fc1077247014ac0c712469498bde2ef7f6d881d5fcb7bdd5e11ebe20218fed365be19afdb8d453a79d77b729f866058522b910741767f4df947faa891434b463",
     "terracotta-0.4.2-windows-arm64.exe",
     {{"VCRUNTIME140.DLL",
       "5cb5ce114614101d260f4754c09e8a0dd57e4da885ebb96b91e274326f3e1dd95ed0ade9f542f1922fad0ed025e88a1f368e791e1d01fae69718f0ec3c7b98c8"},
      {"terracotta-0.4.2-windows-arm64.exe",
       "30a15c5c53e5817c5a3634532172559327474741d3b2c7ef4e8a30acc6f59cdcf3570bf5f583e3cbe9e2abc8253e977c1abda1e9f36c88c4e99240da257347d0"}}},
};

static const char *EXC[] = {
    "加入房间失败：找不到房主。房间已关闭，或尚未连上公共中继",
    "房间连接断开：房间已关闭或网络不稳定",
    "加入房间失败：EasyTier 已崩溃，请向开发者反馈该问题",
    "创建房间失败：EasyTier 已崩溃，请向开发者反馈该问题",
    "房间已关闭：您已退出游戏世界，房间已自动关闭",
    "协议错误：房主发送了错误的响应数据，请向开发者反馈该问题",
};

static const char PING_HOST_HINT[] =
    "陶瓦是 EasyTier P2P 打洞，不是 FRP 隧道。官方公共节点连不上时，必须和 HMCL 用同一条自定义会合节点。"
    "请完全退出后重试；已带上本机 HMCL 成功加入时用的那条 terracotta.glavo.site 节点。";

typedef struct { const char *k, *v; } kv_t;

static const kv_t DIFF[] = {
    {"EASIEST", "当前网络状态极好：稍等一下就成功！"},
    {"SIMPLE", "当前网络状态较好：建立连接需要一段时间……"},
    {"MEDIUM", "当前网络状态中等：已启用抗干扰备用线路，连接可能失败"},
    {"TOUGH", "当前网络状态极差：已启用抗干扰备用线路，连接可能失败"},
};

static const kv_t STATE_LABEL[] = {
    {"missing", "未下载联机核心"},
    {"unsupported", "当前系统架构暂不支持陶瓦联机"},
    {"installing", "正在下载联机核心…"},
    {"launching", "正在初始化联机核心"},
    {"unknown", "正在初始化联机核心"},
    {"waiting", "联机核心已就绪"},
    {"host-scanning", "正在扫描局域网世界"},
    {"host-starting", "正在启动房间"},
    {"host-ok", "已启动房间"},
    {"guest-connecting", "正在加入房间"},
    {"guest-starting", "正在加入房间"},
    {"guest-ok", "已加入房间"},
    {"exception", "联机出错"},
    {"fatal", "联机内核已停止"},
};

static pthread_mutex_t g_start_mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;
static HANDLE g_proc;
static volatile int g_port;
static cJSON *g_nodes;
static cJSON *g_allowed_fw;
static char g_last_lobby[PYMCL_PATH * 2];

static const char *kv_get(const kv_t *t, size_t n, const char *k, const char *def) {
    for (size_t i = 0; i < n; i++)
        if (strcmp(t[i].k, k) == 0) return t[i].v;
    return def;
}

static const char *state_label(const char *k) {
    return kv_get(STATE_LABEL, sizeof(STATE_LABEL) / sizeof(STATE_LABEL[0]), k, k);
}

static const char *pstr(cJSON *o, const char *k, const char *def) {
    const char *s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, k));
    return s ? s : def;
}

/* ---------- Python str 语义的小工具 ---------- */

static uint32_t u8_next(const unsigned char **p) {
    const unsigned char *s = *p;
    uint32_t c = *s;
    int n = c < 0x80 ? 1 : (c >> 5) == 6 ? 2 : (c >> 4) == 14 ? 3 : (c >> 3) == 30 ? 4 : 1;
    if (n == 1) { *p = s + 1; return c; }
    c &= 0x3F >> (n - 1);
    for (int i = 1; i < n; i++) {
        if ((s[i] & 0xC0) != 0x80) { *p = s + 1; return s[0]; }
        c = (c << 6) | (s[i] & 0x3F);
    }
    *p = s + n;
    return c;
}

static int py_space(uint32_t c) {
    return c == ' ' || (c >= 0x09 && c <= 0x0D) || (c >= 0x1C && c <= 0x1F) || c == 0x85 || c == 0xA0
        || c == 0x1680 || (c >= 0x2000 && c <= 0x200A) || c == 0x2028 || c == 0x2029 || c == 0x202F
        || c == 0x205F || c == 0x3000;
}

/* str.strip()：去 Unicode 空白，返回 malloc 的新串 */
static char *py_strip(const char *s) {
    const unsigned char *p = (const unsigned char *)(s ? s : "");
    const unsigned char *start = p, *end = p;
    int seen = 0;
    while (*p) {
        const unsigned char *at = p;
        uint32_t c = u8_next(&p);
        if (!py_space(c)) {
            if (!seen) { start = at; seen = 1; }
            end = p;
        }
    }
    if (!seen) return pymcl_strdup("");
    size_t n = (size_t)(end - start);
    char *out = (char *)malloc(n + 1);
    if (!out) return pymcl_strdup("");
    memcpy(out, start, n);
    out[n] = 0;
    return out;
}

/* 按字符（码点）切开并转大写（只动 ASCII），给房间号算法用 */
static int to_upper_codepoints(const char *s, uint32_t **out) {
    size_t cap = strlen(s ? s : "") + 1;
    uint32_t *a = (uint32_t *)malloc(cap * sizeof(uint32_t));
    int n = 0;
    if (!a) { *out = NULL; return 0; }
    const unsigned char *p = (const unsigned char *)(s ? s : "");
    while (*p) {
        uint32_t c = u8_next(&p);
        if (c < 128) c = (uint32_t)toupper((int)c);
        a[n++] = c;
    }
    *out = a;
    return n;
}

/* ---------- 房间号（burningtnt/Terracotta v0.4.2 room.rs） ---------- */

static int room_digit(uint32_t c) {
    if (c == 'I') c = '1';
    else if (c == 'O') c = '0';
    if (c == 0 || c > 127) return -1;
    const char *hit = strchr(ROOM_CHARS, (int)c);
    return hit ? (int)(hit - ROOM_CHARS) : -1;
}

static void room_from_value(unsigned __int128 value, char out[32]) {
    int k = 0;
    out[k++] = 'U';
    out[k++] = '/';
    for (int i = 0; i < 16; i++) {
        char ch = ROOM_CHARS[(int)(value % 34)];
        value /= 34;
        if (i == 4 || i == 8 || i == 12) out[k++] = '-';
        out[k++] = ch;
    }
    out[k] = 0;
}

/* parse_room：滑动窗口找 U/XXXX-XXXX-XXXX-XXXX，种子须能被 7 整除；找到返回 1 */
static int parse_room(const char *text, char out[32]) {
    uint32_t *c;
    int n = to_upper_codepoints(text, &c);
    int found = 0;
    const int width = 21;
    for (int start = 0; c && start + width <= n && !found; start++) {
        if (c[start] != 'U' || c[start + 1] != '/') continue;
        const uint32_t *body = c + start + 2;
        unsigned __int128 value = 0;
        int ok = 1;
        for (int i = 18; i >= 0; i--) {
            if (i == 4 || i == 9 || i == 14) {
                if (body[i] != '-') { ok = 0; break; }
                continue;
            }
            int d = room_digit(body[i]);
            if (d < 0) { ok = 0; break; }
            value = value * 34 + (unsigned)d;
        }
        if (ok && value % 7 == 0) {
            room_from_value(value, out);
            found = 1;
        }
    }
    free(c);
    return found;
}

static int looks_like_legacy_room(const char *text) {
    uint32_t *c;
    int n = to_upper_codepoints(text, &c);
    int hit = 0;
    for (int start = 0; c && start + 29 <= n && !hit; start++) {
        const uint32_t *seg = c + start;
        int array[25], cnt = 0, good = 1;
        for (int i = 0; i < 5 && good; i++) {
            for (int j = 0; j < 5; j++) {
                int v = room_digit(seg[i * 6 + j]);
                if (v < 0) { good = 0; break; }
                array[cnt++] = v;
            }
            if (good && i != 4 && seg[i * 6 + 5] != '-') good = 0;
        }
        if (!good || cnt != 25) continue;
        int checking = 0;
        for (int i = 0; i < 24; i++) checking = (checking + array[i]) % 34;
        if (checking == array[24]) hit = 1;
    }
    free(c);
    return hit;
}

static int looks_like_pcl2ce_room(const char *text) {
    char *raw = py_strip(text);
    uint32_t *c;
    int n = to_upper_codepoints(raw, &c);
    free(raw);
    int res = 0;
    if (c && n > 0 && n <= 10) {
        unsigned long long value = 0;
        int ok = 1;
        for (int i = 0; i < n; i++) {
            uint32_t ch = c[i];
            if (ch >= '2' && ch <= '9') value = value * 32 + (ch - '2');
            else if (ch >= 'A' && ch <= 'H') value = value * 32 + (ch - 'A' + 8);
            else if (ch >= 'J' && ch <= 'N') value = value * 32 + (ch - 'J' + 16);
            else if (ch >= 'P' && ch <= 'Z') value = value * 32 + (ch - 'P' + 21);
            else { ok = 0; break; }
        }
        if (ok && value < 999999999965536ULL) {
            char s[32];
            snprintf(s, sizeof(s), "%llu", value);
            size_t len = strlen(s);
            if (len == 14) res = 1;
            else if (len == 15) res = (value % 100000) < 65536;
        }
    }
    free(c);
    return res;
}

static const char *room_error(const char *text) {
    char *raw = py_strip(text);
    const char *msg;
    char up[1024];
    snprintf(up, sizeof(up), "%s", raw);
    for (char *q = up; *q; q++) *q = (char)toupper((unsigned char)*q);
    if (!raw[0]) msg = "请输入房间号。";
    else if (looks_like_legacy_room(raw))
        msg = "这是陶瓦旧版房间号。官方 0.4.2 已移除 TerracottaLegacy 格式，"
              "请让房主用当前陶瓦 / HMCL 重新开房（房间号以 U/ 开头）。";
    else if (looks_like_pcl2ce_room(raw))
        msg = "这是 PCL CE 旧房间号。官方 0.4.2 已移除 PCL2CE 格式，"
              "请双方都用当前陶瓦 / HMCL 开房，房间号形如 U/XXXX-XXXX-XXXX-XXXX。";
    else if (strstr(up, "U/") || up[0] == 'U')
        msg = "房间号校验失败。请向房主重新复制完整的 U/XXXX-XXXX-XXXX-XXXX。";
    else
        msg = "房间号须为陶瓦 0.4.2 格式 U/XXXX-XXXX-XXXX-XXXX。"
              "官方内核已不再接受旧版 PCL / 旧陶瓦房间号。";
    free(raw);
    return msg;
}

/* ---------- 内核包与路径 ---------- */

static const tc_pkg *package_meta(void) {
    if (!pymcl_is_windows()) return NULL;
    const char *cls = strcmp(pymcl_arch(), "arm64") == 0 ? "windows-arm64" : "windows-x86_64";
    for (size_t i = 0; i < sizeof(PKGS) / sizeof(PKGS[0]); i++)
        if (strcmp(PKGS[i].cls, cls) == 0) return &PKGS[i];
    return NULL;
}

static void install_dir(char *out, size_t n) { pymcl_path_join3(out, n, g_root, "terracotta", TC_VERSION); }

static int executable(char *out, size_t n) {
    const tc_pkg *meta = package_meta();
    if (!meta) { pymcl_set_error("当前系统架构暂不支持陶瓦联机。"); return -1; }
    char dir[PYMCL_PATH];
    install_dir(dir, sizeof(dir));
    pymcl_path_join(out, n, dir, meta->exe);
    return 0;
}

static int is_installed(void) {
    const tc_pkg *meta = package_meta();
    if (!meta) return 0;
    char dir[PYMCL_PATH], p[PYMCL_PATH];
    install_dir(dir, sizeof(dir));
    for (int i = 0; i < 2; i++) {
        pymcl_path_join(p, sizeof(p), dir, meta->files[i].name);
        if (!pymcl_file_exists(p)) return 0;
    }
    pymcl_path_join(p, sizeof(p), dir, meta->exe);
    return pymcl_file_exists(p);
}

static void runtime_file(char *out, size_t n) { pymcl_path_join3(out, n, g_root, "terracotta", "runtime.json"); }

static int json_port(cJSON *data) {
    cJSON *v = cJSON_GetObjectItemCaseSensitive(data, "port");
    if (cJSON_IsNumber(v)) return (int)v->valuedouble;
    if (cJSON_IsString(v) && v->valuestring[0]) {
        char *end;
        long x = strtol(v->valuestring, &end, 10);
        return *end ? 0 : (int)x;
    }
    return 0;
}

static void save_port(int port) {
    g_port = port;
    if (!port) return;
    char path[PYMCL_PATH], dir[PYMCL_PATH];
    runtime_file(path, sizeof(path));
    pymcl_parent(path, dir, sizeof(dir));
    pymcl_ensure_dir(dir);
    cJSON *o = cJSON_CreateObject();
    cJSON_AddNumberToObject(o, "port", port);
    pymcl_write_json(path, o);
    cJSON_Delete(o);
}

static int load_port(void) {
    char path[PYMCL_PATH];
    runtime_file(path, sizeof(path));
    cJSON *data = pymcl_read_json(path);
    int port = cJSON_IsObject(data) ? json_port(data) : 0;
    cJSON_Delete(data);
    return port;
}

/* ---------- 本机内核 HTTP ---------- */

static int core_get(int port, const char *path_q, int timeout, http_resp *r) {
    char url[4096];
    snprintf(url, sizeof(url), "http://127.0.0.1:%d%s", port, path_q);
    return http_get(url, r, NULL, timeout);
}

static int http_ok(int port) {
    if (!port) return 0;
    http_resp r;
    int rc = core_get(port, "/state", 2, &r);
    int ok = rc == 0 || (r.status > 0 && r.status < 500);
    http_resp_free(&r);
    return ok;
}

static int tc_running(void) {
    if (http_ok(g_port)) return 1;
    int saved = load_port();
    if (saved && saved != g_port && http_ok(saved)) {
        g_port = saved;
        return 1;
    }
    return 0;
}

static cJSON *core_json(int port, const char *path_q, int timeout) {
    http_resp r;
    cJSON *j = NULL;
    if (core_get(port, path_q, timeout, &r) == 0 && r.body) j = cJSON_Parse(r.body);
    http_resp_free(&r);
    return j;
}

static void quote_plus(const char *s, char *out, size_t n) {
    static const char hex[] = "0123456789ABCDEF";
    size_t k = 0;
    for (const unsigned char *p = (const unsigned char *)s; *p && k + 4 < n; p++) {
        if (isalnum(*p) || *p == '_' || *p == '.' || *p == '-' || *p == '~') out[k++] = (char)*p;
        else if (*p == ' ') out[k++] = '+';
        else { out[k++] = '%'; out[k++] = hex[*p >> 4]; out[k++] = hex[*p & 15]; }
    }
    out[k] = 0;
}

static const char *reason_phrase(int status) {
    switch (status) {
    case 401: return "Unauthorized";
    case 403: return "Forbidden";
    case 404: return "Not Found";
    case 405: return "Method Not Allowed";
    case 409: return "Conflict";
    case 500: return "Internal Server Error";
    case 502: return "Bad Gateway";
    case 503: return "Service Unavailable";
    default: return "";
    }
}

/* _http：pairs 是 [[key, value], …]，空值跳过；返回 JSON 或原文字符串 */
static cJSON *tc_http(const char *path, cJSON *pairs, int timeout) {
    int port = g_port;
    if (!port) { pymcl_set_error("联机内核尚未就绪。"); return NULL; }
    size_t cap = 8192;
    char *q = (char *)calloc(1, cap);
    if (!q) { pymcl_set_error("内存不足"); return NULL; }
    snprintf(q, cap, "%s", path);
    int first = 1;
    cJSON *pair;
    cJSON_ArrayForEach(pair, pairs) {
        const char *k = cJSON_GetStringValue(cJSON_GetArrayItem(pair, 0));
        const char *v = cJSON_GetStringValue(cJSON_GetArrayItem(pair, 1));
        if (!k || !v || !v[0]) continue;
        char ek[512], ev[2048];
        quote_plus(k, ek, sizeof(ek));
        quote_plus(v, ev, sizeof(ev));
        size_t len = strlen(q);
        snprintf(q + len, cap - len, "%s%s=%s", first ? "?" : "&", ek, ev);
        first = 0;
    }
    char url[8300];
    snprintf(url, sizeof(url), "http://127.0.0.1:%d%s", port, q);
    free(q);
    http_resp r;
    int rc = http_get(url, &r, NULL, timeout);
    if (r.status == 400) {
        http_resp_free(&r);
        pymcl_set_error("联机内核拒绝了这次请求。房间号须为 U/XXXX-XXXX-XXXX-XXXX，且内核要处于就绪状态。");
        return NULL;
    }
    if (rc != 0) {
        if (r.status >= 400)
            pymcl_set_error("%d %s Error: %s for url: %s", r.status, r.status < 500 ? "Client" : "Server",
                            reason_phrase(r.status), url);
        http_resp_free(&r);
        return NULL;
    }
    const char *text = r.body ? r.body : "";
    cJSON *out = NULL;
    if (text[0] == '{' || text[0] == '[') out = cJSON_Parse(text);
    if (!out) out = cJSON_CreateString(text);
    http_resp_free(&r);
    return out;
}

static int read_port_file(const char *path) {
    if (!pymcl_file_exists(path)) return 0;
    cJSON *data = pymcl_read_json(path);
    int port = cJSON_IsObject(data) ? json_port(data) : 0;
    cJSON_Delete(data);
    return port;
}

static void kernel_version(int port, char *out, size_t n) {
    out[0] = 0;
    cJSON *j = core_json(port, "/meta", 2);
    const char *v = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(j, "version"));
    if (v) snprintf(out, n, "%s", v);
    cJSON_Delete(j);
}

static void peaceful_stop(int port) {
    http_resp r;
    core_get(port, "/panic?peaceful=true", 2, &r);
    http_resp_free(&r);
}

static void recover_waiting(void) {
    int port = g_port;
    if (!port) return;
    cJSON *j = core_json(port, "/state", 2);
    const char *st = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(j, "state"));
    if (st && strcmp(st, "exception") == 0) {
        http_resp r;
        core_get(port, "/state/ide", 2, &r);
        http_resp_free(&r);
    }
    cJSON_Delete(j);
}

/* ---------- 公共节点 ---------- */

static int is_china_mainland(void) {
    wchar_t w[LOCALE_NAME_MAX_LENGTH];
    if (!GetUserDefaultLocaleName(w, LOCALE_NAME_MAX_LENGTH)) return 1;
    char tag[LOCALE_NAME_MAX_LENGTH];
    int k = 0;
    for (int i = 0; w[i] && k < LOCALE_NAME_MAX_LENGTH - 1; i++)
        tag[k++] = w[i] == L'-' ? '_' : (char)tolower((int)(w[i] & 0x7F));
    tag[k] = 0;
    if (!tag[0]) return 1;
    if (pymcl_startswith(tag, "zh_tw") || pymcl_startswith(tag, "zh_hk") || pymcl_startswith(tag, "zh_mo"))
        return 0;
    return pymcl_startswith(tag, "zh");
}

/* HMCL TerracottaNode.validate：urlparse 得有 scheme 和 netloc */
static int valid_node_url(const char *url) {
    const char *p = url;
    if (!isalpha((unsigned char)*p)) return 0;
    while (isalnum((unsigned char)*p) || *p == '+' || *p == '-' || *p == '.') p++;
    if (*p != ':' || p[1] != '/' || p[2] != '/') return 0;
    p += 3;
    return *p && *p != '/' && *p != '?' && *p != '#';
}

static void add_node(cJSON *listed, const char *raw) {
    char *url = py_strip(raw);
    int dup = 0;
    cJSON *it;
    cJSON_ArrayForEach(it, listed) if (strcmp(it->valuestring, url) == 0) dup = 1;
    if (url[0] && !dup && valid_node_url(url)) cJSON_AddItemToArray(listed, cJSON_CreateString(url));
    free(url);
}

static cJSON *public_nodes(void) {
    pthread_mutex_lock(&g_mu);
    if (g_nodes) {
        cJSON *c = cJSON_Duplicate(g_nodes, 1);
        pthread_mutex_unlock(&g_mu);
        return c;
    }
    pthread_mutex_unlock(&g_mu);
    cJSON *listed = cJSON_CreateArray();
    add_node(listed, TC_HMCL_CUSTOM_NODE);
    cJSON *extra = config_get("terracotta_extra_nodes");
    if (cJSON_IsString(extra)) add_node(listed, extra->valuestring);
    else if (cJSON_IsArray(extra)) {
        cJSON *it;
        cJSON_ArrayForEach(it, extra) if (cJSON_IsString(it)) add_node(listed, it->valuestring);
    }
    cJSON *rows = http_get_json(TC_NODE_LIST_URL, 10);
    if (cJSON_IsArray(rows)) {
        int mainland = is_china_mainland();
        cJSON *row;
        cJSON_ArrayForEach(row, rows) {
            if (!cJSON_IsObject(row)) continue;
            char *url = py_strip(pstr(row, "url", ""));
            char *region = py_strip(pstr(row, "region", ""));
            if (url[0] && valid_node_url(url)) {
                int region_cn = pymcl_ieq(region, "cn");
                if (!region[0] || mainland == region_cn) add_node(listed, url);
            }
            free(url);
            free(region);
        }
    }
    cJSON_Delete(rows);
    pthread_mutex_lock(&g_mu);
    if (!g_nodes) g_nodes = cJSON_Duplicate(listed, 1);
    pthread_mutex_unlock(&g_mu);
    return listed;
}

/* ---------- 内核启停 ---------- */

static void wlog(pymcl_ctx *ctx, const char *fmt, ...) {
    if (!ctx || !ctx->on_log) return;
    char buf[1024];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    ctx->on_log(ctx->ud, buf);
}

static int make_temp_dir(char *out, size_t n) {
    wchar_t tmp[MAX_PATH];
    if (!GetTempPathW(MAX_PATH, tmp)) return -1;
    char *base = pymcl_wide_to_u8(tmp);
    if (!base) return -1;
    for (int i = 0; i < 20; i++) {
        unsigned char rnd[4];
        BCryptGenRandom(NULL, rnd, sizeof(rnd), BCRYPT_USE_SYSTEM_PREFERRED_RNG);
        char name[64];
        snprintf(name, sizeof(name), "pymcl-terracotta-%02x%02x%02x%02x", rnd[0], rnd[1], rnd[2], rnd[3]);
        pymcl_path_join(out, n, base, name);
        wchar_t *w = pymcl_u8_to_wide(out);
        BOOL ok = w && CreateDirectoryW(w, NULL);
        free(w);
        if (ok) { free(base); return 0; }
    }
    free(base);
    return -1;
}

static HANDLE spawn_kernel(const char *exe, const char *marker) {
    char dir[PYMCL_PATH], cmd[PYMCL_PATH * 3];
    pymcl_parent(exe, dir, sizeof(dir));
    snprintf(cmd, sizeof(cmd), "\"%s\" --hmcl \"%s\"", exe, marker);
    wchar_t *wexe = pymcl_u8_to_wide(exe), *wcmd = pymcl_u8_to_wide(cmd), *wdir = pymcl_u8_to_wide(dir);
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof(si));
    memset(&pi, 0, sizeof(pi));
    si.cb = sizeof(si);
    BOOL ok = wexe && wcmd && CreateProcessW(wexe, wcmd, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, wdir, &si, &pi);
    free(wexe);
    free(wcmd);
    free(wdir);
    if (!ok) return NULL;
    CloseHandle(pi.hThread);
    return pi.hProcess;
}

/* start：拉起官方内核，等它写出本地 HTTP 端口；成功返回端口，失败 -1 */
static int tc_start(pymcl_ctx *ctx) {
    pthread_mutex_lock(&g_start_mu);
    char last_error[512] = {0};
    for (int attempt = 0; attempt < 2; attempt++) {
        if (tc_running()) {
            char ver[64];
            kernel_version(g_port, ver, sizeof(ver));
            if (ver[0] && strcmp(ver, TC_VERSION) != 0 && attempt == 0) {
                wlog(ctx, "发现其它版本陶瓦内核 %s，正在切换到官方 %s", ver, TC_VERSION);
                peaceful_stop(g_port);
                Sleep(3000);
                g_port = 0;
                continue;
            }
            recover_waiting();
            wlog(ctx, "联机内核已在运行（127.0.0.1:%d）", g_port);
            int port = g_port;
            pthread_mutex_unlock(&g_start_mu);
            return port;
        }
        char exe[PYMCL_PATH];
        if (executable(exe, sizeof(exe)) != 0) { pthread_mutex_unlock(&g_start_mu); return -1; }
        if (!pymcl_file_exists(exe)) {
            pthread_mutex_unlock(&g_start_mu);
            pymcl_set_error("请先安装陶瓦联机内核。");
            return -1;
        }
        char tmp[PYMCL_PATH], marker[PYMCL_PATH];
        if (make_temp_dir(tmp, sizeof(tmp)) != 0) {
            pthread_mutex_unlock(&g_start_mu);
            pymcl_set_error("无法创建临时目录");
            return -1;
        }
        pymcl_path_join(marker, sizeof(marker), tmp, "http");
        wlog(ctx, "启动 %s", pymcl_basename(exe));
        HANDLE proc = spawn_kernel(exe, marker);
        if (!proc) {
            pthread_mutex_unlock(&g_start_mu);
            pymcl_set_error("无法启动陶瓦联机内核。");
            return -1;
        }
        pthread_mutex_lock(&g_mu);
        if (g_proc) CloseHandle(g_proc);
        g_proc = proc;
        pthread_mutex_unlock(&g_mu);
        int port = 0;
        ULONGLONG deadline = GetTickCount64() + 40000;
        last_error[0] = 0;
        while (GetTickCount64() < deadline) {
            port = read_port_file(marker);
            if (port) break;
            DWORD code = STILL_ACTIVE;
            GetExitCodeProcess(proc, &code);
            if (code == STILL_ACTIVE) { Sleep(150); continue; }
            if (code == 0) {
                for (int i = 0; i < 10 && !port; i++) {
                    port = read_port_file(marker);
                    if (!port) Sleep(200);
                }
                if (port) break;
                snprintf(last_error, sizeof(last_error), "陶瓦联机已退出，但没有写出端口文件。");
                break;
            }
            snprintf(last_error, sizeof(last_error), "陶瓦联机进程提前退出，代码 %lu。", (unsigned long)code);
            break;
        }
        if (!port) {
            TerminateProcess(proc, 1);
            if (last_error[0] && attempt == 1) {
                pthread_mutex_unlock(&g_start_mu);
                pymcl_set_error("%s", last_error);
                return -1;
            }
            if (!last_error[0]) snprintf(last_error, sizeof(last_error), "等待联机内核端口超时。");
            continue;
        }
        save_port(port);
        ULONGLONG ready_until = GetTickCount64() + 20000;
        while (GetTickCount64() < ready_until && !http_ok(port)) Sleep(200);
        if (!http_ok(port)) {
            pthread_mutex_unlock(&g_start_mu);
            pymcl_set_error("端口 %d 已写出，但联机接口还没有响应。", port);
            return -1;
        }
        char ver[64];
        kernel_version(port, ver, sizeof(ver));
        if (ver[0] && strcmp(ver, TC_VERSION) != 0 && attempt == 0) {
            wlog(ctx, "发现其它版本陶瓦内核 %s，正在切换到官方 %s", ver, TC_VERSION);
            peaceful_stop(port);
            Sleep(3000);
            g_port = 0;
            continue;
        }
        pthread_mutex_lock(&g_mu);
        DWORD code = 0;
        if (g_proc && GetExitCodeProcess(g_proc, &code) && code != STILL_ACTIVE) {
            CloseHandle(g_proc);
            g_proc = NULL;
        }
        pthread_mutex_unlock(&g_mu);
        recover_waiting();
        wlog(ctx, "联机内核已就绪（127.0.0.1:%d）", port);
        pthread_mutex_unlock(&g_start_mu);
        return port;
    }
    pthread_mutex_unlock(&g_start_mu);
    pymcl_set_error("%s", last_error[0] ? last_error : "无法启动陶瓦联机内核。");
    return -1;
}

static void tc_stop(void) {
    int port = g_port ? g_port : load_port();
    if (port) peaceful_stop(port);
    pthread_mutex_lock(&g_mu);
    HANDLE proc = g_proc;
    g_proc = NULL;
    g_port = 0;
    pthread_mutex_unlock(&g_mu);
    if (proc) {
        DWORD code = 0;
        if (GetExitCodeProcess(proc, &code) && code == STILL_ACTIVE) {
            TerminateProcess(proc, 1);
            WaitForSingleObject(proc, 3000);
        }
        CloseHandle(proc);
    }
    char path[PYMCL_PATH];
    runtime_file(path, sizeof(path));
    wchar_t *w = pymcl_u8_to_wide(path);
    if (w) { DeleteFileW(w); free(w); }
}

/* ---------- 安装：下载官方平台包，解出 tar.gz 里要的文件并逐个校验 ---------- */

static int gunzip_all(const char *path, unsigned char **out, size_t *out_len) {
    char *raw = NULL;
    size_t raw_len = 0;
    if (pymcl_read_file(path, &raw, &raw_len) != 0) return -1;
    z_stream z;
    memset(&z, 0, sizeof(z));
    if (inflateInit2(&z, 16 + MAX_WBITS) != Z_OK) { free(raw); return -1; }
    size_t cap = raw_len * 3 + 65536, len = 0;
    unsigned char *buf = (unsigned char *)malloc(cap);
    int rc = Z_OK;
    z.next_in = (Bytef *)raw;
    z.avail_in = (uInt)raw_len;
    while (buf && rc != Z_STREAM_END) {
        if (len == cap) {
            unsigned char *nb = (unsigned char *)realloc(buf, cap * 2);
            if (!nb) { free(buf); buf = NULL; break; }
            buf = nb;
            cap *= 2;
        }
        z.next_out = buf + len;
        z.avail_out = (uInt)(cap - len);
        rc = inflate(&z, Z_NO_FLUSH);
        len = cap - z.avail_out;
        if (rc != Z_OK && rc != Z_STREAM_END) { free(buf); buf = NULL; break; }
        if (rc == Z_OK && z.avail_in == 0 && z.avail_out != 0) { free(buf); buf = NULL; break; }
    }
    inflateEnd(&z);
    free(raw);
    if (!buf) return -1;
    *out = buf;
    *out_len = len;
    return 0;
}

static unsigned long long tar_octal(const unsigned char *p, int n) {
    unsigned long long v = 0;
    for (int i = 0; i < n && p[i]; i++) {
        if (p[i] == ' ') continue;
        if (p[i] < '0' || p[i] > '7') break;
        v = v * 8 + (p[i] - '0');
    }
    return v;
}

static int extract_named(const char *archive, const char *dest_dir, const tc_pkg *meta) {
    unsigned char *tar = NULL;
    size_t len = 0;
    if (gunzip_all(archive, &tar, &len) != 0) {
        pymcl_set_error("内核安装包解压失败: %s", pymcl_basename(archive));
        return -1;
    }
    pymcl_ensure_dir(dest_dir);
    int found[2] = {0, 0};
    char longname[1024] = {0};
    size_t pos = 0;
    int rc = 0;
    while (pos + 512 <= len && !rc) {
        const unsigned char *h = tar + pos;
        if (!h[0]) break;
        unsigned long long size = tar_octal(h + 124, 12);
        char type = (char)h[156];
        size_t body = pos + 512;
        size_t next = body + (size_t)((size + 511) / 512 * 512);
        if (body + size > len) break;
        if (type == 'L') {
            snprintf(longname, sizeof(longname), "%.*s", (int)(size < sizeof(longname) ? size : sizeof(longname) - 1),
                     (const char *)(tar + body));
            pos = next;
            continue;
        }
        char name[1024];
        if (longname[0]) {
            snprintf(name, sizeof(name), "%s", longname);
            longname[0] = 0;
        } else if (memcmp(h + 257, "ustar", 5) == 0 && h[345]) {
            snprintf(name, sizeof(name), "%.155s/%.100s", (const char *)(h + 345), (const char *)h);
        } else {
            snprintf(name, sizeof(name), "%.100s", (const char *)h);
        }
        if (type == '0' || type == 0) {
            const char *base = strrchr(name, '/');
            base = base ? base + 1 : name;
            for (int i = 0; i < 2; i++) {
                if (!pymcl_ieq(base, meta->files[i].name)) continue;
                char out[PYMCL_PATH], got[129];
                pymcl_path_join(out, sizeof(out), dest_dir, meta->files[i].name);
                if (pymcl_write_file(out, tar + body, (size_t)size) != 0) { rc = -1; break; }
                if (pymcl_sha512_file(out, got) != 0 || !pymcl_ieq(got, meta->files[i].sha512)) {
                    pymcl_set_error("内核文件校验失败: %s", meta->files[i].name);
                    rc = -1;
                    break;
                }
                found[i] = 1;
            }
        }
        pos = next;
    }
    free(tar);
    if (rc) return -1;
    if (!found[0] || !found[1]) {
        const char *a = !found[0] ? meta->files[0].name : meta->files[1].name;
        const char *b = !found[0] && !found[1] ? meta->files[1].name : NULL;
        /* sorted(missing)：VCRUNTIME140.DLL 按码点排在 terracotta-… 前面 */
        if (b) pymcl_set_error("安装包不完整，缺少: %s、%s", a, b);
        else pymcl_set_error("安装包不完整，缺少: %s", a);
        return -1;
    }
    return 0;
}

static int tc_install(pymcl_ctx *ctx) {
    const tc_pkg *meta = package_meta();
    if (!meta) { pymcl_set_error("当前系统架构暂不支持陶瓦联机。"); return -1; }
    if (is_installed()) {
        wlog(ctx, "陶瓦联机内核已安装");
        return 0;
    }
    wlog(ctx, "下载陶瓦联机 %s（%s）", TC_VERSION, meta->cls);
    char cache[PYMCL_PATH], pkg[PYMCL_PATH], name[160];
    pymcl_path_join3(cache, sizeof(cache), g_root, "cache", "terracotta");
    pymcl_ensure_dir(cache);
    snprintf(name, sizeof(name), "terracotta-%s-%s-pkg.tar.gz", TC_VERSION, meta->cls);
    pymcl_path_join(pkg, sizeof(pkg), cache, name);
    char urls[4][512];
    snprintf(urls[0], 512, "https://gitee.com/burningtnt/Terracotta/releases/download/v%s/%s", TC_VERSION, name);
    snprintf(urls[1], 512, "https://cnb.cool/HMCL-Terracotta/Terracotta/-/releases/download/v%s/%s", TC_VERSION, name);
    snprintf(urls[2], 512, "https://alist.8mi.tech/d/mirror/HMCL-Terracotta/Auto/v%s/%s", TC_VERSION, name);
    snprintf(urls[3], 512, "https://github.com/burningtnt/Terracotta/releases/download/v%s/%s", TC_VERSION, name);
    const char *extra[3] = {urls[1], urls[2], urls[3]};
    if (download_file(urls[0], extra, 3, pkg, ctx, NULL, -1, meta->hash) != 0) return -1;
    wlog(ctx, "正在解压内核…");
    char root[PYMCL_PATH];
    install_dir(root, sizeof(root));
    if (pymcl_dir_exists(root)) pymcl_remove_tree(root);
    if (extract_named(pkg, root, meta) != 0) {
        char err[512];
        snprintf(err, sizeof(err), "%s", pymcl_error());
        pymcl_remove_tree(root);
        pymcl_set_error("%s", err);
        return -1;
    }
    wlog(ctx, "已安装到 %s", root);
    return 0;
}

/* _terracotta_prepare_impl：由 backend.c 的任务线程调用 */
int terracotta_prepare_run(pymcl_ctx *ctx, char *msg, size_t n) {
    if (tc_install(ctx) != 0) return -1;
    if (ctx && ctx->on_progress) ctx->on_progress(ctx->ud, tr("启动内核"), 1, 1);
    if (tc_start(ctx) < 0) return -1;
    snprintf(msg, n, "%s", tr("陶瓦联机已就绪"));
    return 0;
}

/* ---------- 状态切换 ---------- */

static cJSON *player_params(const char *player, const char *room) {
    cJSON *pairs = cJSON_CreateArray();
    cJSON *p = cJSON_CreateArray();
    cJSON_AddItemToArray(p, cJSON_CreateString("player"));
    cJSON_AddItemToArray(p, cJSON_CreateString(player && player[0] ? player : "Player"));
    cJSON_AddItemToArray(pairs, p);
    if (room && room[0]) {
        char *r = py_strip(room);
        p = cJSON_CreateArray();
        cJSON_AddItemToArray(p, cJSON_CreateString("room"));
        cJSON_AddItemToArray(p, cJSON_CreateString(r));
        cJSON_AddItemToArray(pairs, p);
        free(r);
    }
    cJSON *nodes = public_nodes(), *it;
    cJSON_ArrayForEach(it, nodes) {
        p = cJSON_CreateArray();
        cJSON_AddItemToArray(p, cJSON_CreateString("public_nodes"));
        cJSON_AddItemToArray(p, cJSON_CreateString(it->valuestring));
        cJSON_AddItemToArray(pairs, p);
    }
    cJSON_Delete(nodes);
    return pairs;
}

static cJSON *fetch_state(void) {
    if (!tc_running()) return cJSON_CreateObject();
    cJSON *data = tc_http("/state", NULL, 4);
    if (!data) return NULL;
    if (!cJSON_IsObject(data)) { cJSON_Delete(data); return cJSON_CreateObject(); }
    return data;
}

/* split_join_url：官方 guest-ok 的 url 是 127.0.0.1 或 127.0.0.1:端口 */
static int split_join_url(const char *url, char *host, size_t hn, long long *port) {
    char *text = py_strip(url);
    if (!text[0]) {
        free(text);
        pymcl_set_error("还没有联机地址。");
        return -1;
    }
    const char *t = text;
    const char *sch = strstr(t, "://");
    if (sch) t = sch + 3;
    const char *colon = strrchr(t, ':');
    if (!colon) {
        snprintf(host, hn, "%s", t[0] ? t : "127.0.0.1");
        *port = 25565;
        free(text);
        return 0;
    }
    char *h = (char *)malloc((size_t)(colon - t) + 1);
    memcpy(h, t, (size_t)(colon - t));
    h[colon - t] = 0;
    char *ps = py_strip(colon + 1);
    const char *q = ps;
    int neg = 0, digits = 0, ok = 1;
    long long v = 0;
    if (*q == '+' || *q == '-') { neg = *q == '-'; q++; }
    for (; *q; q++) {
        if (*q == '_' && digits && q[1] && isdigit((unsigned char)q[1])) continue;
        if (!isdigit((unsigned char)*q)) { ok = 0; break; }
        v = v * 10 + (*q - '0');
        digits++;
    }
    if (!ok || !digits) {
        pymcl_set_error("invalid literal for int() with base 10: '%s'", colon + 1);
        free(h);
        free(ps);
        free(text);
        return -1;
    }
    snprintf(host, hn, "%s", h[0] ? h : "127.0.0.1");
    *port = neg ? -v : v;
    free(h);
    free(ps);
    free(text);
    return 0;
}

/* ---------- servers.dat（Python 参考实现按 gzip 读写，这里照搬） ---------- */

typedef struct { const unsigned char *p; size_t len, pos; int bad; } rd_t;

static int rd_u8(rd_t *r) {
    if (r->pos + 1 > r->len) { r->bad = 1; return 0; }
    return r->p[r->pos++];
}

static uint32_t rd_be(rd_t *r, int n) {
    uint32_t v = 0;
    if (r->pos + (size_t)n > r->len) { r->bad = 1; return 0; }
    for (int i = 0; i < n; i++) v = (v << 8) | r->p[r->pos++];
    return v;
}

static char *rd_str(rd_t *r) {
    uint32_t n = rd_be(r, 2);
    if (r->bad || r->pos + n > r->len) { r->bad = 1; return pymcl_strdup(""); }
    char *s = (char *)malloc(n + 1);
    memcpy(s, r->p + r->pos, n);
    s[n] = 0;
    r->pos += n;
    return s;
}

static void rd_skip(rd_t *r, size_t n) {
    if (r->pos + n > r->len) r->bad = 1;
    else r->pos += n;
}

static void skip_nbt(rd_t *r, int tag, int depth) {
    if (r->bad || depth > 64) { r->bad = 1; return; }
    switch (tag) {
    case 0: return;
    case 1: rd_skip(r, 1); return;
    case 2: rd_skip(r, 2); return;
    case 3: case 5: rd_skip(r, 4); return;
    case 4: case 6: rd_skip(r, 8); return;
    case 7: { int32_t n = (int32_t)rd_be(r, 4); if (n > 0) rd_skip(r, (size_t)n); return; }
    case 8: free(rd_str(r)); return;
    case 9: {
        int child = rd_u8(r);
        int32_t count = (int32_t)rd_be(r, 4);
        for (int32_t i = 0; i < count && !r->bad; i++) skip_nbt(r, child, depth + 1);
        return;
    }
    case 10:
        while (!r->bad) {
            int child = rd_u8(r);
            if (child == 0) break;
            free(rd_str(r));
            skip_nbt(r, child, depth + 1);
        }
        return;
    case 11: { int32_t n = (int32_t)rd_be(r, 4); if (n > 0) rd_skip(r, (size_t)n * 4); return; }
    case 12: { int32_t n = (int32_t)rd_be(r, 4); if (n > 0) rd_skip(r, (size_t)n * 8); return; }
    default: r->bad = 1;
    }
}

static cJSON *read_compound(rd_t *r, int depth) {
    cJSON *data = cJSON_CreateObject();
    if (depth > 64) { r->bad = 1; return data; }
    while (!r->bad) {
        int tag = rd_u8(r);
        if (tag == 0) return data;
        char *name = rd_str(r);
        cJSON *val = NULL;
        if (tag == 1) val = cJSON_CreateNumber(rd_u8(r));
        else if (tag == 8) { char *s = rd_str(r); val = cJSON_CreateString(s); free(s); }
        else if (tag == 9) {
            int child = rd_u8(r);
            int32_t count = (int32_t)rd_be(r, 4);
            val = cJSON_CreateArray();
            for (int32_t i = 0; i < count && !r->bad; i++) {
                if (child == 10) cJSON_AddItemToArray(val, read_compound(r, depth + 1));
                else skip_nbt(r, child, depth + 1);
            }
        } else skip_nbt(r, tag, depth + 1);
        if (val) {
            cJSON_DeleteItemFromObjectCaseSensitive(data, name);
            cJSON_AddItemToObject(data, name, val);
        }
        free(name);
    }
    return data;
}

static cJSON *read_servers(const char *path) {
    cJSON *rows = cJSON_CreateArray();
    if (!pymcl_file_exists(path)) return rows;
    unsigned char *raw = NULL;
    size_t len = 0;
    if (gunzip_all(path, &raw, &len) != 0) return rows;
    rd_t r = {raw, len, 0, 0};
    if (rd_u8(&r) == 10 && !r.bad) {
        free(rd_str(&r));
        cJSON *root = read_compound(&r, 0);
        cJSON *list = cJSON_GetObjectItemCaseSensitive(root, "servers");
        if (!r.bad && cJSON_IsArray(list)) {
            cJSON *it;
            cJSON_ArrayForEach(it, list)
                if (cJSON_IsObject(it)) cJSON_AddItemToArray(rows, cJSON_Duplicate(it, 1));
        }
        cJSON_Delete(root);
        if (r.bad) {
            cJSON_Delete(rows);
            rows = cJSON_CreateArray();
        }
    }
    free(raw);
    return rows;
}

typedef struct { unsigned char *p; size_t len, cap; } wb_t;

static void wb_put(wb_t *b, const void *d, size_t n) {
    if (b->len + n > b->cap) {
        size_t nc = (b->cap ? b->cap * 2 : 256) + n;
        unsigned char *np = (unsigned char *)realloc(b->p, nc);
        if (!np) return;
        b->p = np;
        b->cap = nc;
    }
    memcpy(b->p + b->len, d, n);
    b->len += n;
}

static void wb_u8(wb_t *b, int v) { unsigned char c = (unsigned char)v; wb_put(b, &c, 1); }

static void wb_str(wb_t *b, const char *s) {
    size_t n = strlen(s);
    unsigned char h[2] = {(unsigned char)(n >> 8), (unsigned char)n};
    wb_put(b, h, 2);
    wb_put(b, s, n);
}

static void py_text(cJSON *v, const char *def, char *out, size_t n) {
    if (py_truthy(v)) py_str(v, out, n);
    else snprintf(out, n, "%s", def);
}

static int write_servers(const char *path, cJSON *servers) {
    wb_t b = {0};
    wb_u8(&b, 10);
    wb_str(&b, "");
    wb_u8(&b, 9);
    wb_str(&b, "servers");
    wb_u8(&b, 10);
    int count = cJSON_GetArraySize(servers);
    unsigned char c4[4] = {(unsigned char)(count >> 24), (unsigned char)(count >> 16),
                           (unsigned char)(count >> 8), (unsigned char)count};
    wb_put(&b, c4, 4);
    cJSON *row;
    cJSON_ArrayForEach(row, servers) {
        char name[1024], ip[1024];
        py_text(cJSON_GetObjectItemCaseSensitive(row, "name"), TC_LOBBY_NAME, name, sizeof(name));
        py_text(cJSON_GetObjectItemCaseSensitive(row, "ip"), "", ip, sizeof(ip));
        int hidden = py_truthy(cJSON_GetObjectItemCaseSensitive(row, "hidden")) ? 1 : 0;
        wb_u8(&b, 8); wb_str(&b, "name"); wb_str(&b, name);
        wb_u8(&b, 8); wb_str(&b, "ip"); wb_str(&b, ip);
        wb_u8(&b, 1); wb_str(&b, "hidden"); wb_u8(&b, hidden);
        wb_u8(&b, 0);
    }
    wb_u8(&b, 0);
    if (!b.p) { pymcl_set_error("内存不足"); return -1; }
    z_stream z;
    memset(&z, 0, sizeof(z));
    if (deflateInit2(&z, 9, Z_DEFLATED, 16 + MAX_WBITS, 8, Z_DEFAULT_STRATEGY) != Z_OK) { free(b.p); return -1; }
    size_t cap = deflateBound(&z, (uLong)b.len) + 64;
    unsigned char *out = (unsigned char *)malloc(cap);
    z.next_in = b.p;
    z.avail_in = (uInt)b.len;
    z.next_out = out;
    z.avail_out = (uInt)cap;
    int rc = out ? deflate(&z, Z_FINISH) : Z_MEM_ERROR;
    size_t olen = cap - z.avail_out;
    deflateEnd(&z);
    free(b.p);
    if (rc != Z_STREAM_END) { free(out); pymcl_set_error("servers.dat 写入失败"); return -1; }
    int wr = pymcl_write_file(path, out, olen);
    free(out);
    return wr;
}

static void default_game_dir(char *out, size_t n) {
    const char *inst = config_str("default_instance", "");
    instance_path(inst && inst[0] ? inst : "default", out, n);
}

static int write_lobby_server(const char *game_dir, const char *url) {
    char host[512], address[600], path[PYMCL_PATH];
    long long port;
    if (split_join_url(url, host, sizeof(host), &port) != 0) return -1;
    if (port == 25565) snprintf(address, sizeof(address), "%s", host);
    else snprintf(address, sizeof(address), "%s:%lld", host, port);
    pymcl_path_join(path, sizeof(path), game_dir, "servers.dat");
    pymcl_ensure_dir(game_dir);
    cJSON *servers = read_servers(path);
    cJSON *out = cJSON_CreateArray();
    cJSON *entry = cJSON_CreateObject();
    cJSON_AddStringToObject(entry, "name", TC_LOBBY_NAME);
    cJSON_AddStringToObject(entry, "ip", address);
    cJSON_AddNumberToObject(entry, "hidden", 0);
    cJSON_AddItemToArray(out, entry);
    cJSON *row;
    cJSON_ArrayForEach(row, servers) {
        char name[1024], ip[1024];
        py_text(cJSON_GetObjectItemCaseSensitive(row, "name"), "", name, sizeof(name));
        py_text(cJSON_GetObjectItemCaseSensitive(row, "ip"), "", ip, sizeof(ip));
        if (strcmp(name, TC_LOBBY_NAME) == 0 || strcmp(ip, address) == 0) continue;
        cJSON_AddItemToArray(out, cJSON_Duplicate(row, 1));
    }
    cJSON_Delete(servers);
    int rc = write_servers(path, out);
    cJSON_Delete(out);
    return rc;
}

static int remember_lobby(const char *url, const char *game_dir) {
    char dest[PYMCL_PATH], key[sizeof(g_last_lobby)];
    if (game_dir && game_dir[0]) snprintf(dest, sizeof(dest), "%s", game_dir);
    else default_game_dir(dest, sizeof(dest));
    snprintf(key, sizeof(key), "%s|%s", dest, url);
    pthread_mutex_lock(&g_mu);
    int same = strcmp(g_last_lobby, key) == 0;
    pthread_mutex_unlock(&g_mu);
    if (same) return 0;
    if (write_lobby_server(dest, url) != 0) return -1;
    pthread_mutex_lock(&g_mu);
    snprintf(g_last_lobby, sizeof(g_last_lobby), "%s", key);
    pthread_mutex_unlock(&g_mu);
    return 0;
}

/* ---------- 防火墙 ---------- */

static void add_program(cJSON *found, const char *path) {
    wchar_t *w = pymcl_u8_to_wide(path);
    wchar_t full[MAX_PATH * 2];
    DWORD n = w ? GetFullPathNameW(w, MAX_PATH * 2, full, NULL) : 0;
    free(w);
    if (!n || n >= MAX_PATH * 2) return;
    char *u = pymcl_wide_to_u8(full);
    if (!u) return;
    if (pymcl_file_exists(u)) {
        int dup = 0;
        cJSON *it;
        cJSON_ArrayForEach(it, found) if (pymcl_ieq(it->valuestring, u)) dup = 1;
        if (!dup) cJSON_AddItemToArray(found, cJSON_CreateString(u));
    }
    free(u);
}

/* 陶瓦本体 + 临时目录里解压出的 EasyTier */
static cJSON *firewall_programs(void) {
    cJSON *found = cJSON_CreateArray();
    char exe[PYMCL_PATH];
    if (package_meta() && executable(exe, sizeof(exe)) == 0) add_program(found, exe);
    wchar_t wt[MAX_PATH];
    if (GetTempPathW(MAX_PATH, wt)) {
        char *t = pymcl_wide_to_u8(wt), dir[PYMCL_PATH];
        if (t) {
            pymcl_path_join(dir, sizeof(dir), t, "terracotta");
            free(t);
            if (pymcl_dir_exists(dir)) {
                cJSON *files = pymcl_walk_files(dir), *it;
                cJSON_ArrayForEach(it, files) {
                    const char *rel = cJSON_GetStringValue(it);
                    if (!rel || !pymcl_endswith(rel, ".exe")) continue;
                    const char *base = pymcl_basename(rel);
                    if (!pymcl_icontains(base, "easytier") && !pymcl_icontains(base, "terracotta")) continue;
                    char full[PYMCL_PATH];
                    if (rel[0] && rel[1] == ':') snprintf(full, sizeof(full), "%s", rel);
                    else pymcl_path_join(full, sizeof(full), dir, rel);
                    add_program(found, full);
                }
                cJSON_Delete(files);
            }
        }
    }
    return found;
}

static void short_path(const char *path, char *out, size_t n) {
    wchar_t *w = pymcl_u8_to_wide(path);
    wchar_t buf[520];
    DWORD got = w ? GetShortPathNameW(w, buf, 520) : 0;
    free(w);
    char *u = got && got < 520 ? pymcl_wide_to_u8(buf) : NULL;
    snprintf(out, n, "%s", u ? u : path);
    free(u);
}

static void collect_line(void *ud, const char *line) {
    char *buf = (char *)ud;
    size_t len = strlen(buf);
    snprintf(buf + len, 4096 - len, "%s%s", len ? "\n" : "", line);
}

static cJSON *allow_firewall(void) {
    cJSON *programs = firewall_programs();
    if (!cJSON_GetArraySize(programs)) {
        cJSON_Delete(programs);
        pymcl_set_error("还没找到陶瓦内核，请先点下载/启动，再允许防火墙。");
        return NULL;
    }
    size_t cap = 16384, len = 0;
    char *bat = (char *)calloc(1, cap);
    len += (size_t)snprintf(bat + len, cap - len, "@echo off\r\nchcp 65001 >nul\r\n");
    int index = 0;
    cJSON *it;
    cJSON_ArrayForEach(it, programs) {
        char prog[PYMCL_PATH];
        short_path(it->valuestring, prog, sizeof(prog));
        const char *dirs[2] = {"in", "out"};
        for (int d = 0; d < 2; d++) {
            len += (size_t)snprintf(bat + len, cap - len,
                "netsh advfirewall firewall delete rule name=\"PyMCL Terracotta %d %s\" >nul 2>nul\r\n"
                "netsh advfirewall firewall add rule name=\"PyMCL Terracotta %d %s\" dir=%s "
                "action=allow program=\"%s\" enable=yes profile=any\r\n",
                index, dirs[d], index, dirs[d], dirs[d], prog);
        }
        index++;
    }
    len += (size_t)snprintf(bat + len, cap - len,
        "netsh advfirewall firewall delete rule name=\"PyMCL Terracotta ICMPv4\" >nul 2>nul\r\n"
        "netsh advfirewall firewall add rule name=\"PyMCL Terracotta ICMPv4\" "
        "protocol=icmpv4:8,any dir=in action=allow enable=yes profile=any\r\n"
        "exit /b 0\r\n");
    char path[PYMCL_PATH], dir[PYMCL_PATH];
    pymcl_path_join3(path, sizeof(path), g_root, "terracotta", "allow-firewall.bat");
    pymcl_parent(path, dir, sizeof(dir));
    pymcl_ensure_dir(dir);
    /* bat 按 GBK 写（与 Python encoding="gbk", errors="replace" 一致） */
    wchar_t *wbat = pymcl_u8_to_wide(bat);
    free(bat);
    int gl = wbat ? WideCharToMultiByte(936, 0, wbat, -1, NULL, 0, "?", NULL) : 0;
    char *gbk = gl ? (char *)malloc((size_t)gl) : NULL;
    if (gbk) WideCharToMultiByte(936, 0, wbat, -1, gbk, gl, "?", NULL);
    free(wbat);
    int wr = gbk ? pymcl_write_file(path, gbk, strlen(gbk)) : -1;
    free(gbk);
    if (wr != 0) {
        cJSON_Delete(programs);
        pymcl_set_error("写入防火墙规则失败，请在 UAC 窗口点「是」。");
        return NULL;
    }
    char quoted[PYMCL_PATH * 2], cmd[PYMCL_PATH * 3];
    size_t k = 0;
    quoted[k++] = '\'';
    for (const char *p = path; *p && k + 3 < sizeof(quoted); p++) {
        if (*p == '\'') quoted[k++] = '\'';
        quoted[k++] = *p;
    }
    quoted[k++] = '\'';
    quoted[k] = 0;
    snprintf(cmd, sizeof(cmd), "Start-Process -FilePath %s -Verb RunAs -Wait -WindowStyle Hidden", quoted);
    const char *argv[] = {"powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", cmd};
    char out[4096] = {0};
    int code = pymcl_run_process(argv, 6, NULL, collect_line, out, 600);
    if (code != 0) {
        cJSON_Delete(programs);
        char low[4096];
        snprintf(low, sizeof(low), "%s", out);
        for (char *q = low; *q; q++) *q = (char)tolower((unsigned char)*q);
        char *err = py_strip(out);
        if (strstr(low, "canceled") || strstr(out, "1223") || code == 1223)
            pymcl_set_error("已取消管理员授权，防火墙规则没有写入。");
        else if (err[0]) pymcl_set_error("%s", err);
        else pymcl_set_error("写入防火墙规则失败，请在 UAC 窗口点「是」。");
        free(err);
        return NULL;
    }
    pthread_mutex_lock(&g_mu);
    cJSON_Delete(g_allowed_fw);
    g_allowed_fw = cJSON_CreateArray();
    cJSON_ArrayForEach(it, programs) {
        char low[PYMCL_PATH];
        snprintf(low, sizeof(low), "%s", it->valuestring);
        for (char *q = low; *q; q++) *q = (char)tolower((unsigned char)*q);
        cJSON_AddItemToArray(g_allowed_fw, cJSON_CreateString(low));
    }
    pthread_mutex_unlock(&g_mu);
    char names[2048] = {0};
    int i = 0;
    cJSON_ArrayForEach(it, programs) {
        if (i >= 4) break;
        size_t nl = strlen(names);
        snprintf(names + nl, sizeof(names) - nl, "%s%s", i ? "、" : "", pymcl_basename(it->valuestring));
        i++;
    }
    cJSON_Delete(programs);
    char msg[2600];
    snprintf(msg, sizeof(msg), "已允许 %s 通过防火墙。若装着电脑管家/360/火绒，还要在它们里面放行。", names);
    return cJSON_CreateString(msg);
}

static int firewall_stale(void) {
    cJSON *programs = firewall_programs(), *it;
    int stale = 0;
    pthread_mutex_lock(&g_mu);
    cJSON_ArrayForEach(it, programs) {
        if (!pymcl_icontains(pymcl_basename(it->valuestring), "easytier")) continue;
        char low[PYMCL_PATH];
        snprintf(low, sizeof(low), "%s", it->valuestring);
        for (char *q = low; *q; q++) *q = (char)tolower((unsigned char)*q);
        int allowed = 0;
        cJSON *a;
        cJSON_ArrayForEach(a, g_allowed_fw) if (strcmp(a->valuestring, low) == 0) allowed = 1;
        if (!allowed) { stale = 1; break; }
    }
    pthread_mutex_unlock(&g_mu);
    cJSON_Delete(programs);
    return stale;
}

/* ---------- snapshot ---------- */

static cJSON *snapshot(const char *player, int game_running) {
    const tc_pkg *meta = package_meta();
    cJSON *info = cJSON_CreateObject();
    cJSON_AddBoolToObject(info, "supported", meta != NULL);
    cJSON_AddBoolToObject(info, "installed", is_installed());
    cJSON_AddBoolToObject(info, "running", tc_running());
    cJSON_AddNumberToObject(info, "port", g_port);
    cJSON_AddStringToObject(info, "state", "missing");
    cJSON_AddStringToObject(info, "label", state_label("missing"));
    cJSON_AddStringToObject(info, "room", "");
    cJSON_AddStringToObject(info, "url", "");
    cJSON_AddStringToObject(info, "difficulty", "");
    cJSON_AddStringToObject(info, "difficulty_hint", "");
    cJSON_AddItemToObject(info, "profiles", cJSON_CreateArray());
    cJSON_AddStringToObject(info, "error", "");
    cJSON_AddStringToObject(info, "player", player && player[0] ? player : "Player");
    cJSON_AddBoolToObject(info, "game_running", game_running);
    cJSON_AddStringToObject(info, "copyright", TC_COPYRIGHT);
    cJSON_AddStringToObject(info, "home", TC_HOME);
    cJSON_AddStringToObject(info, "version", TC_VERSION);
    pthread_mutex_lock(&g_mu);
    cJSON_AddItemToObject(info, "nodes", g_nodes ? cJSON_Duplicate(g_nodes, 1) : cJSON_CreateArray());
    pthread_mutex_unlock(&g_mu);
    cJSON_AddBoolToObject(info, "firewall_stale", 0);
#define SET_STR(k, v) cJSON_ReplaceItemInObjectCaseSensitive(info, k, cJSON_CreateString(v))
    if (!meta) {
        SET_STR("state", "unsupported");
        SET_STR("label", state_label("unsupported"));
        return info;
    }
    if (!cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(info, "installed"))) return info;
    if (!tc_running()) {
        SET_STR("state", "idle");
        SET_STR("label", "内核已安装，打开本页会自动启动");
        return info;
    }
    cJSON *data = fetch_state();
    if (!data) {
        SET_STR("state", "fatal");
        SET_STR("label", state_label("fatal"));
        SET_STR("error", pymcl_error());
        return info;
    }
    char raw[128], room[256], url[512], diff[64];
    py_text(cJSON_GetObjectItemCaseSensitive(data, "state"), "unknown", raw, sizeof(raw));
    SET_STR("state", raw);
    SET_STR("label", state_label(raw));
    cJSON *rv = cJSON_GetObjectItemCaseSensitive(data, "room");
    py_text(py_truthy(rv) ? rv : cJSON_GetObjectItemCaseSensitive(data, "code"), "", room, sizeof(room));
    SET_STR("room", room);
    py_text(cJSON_GetObjectItemCaseSensitive(data, "url"), "", url, sizeof(url));
    SET_STR("url", url);
    py_text(cJSON_GetObjectItemCaseSensitive(data, "difficulty"), "", diff, sizeof(diff));
    for (char *q = diff; *q; q++) *q = (char)toupper((unsigned char)*q);
    SET_STR("difficulty", diff);
    SET_STR("difficulty_hint", kv_get(DIFF, sizeof(DIFF) / sizeof(DIFF[0]), diff, ""));
    cJSON *profiles = cJSON_GetObjectItemCaseSensitive(data, "profiles");
    cJSON *rows = cJSON_CreateArray();
    if (cJSON_IsArray(profiles)) {
        cJSON *item;
        cJSON_ArrayForEach(item, profiles) {
            if (!cJSON_IsObject(item)) continue;
            cJSON *row = cJSON_CreateObject();
            const char *keys[3] = {"name", "vendor", "kind"};
            for (int i = 0; i < 3; i++) {
                cJSON *v = cJSON_GetObjectItemCaseSensitive(item, keys[i]);
                cJSON_AddItemToObject(row, keys[i], py_truthy(v) ? cJSON_Duplicate(v, 1)
                                                     : cJSON_CreateString(i == 0 ? "玩家" : ""));
            }
            cJSON_AddItemToArray(rows, row);
        }
    }
    cJSON_ReplaceItemInObjectCaseSensitive(info, "profiles", rows);
    if (strcmp(raw, "exception") == 0) {
        long long typ = 0;
        cJSON *tv = cJSON_GetObjectItemCaseSensitive(data, "type");
        if (py_truthy(tv) && !py_int(tv, &typ)) typ = 0;
        const char *err = typ >= 0 && typ < (long long)(sizeof(EXC) / sizeof(EXC[0])) ? EXC[typ] : "联机出错";
        SET_STR("error", err);
        SET_STR("label", err);
        if (typ == 0) cJSON_AddStringToObject(info, "error_hint", PING_HOST_HINT);
    }
    if (strcmp(raw, "guest-ok") == 0 && url[0]) remember_lobby(url, NULL);
    cJSON_ReplaceItemInObjectCaseSensitive(info, "firewall_stale", cJSON_CreateBool(firewall_stale()));
#undef SET_STR
    cJSON_Delete(data);
    return info;
}

/* ---------- bridge/api.py 那一层 ---------- */

static void active_player(char *out, size_t n) {
    snprintf(out, n, "Player");
    cJSON *root = accounts_load();
    const char *active = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(root, "active"));
    if (active && active[0]) {
        cJSON *acc;
        cJSON_ArrayForEach(acc, cJSON_GetObjectItemCaseSensitive(root, "accounts")) {
            cJSON *name = cJSON_GetObjectItemCaseSensitive(acc, "name");
            if (!cJSON_IsString(name) || strcmp(name->valuestring, active) != 0) continue;
            if (name->valuestring[0]) snprintf(out, n, "%s", name->valuestring);
            break;
        }
    }
    cJSON_Delete(root);
}

static int game_running(void) {
    cJSON *r = backend_call("is_game_running", NULL);
    int on = py_truthy(r);
    cJSON_Delete(r);
    return on;
}

static cJSON *api_snapshot(void) {
    char player[256];
    active_player(player, sizeof(player));
    return snapshot(player, game_running());
}

static cJSON *launch_into_server(const char *url, const char *already_msg) {
    const char *inst_name = config_str("default_instance", "");
    if (!inst_name || !inst_name[0]) inst_name = "default";
    char inst_dir[PYMCL_PATH];
    instance_path(inst_name, inst_dir, sizeof(inst_dir));
    if (remember_lobby(url, inst_dir) != 0) return NULL;
    cJSON *info = api_snapshot();
    int running = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(info, "game_running"));
    cJSON_Delete(info);
    if (running) return cJSON_CreateString(already_msg);
    cJSON *q = cJSON_CreateObject();
    cJSON_AddStringToObject(q, "instance", inst_name);
    cJSON *ids = backend_call("get_installed_versions", q);
    cJSON_Delete(q);
    char best[256] = {0};
    long long best_m = -1;
    cJSON *it;
    cJSON_ArrayForEach(it, ids) {
        const char *vid = cJSON_IsString(it) ? it->valuestring : pstr(it, "id", NULL);
        if (!vid) continue;
        char vdir[PYMCL_PATH];
        pymcl_path_join3(vdir, sizeof(vdir), inst_dir, "versions", vid);
        long long m = pymcl_file_mtime(vdir);
        if (m > best_m) { best_m = m; snprintf(best, sizeof(best), "%s", vid); }
    }
    cJSON_Delete(ids);
    if (!best[0]) {
        pymcl_set_error("%s", tr("请先到「启动」页安装一个版本。"));
        return NULL;
    }
    char host[512];
    long long port;
    if (split_join_url(url, host, sizeof(host), &port) != 0) return NULL;
    /* 微软号：account / username 都是账号名；其余一律走离线，用户名取账号名，没有就 terracotta_player */
    char player[256], name[256] = {0};
    active_player(player, sizeof(player));
    cJSON *root = accounts_load();
    const char *active = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(root, "active"));
    int microsoft = 0;
    cJSON *acc;
    cJSON_ArrayForEach(acc, cJSON_GetObjectItemCaseSensitive(root, "accounts")) {
        if (active && active[0] && strcmp(pstr(acc, "name", ""), active) == 0) {
            microsoft = strcmp(pstr(acc, "type", ""), "microsoft") == 0;
            snprintf(name, sizeof(name), "%s", pstr(acc, "name", ""));
            break;
        }
    }
    cJSON_Delete(root);
    cJSON *p = cJSON_CreateObject();
    cJSON_AddStringToObject(p, "instance", inst_name);
    cJSON_AddStringToObject(p, "version", best);
    cJSON_AddStringToObject(p, "account", microsoft && name[0] ? name : tr("离线模式"));
    cJSON_AddStringToObject(p, "username", name[0] ? name : player);
    cJSON_AddNumberToObject(p, "memory_mb", config_int("memory_mb", 4096) ? config_int("memory_mb", 4096) : 4096);
    cJSON_AddNumberToObject(p, "width", config_int("width", 854) ? config_int("width", 854) : 854);
    cJSON_AddNumberToObject(p, "height", config_int("height", 480) ? config_int("height", 480) : 480);
    cJSON *extra = cJSON_CreateArray();
    char port_s[32];
    snprintf(port_s, sizeof(port_s), "%lld", port);
    cJSON_AddItemToArray(extra, cJSON_CreateString("--server"));
    cJSON_AddItemToArray(extra, cJSON_CreateString(host));
    cJSON_AddItemToArray(extra, cJSON_CreateString("--port"));
    cJSON_AddItemToArray(extra, cJSON_CreateString(port_s));
    cJSON_AddItemToObject(p, "extra_game_args", extra);
    cJSON *task = backend_call("launch_game", p);
    cJSON_Delete(p);
    return task;
}

static cJSON *missing_arg(const char *method, const char *arg) {
    pymcl_set_error("BackendAPI.%s() missing 1 required positional argument: '%s'", method, arg);
    return NULL;
}

cJSON *rpc_terracotta_call(const char *method, cJSON *params, sse_emit_fn emit, int *handled) {
    (void)emit;
    *handled = 1;
    if (strcmp(method, "terracotta_player") == 0) {
        char player[256];
        active_player(player, sizeof(player));
        return cJSON_CreateString(player);
    }
    if (strcmp(method, "terracotta_snapshot") == 0) return api_snapshot();
    if (strcmp(method, "terracotta_host") == 0) {
        char player[256];
        active_player(player, sizeof(player));
        recover_waiting();
        cJSON *pairs = player_params(player, NULL);
        cJSON *r = tc_http("/state/scanning", pairs, 4);
        cJSON_Delete(pairs);
        if (!r) return NULL;
        cJSON_Delete(r);
        return cJSON_CreateNull();
    }
    if (strcmp(method, "terracotta_join") == 0) {
        cJSON *rv = cJSON_GetObjectItemCaseSensitive(params, "room");
        if (!rv) return missing_arg(method, "room");
        char *room = py_strip(cJSON_IsString(rv) ? rv->valuestring : "");
        char norm[32];
        cJSON *r = NULL;
        if (!room[0]) pymcl_set_error("请输入邀请码。");
        else if (!parse_room(room, norm)) pymcl_set_error("%s", room_error(room));
        else {
            char player[256];
            active_player(player, sizeof(player));
            recover_waiting();
            cJSON *pairs = player_params(player, room);
            r = tc_http("/state/guesting", pairs, 4);
            cJSON_Delete(pairs);
        }
        free(room);
        if (!r) return NULL;
        cJSON_Delete(r);
        return cJSON_CreateNull();
    }
    if (strcmp(method, "terracotta_idle") == 0) {
        cJSON *r = tc_http("/state/ide", NULL, 4);
        if (!r) return NULL;
        cJSON_Delete(r);
        return cJSON_CreateNull();
    }
    if (strcmp(method, "terracotta_allow_firewall") == 0) return allow_firewall();
    if (strcmp(method, "terracotta_open_firewall_settings") == 0) {
        ShellExecuteW(NULL, L"open", L"control", L"firewall.cpl", NULL, SW_SHOWNORMAL);
        return cJSON_CreateNull();
    }
    if (strcmp(method, "terracotta_shutdown") == 0) {
        tc_stop();
        return cJSON_CreateNull();
    }
    if (strcmp(method, "terracotta_enter_world") == 0) {
        cJSON *info = api_snapshot();
        char url[512];
        snprintf(url, sizeof(url), "%s", pstr(info, "url", ""));
        int ok = strcmp(pstr(info, "state", ""), "guest-ok") == 0 && url[0];
        cJSON_Delete(info);
        if (!ok) {
            pymcl_set_error("%s", tr("还没连上房间。请先输入邀请码加入。"));
            return NULL;
        }
        return launch_into_server(url, tr("请到游戏「多人游戏」双击「陶瓦联机大厅」。"));
    }
    if (strcmp(method, "terracotta_direct_connect") == 0) {
        cJSON *av = cJSON_GetObjectItemCaseSensitive(params, "address");
        if (!av) return missing_arg(method, "address");
        char host[512], url[600];
        long long port;
        if (split_join_url(cJSON_IsString(av) ? av->valuestring : "", host, sizeof(host), &port) != 0) return NULL;
        if (!host[0] || strcmp(host, "127.0.0.1") == 0 || strcmp(host, "localhost") == 0) {
            pymcl_set_error("%s", tr("请输入房主的公网地址，例如 1.2.3.4:25565"));
            return NULL;
        }
        snprintf(url, sizeof(url), "%s:%lld", host, port);
        return launch_into_server(url, tr("请到游戏「多人游戏」双击「陶瓦联机大厅」。"));
    }
    *handled = 0;
    return NULL;
}

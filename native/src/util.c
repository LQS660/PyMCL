#include "pymcl.h"
#include <bcrypt.h>
#include <shlobj.h>
#include <direct.h>
#include <errno.h>
#include <ctype.h>
#include <math.h>

#pragma comment(lib, "bcrypt.lib")

/* 每个线程一份：桥是多线程 HTTP 服务，共用一份会把 A 请求的错误回给 B 请求 */
static _Thread_local char g_err[PYMCL_ERR];
char g_root[PYMCL_PATH];

const char *pymcl_error(void) { return g_err[0] ? g_err : ""; }
void pymcl_set_error(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    vsnprintf(g_err, sizeof(g_err), fmt, ap);
    va_end(ap);
}
void pymcl_log(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    fprintf(stderr, "[pymcl] ");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
}

char *pymcl_strdup(const char *s) {
    if (!s) return NULL;
    size_t n = strlen(s) + 1;
    char *p = (char *)malloc(n);
    if (p) memcpy(p, s, n);
    return p;
}
int pymcl_snprintf(char *buf, size_t n, const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    int r = vsnprintf(buf, n, fmt, ap);
    va_end(ap);
    if (n) buf[n - 1] = 0;
    return r;
}
void pymcl_path_join(char *out, size_t n, const char *a, const char *b) {
    if (!a || !a[0]) { snprintf(out, n, "%s", b ? b : ""); return; }
    if (!b || !b[0]) { snprintf(out, n, "%s", a); return; }
    /* 与 pathlib 一致：后半截是绝对路径（盘符或 UNC）就以它为准，比如 instances_dir 填了 D:\Games */
    if ((isalpha((unsigned char)b[0]) && b[1] == ':') || (b[0] == '\\' && b[1] == '\\')) {
        snprintf(out, n, "%s", b);
        return;
    }
    size_t la = strlen(a);
    if (a[la - 1] == '/' || a[la - 1] == '\\')
        snprintf(out, n, "%s%s", a, b);
    else
        snprintf(out, n, "%s\\%s", a, b);
}
void pymcl_path_join3(char *out, size_t n, const char *a, const char *b, const char *c) {
    char tmp[PYMCL_PATH];
    pymcl_path_join(tmp, sizeof(tmp), a, b);
    pymcl_path_join(out, n, tmp, c);
}
const char *pymcl_basename(const char *p) {
    if (!p) return "";
    const char *s = p, *last = p;
    for (; *s; s++) if (*s == '/' || *s == '\\') last = s + 1;
    return last;
}
void pymcl_parent(const char *p, char *out, size_t n) {
    snprintf(out, n, "%s", p ? p : "");
    char *s = out + strlen(out);
    while (s > out && (s[-1] == '/' || s[-1] == '\\')) *--s = 0;
    while (s > out && s[-1] != '/' && s[-1] != '\\') *--s = 0;
    if (s > out && (s[-1] == '/' || s[-1] == '\\')) *--s = 0;
}
int pymcl_endswith(const char *s, const char *suf) {
    if (!s || !suf) return 0;
    size_t a = strlen(s), b = strlen(suf);
    return a >= b && _stricmp(s + a - b, suf) == 0;
}
int pymcl_startswith(const char *s, const char *pre) {
    if (!s || !pre) return 0;
    return strncmp(s, pre, strlen(pre)) == 0;
}
int pymcl_ieq(const char *a, const char *b) {
    if (!a || !b) return a == b;
    return _stricmp(a, b) == 0;
}
int pymcl_icontains(const char *hay, const char *needle) {
    if (!hay || !needle || !needle[0]) return 0;
    size_t n = strlen(needle);
    for (const char *p = hay; *p; p++) {
        if (_strnicmp(p, needle, n) == 0) return 1;
    }
    return 0;
}
void pymcl_replace_char(char *s, char a, char b) {
    if (!s) return;
    for (; *s; s++) if (*s == a) *s = b;
}
wchar_t *pymcl_u8_to_wide(const char *s) {
    if (!s) return NULL;
    int n = MultiByteToWideChar(CP_UTF8, 0, s, -1, NULL, 0);
    wchar_t *w = (wchar_t *)malloc((size_t)n * sizeof(wchar_t));
    if (!w) return NULL;
    MultiByteToWideChar(CP_UTF8, 0, s, -1, w, n);
    return w;
}
char *pymcl_wide_to_u8(const wchar_t *w) {
    if (!w) return NULL;
    int n = WideCharToMultiByte(CP_UTF8, 0, w, -1, NULL, 0, NULL, NULL);
    char *s = (char *)malloc((size_t)n);
    if (!s) return NULL;
    WideCharToMultiByte(CP_UTF8, 0, w, -1, s, n, NULL, NULL);
    return s;
}

static int mkdir_one(const char *p) {
    wchar_t *w = pymcl_u8_to_wide(p);
    if (!w) return -1;
    BOOL ok = CreateDirectoryW(w, NULL);
    DWORD e = GetLastError();
    free(w);
    return (ok || e == ERROR_ALREADY_EXISTS) ? 0 : -1;
}
int pymcl_ensure_dir(const char *path) {
    if (!path || !path[0]) return -1;
    char buf[PYMCL_PATH];
    snprintf(buf, sizeof(buf), "%s", path);
    pymcl_replace_char(buf, '/', '\\');
    size_t n = strlen(buf);
    if (n && (buf[n - 1] == '\\')) buf[n - 1] = 0;
    for (char *p = buf; *p; p++) {
        if (*p == '\\' && p > buf + 2) {
            char c = *p; *p = 0;
            mkdir_one(buf);
            *p = c;
        }
    }
    return mkdir_one(buf);
}
int pymcl_file_exists(const char *path) {
    wchar_t *w = pymcl_u8_to_wide(path);
    if (!w) return 0;
    DWORD a = GetFileAttributesW(w);
    free(w);
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}
int pymcl_path_exists(const char *path) {
    wchar_t *w = pymcl_u8_to_wide(path);
    if (!w) return 0;
    DWORD a = GetFileAttributesW(w);
    free(w);
    return a != INVALID_FILE_ATTRIBUTES;
}
int pymcl_dir_exists(const char *path) {
    wchar_t *w = pymcl_u8_to_wide(path);
    if (!w) return 0;
    DWORD a = GetFileAttributesW(w);
    free(w);
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
}
long long pymcl_file_size(const char *path) {
    wchar_t *w = pymcl_u8_to_wide(path);
    if (!w) return -1;
    WIN32_FILE_ATTRIBUTE_DATA d;
    BOOL ok = GetFileAttributesExW(w, GetFileExInfoStandard, &d);
    free(w);
    if (!ok) return -1;
    ULARGE_INTEGER u;
    u.LowPart = d.nFileSizeLow;
    u.HighPart = d.nFileSizeHigh;
    return (long long)u.QuadPart;
}
int pymcl_read_file(const char *path, char **out, size_t *len) {
    wchar_t *w = pymcl_u8_to_wide(path);
    if (!w) return -1;
    FILE *f = _wfopen(w, L"rb");
    free(w);
    if (!f) { pymcl_set_error("无法读取 %s", path); return -1; }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n < 0) { fclose(f); return -1; }
    char *buf = (char *)malloc((size_t)n + 1);
    if (!buf) { fclose(f); return -1; }
    size_t got = fread(buf, 1, (size_t)n, f);
    fclose(f);
    buf[got] = 0;
    *out = buf;
    if (len) *len = got;
    return 0;
}
int pymcl_write_file(const char *path, const void *data, size_t len) {
    char parent[PYMCL_PATH];
    pymcl_parent(path, parent, sizeof(parent));
    if (parent[0]) pymcl_ensure_dir(parent);
    wchar_t *w = pymcl_u8_to_wide(path);
    if (!w) return -1;
    FILE *f = _wfopen(w, L"wb");
    free(w);
    if (!f) { pymcl_set_error("无法写入 %s", path); return -1; }
    size_t wro = fwrite(data, 1, len, f);
    fclose(f);
    return wro == len ? 0 : -1;
}
int pymcl_copy_file(const char *src, const char *dst) {
    char parent[PYMCL_PATH];
    pymcl_parent(dst, parent, sizeof(parent));
    if (parent[0]) pymcl_ensure_dir(parent);
    wchar_t *ws = pymcl_u8_to_wide(src);
    wchar_t *wd = pymcl_u8_to_wide(dst);
    if (!ws || !wd) { free(ws); free(wd); return -1; }
    BOOL ok = CopyFileW(ws, wd, FALSE);
    free(ws); free(wd);
    return ok ? 0 : -1;
}
static void remove_tree_w(const wchar_t *dir) {
    wchar_t pat[PYMCL_PATH];
    _snwprintf(pat, PYMCL_PATH, L"%s\\*", dir);
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) { RemoveDirectoryW(dir); return; }
    do {
        if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0) continue;
        wchar_t child[PYMCL_PATH];
        _snwprintf(child, PYMCL_PATH, L"%s\\%s", dir, fd.cFileName);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
            remove_tree_w(child);
        else {
            SetFileAttributesW(child, FILE_ATTRIBUTE_NORMAL);
            DeleteFileW(child);
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    RemoveDirectoryW(dir);
}
void pymcl_remove_tree(const char *path) {
    if (!path || !path[0]) return;
    wchar_t *w = pymcl_u8_to_wide(path);
    if (!w) return;
    DWORD a = GetFileAttributesW(w);
    if (a == INVALID_FILE_ATTRIBUTES) { free(w); return; }
    if (a & FILE_ATTRIBUTE_DIRECTORY) remove_tree_w(w);
    else { SetFileAttributesW(w, FILE_ATTRIBUTE_NORMAL); DeleteFileW(w); }
    free(w);
}
void pymcl_copy_tree(const char *src, const char *dst) {
    wchar_t *ws = pymcl_u8_to_wide(src);
    if (!ws) return;
    WIN32_FIND_DATAW fd;
    wchar_t pat[PYMCL_PATH];
    _snwprintf(pat, PYMCL_PATH, L"%s\\*", ws);
    HANDLE h = FindFirstFileW(pat, &fd);
    pymcl_ensure_dir(dst);
    if (h == INVALID_HANDLE_VALUE) { free(ws); return; }
    do {
        if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0) continue;
        char *name = pymcl_wide_to_u8(fd.cFileName);
        char csrc[PYMCL_PATH], cdst[PYMCL_PATH];
        pymcl_path_join(csrc, sizeof(csrc), src, name);
        pymcl_path_join(cdst, sizeof(cdst), dst, name);
        free(name);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
            pymcl_copy_tree(csrc, cdst);
        else
            pymcl_copy_file(csrc, cdst);
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    free(ws);
}
/* int(p.stat().st_mtime) */
long long pymcl_file_mtime(const char *path) {
    wchar_t *w = pymcl_u8_to_wide(path);
    WIN32_FILE_ATTRIBUTE_DATA fa;
    long long r = 0;
    if (w && GetFileAttributesExW(w, GetFileExInfoStandard, &fa)) {
        ULARGE_INTEGER u;
        u.LowPart = fa.ftLastWriteTime.dwLowDateTime;
        u.HighPart = fa.ftLastWriteTime.dwHighDateTime;
        r = (long long)((u.QuadPart - 116444736000000000ULL) / 10000000ULL);
    }
    free(w);
    return r;
}

static const char k_b64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

char *pymcl_b64encode(const unsigned char *data, size_t len) {
    size_t outlen = 4 * ((len + 2) / 3);
    char *out = (char *)malloc(outlen + 1);
    if (!out) return NULL;
    size_t o = 0;
    for (size_t i = 0; i < len; i += 3) {
        uint32_t v = (uint32_t)data[i] << 16;
        if (i + 1 < len) v |= (uint32_t)data[i + 1] << 8;
        if (i + 2 < len) v |= data[i + 2];
        out[o++] = k_b64[(v >> 18) & 63];
        out[o++] = k_b64[(v >> 12) & 63];
        out[o++] = i + 1 < len ? k_b64[(v >> 6) & 63] : '=';
        out[o++] = i + 2 < len ? k_b64[v & 63] : '=';
    }
    out[o] = 0;
    return out;
}

/* base64.b64decode(validate=True)：只认标准字母表，长度与填充不对就失败（返回 NULL） */
unsigned char *pymcl_b64decode(const char *text, size_t *out_len) {
    size_t len = text ? strlen(text) : 0;
    if (len % 4 != 0) return NULL;
    unsigned char *out = (unsigned char *)malloc(len / 4 * 3 + 1);
    if (!out) return NULL;
    size_t o = 0;
    for (size_t i = 0; i < len; i += 4) {
        int v[4];
        for (int k = 0; k < 4; k++) {
            char c = text[i + k];
            const char *p = c ? strchr(k_b64, c) : NULL;
            if (p) v[k] = (int)(p - k_b64);
            else if (c == '=' && i + 4 == len && k >= 2) v[k] = -1;
            else { free(out); return NULL; }
        }
        if (v[2] < 0 && v[3] >= 0) { free(out); return NULL; }
        out[o++] = (unsigned char)((v[0] << 2) | (v[1] >> 4));
        if (v[2] >= 0) out[o++] = (unsigned char)(((v[1] & 15) << 4) | (v[2] >> 2));
        if (v[3] >= 0) out[o++] = (unsigned char)(((v[2] & 3) << 6) | v[3]);
    }
    if (out_len) *out_len = o;
    return out;
}

/* urllib.parse.quote(s)（safe="/"）：UTF-8 字节里除字母数字与 _.-~/ 之外都转成 %XX */
void pymcl_url_quote(const char *s, char *out, size_t n) {
    size_t o = 0;
    for (const unsigned char *p = (const unsigned char *)(s ? s : ""); *p && o + 4 < n; p++) {
        if (isalnum(*p) || strchr("_.-~/", *p)) out[o++] = (char)*p;
        else o += (size_t)snprintf(out + o, n - o, "%%%02X", *p);
    }
    out[o] = 0;
}

static int cmp_names(const void *a, const void *b) {
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

/* WindowsPath 之间比较不分大小写（Python 里 sorted(folder.iterdir()) 就是这个口径） */
static int cmp_names_nocase(const void *a, const void *b) {
    wchar_t *wa = pymcl_u8_to_wide(*(const char *const *)a), *wb = pymcl_u8_to_wide(*(const char *const *)b);
    int r = 0;
    if (wa && wb) {
        CharLowerW(wa);
        CharLowerW(wb);
        r = wcscmp(wa, wb);
    }
    free(wa);
    free(wb);
    return r;
}

cJSON *pymcl_list_dir(const char *dir, int want_dirs, int nocase) {
    cJSON *out = cJSON_CreateArray();
    wchar_t *w = pymcl_u8_to_wide(dir);
    if (!w) return out;
    wchar_t pat[PYMCL_PATH];
    _snwprintf(pat, PYMCL_PATH, L"%s\\*", w);
    free(w);
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pat, &fd);
    if (h == INVALID_HANDLE_VALUE) return out;
    char **names = NULL;
    size_t cnt = 0, cap = 0;
    do {
        int is_dir = (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0;
        if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0) continue;
        if (want_dirs == 0 && is_dir) continue;
        if (want_dirs == 1 && !is_dir) continue;
        char *name = pymcl_wide_to_u8(fd.cFileName);
        if (!name) continue;
        if (cnt == cap) {
            cap = cap ? cap * 2 : 32;
            char **nn = (char **)realloc(names, cap * sizeof(char *));
            if (!nn) { free(name); break; }
            names = nn;
        }
        names[cnt++] = name;
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    if (cnt) qsort(names, cnt, sizeof(char *), nocase ? cmp_names_nocase : cmp_names);
    for (size_t i = 0; i < cnt; i++) {
        cJSON_AddItemToArray(out, cJSON_CreateString(names[i]));
        free(names[i]);
    }
    free(names);
    return out;
}

/* str(Path(s))：斜杠换成反斜杠、去掉重复分隔符与 "."、去掉末尾分隔符（盘符根除外） */
void pymcl_py_path(const char *in, char *out, size_t n) {
    char tmp[PYMCL_PATH];
    snprintf(tmp, sizeof(tmp), "%s", in ? in : "");
    pymcl_replace_char(tmp, '/', '\\');
    size_t o = 0, i = 0, len = strlen(tmp);
    char buf[PYMCL_PATH];
    if (len >= 2 && tmp[0] == '\\' && tmp[1] == '\\') { buf[o++] = '\\'; buf[o++] = '\\'; i = 2; }
    for (; i < len && o + 1 < sizeof(buf); i++) {
        if (tmp[i] == '\\' && o > 0 && buf[o - 1] == '\\') continue;
        buf[o++] = tmp[i];
    }
    buf[o] = 0;
    /* 去掉 "\.\" 与开头的 ".\"，结尾的 "\." */
    char *p;
    while ((p = strstr(buf, "\\.\\")) != NULL) memmove(p, p + 2, strlen(p + 2) + 1);
    while (strncmp(buf, ".\\", 2) == 0 && buf[2]) memmove(buf, buf + 2, strlen(buf + 2) + 1);
    len = strlen(buf);
    if (len >= 2 && buf[len - 1] == '.' && buf[len - 2] == '\\') buf[len -= 2] = 0;
    while (len > 1 && buf[len - 1] == '\\' && !(len == 3 && buf[1] == ':')) buf[--len] = 0;
    if (len == 2 && buf[1] == ':') { /* "C:" 保持原样 */ }
    snprintf(out, n, "%s", buf[0] ? buf : ".");
}

cJSON *pymcl_read_json(const char *path) {
    char *buf = NULL; size_t n = 0;
    if (pymcl_read_file(path, &buf, &n) != 0) return NULL;
    /* 记事本 / PowerShell 存的 UTF-8 带 BOM；Python 端按 utf-8-sig 读，这边也得认 */
    const char *p = buf;
    if (n >= 3 && (unsigned char)p[0] == 0xEF && (unsigned char)p[1] == 0xBB && (unsigned char)p[2] == 0xBF) p += 3;
    cJSON *j = cJSON_Parse(p);
    free(buf);
    return j;
}

typedef struct { char *p; size_t len, cap; } sbuf;

static void sb_put(sbuf *b, const char *s, size_t n) {
    if (b->len + n + 1 > b->cap) {
        size_t cap = b->cap ? b->cap : 256;
        while (b->len + n + 1 > cap) cap *= 2;
        char *np = (char *)realloc(b->p, cap);
        if (!np) return;
        b->p = np;
        b->cap = cap;
    }
    memcpy(b->p + b->len, s, n);
    b->len += n;
    b->p[b->len] = 0;
}
static void sb_puts(sbuf *b, const char *s) { sb_put(b, s, strlen(s)); }

static void py_dump_string(sbuf *b, const char *s) {
    sb_put(b, "\"", 1);
    for (const unsigned char *p = (const unsigned char *)(s ? s : ""); *p; p++) {
        switch (*p) {
        case '"': sb_put(b, "\\\"", 2); break;
        case '\\': sb_put(b, "\\\\", 2); break;
        case '\n': sb_put(b, "\\n", 2); break;
        case '\r': sb_put(b, "\\r", 2); break;
        case '\t': sb_put(b, "\\t", 2); break;
        case '\b': sb_put(b, "\\b", 2); break;
        case '\f': sb_put(b, "\\f", 2); break;
        default:
            if (*p < 0x20) {
                char esc[8];
                snprintf(esc, sizeof(esc), "\\u%04x", *p);
                sb_puts(b, esc);
            } else {
                sb_put(b, (const char *)p, 1);
            }
        }
    }
    sb_put(b, "\"", 1);
}

static void py_dump_number(sbuf *b, double d) {
    char num[64];
    if (d != d) { sb_puts(b, "NaN"); return; }
    if (d == HUGE_VAL) { sb_puts(b, "Infinity"); return; }
    if (d == -HUGE_VAL) { sb_puts(b, "-Infinity"); return; }
    if (d == floor(d) && fabs(d) < 9007199254740992.0) {
        snprintf(num, sizeof(num), "%lld", (long long)d);
    } else {
        for (int prec = 1; prec <= 17; prec++) {
            snprintf(num, sizeof(num), "%.*g", prec, d);
            if (strtod(num, NULL) == d) break;
        }
    }
    sb_puts(b, num);
}

static void py_dump(sbuf *b, const cJSON *it, int depth) {
    if (!it || cJSON_IsNull(it)) { sb_puts(b, "null"); return; }
    if (cJSON_IsTrue(it)) { sb_puts(b, "true"); return; }
    if (cJSON_IsFalse(it)) { sb_puts(b, "false"); return; }
    if (cJSON_IsNumber(it)) { py_dump_number(b, it->valuedouble); return; }
    if (cJSON_IsString(it)) { py_dump_string(b, it->valuestring); return; }
    if (cJSON_IsRaw(it)) { sb_puts(b, it->valuestring ? it->valuestring : "null"); return; }
    int is_obj = cJSON_IsObject(it);
    const cJSON *c = it->child;
    if (!c) { sb_puts(b, is_obj ? "{}" : "[]"); return; }
    sb_puts(b, is_obj ? "{" : "[");
    for (; c; c = c->next) {
        sb_puts(b, "\n");
        for (int i = 0; i < depth + 1; i++) sb_puts(b, "  ");
        if (is_obj) {
            py_dump_string(b, c->string);
            sb_puts(b, ": ");
        }
        py_dump(b, c, depth + 1);
        if (c->next) sb_puts(b, ",");
    }
    sb_puts(b, "\n");
    for (int i = 0; i < depth; i++) sb_puts(b, "  ");
    sb_puts(b, is_obj ? "}" : "]");
}

char *pymcl_json_dumps(const cJSON *obj) {
    sbuf b = {0};
    py_dump(&b, obj, 0);
    return b.p;
}

/* 与 mclauncher/utils.write_json 同一种落盘：json.dumps(indent=2, ensure_ascii=False)，
   先写临时文件再原子替换。两个桥轮流写同一份 config.json / accounts.json 时内容逐字节一致。 */
int pymcl_write_json(const char *path, cJSON *obj) {
    char *s = pymcl_json_dumps(obj);
    if (!s) return -1;
    char tmp[PYMCL_PATH];
    snprintf(tmp, sizeof(tmp), "%s.%lu.tmp", path, (unsigned long)GetCurrentThreadId());
    int r = pymcl_write_file(tmp, s, strlen(s));
    free(s);
    if (r != 0) return r;
    wchar_t *wt = pymcl_u8_to_wide(tmp), *wp = pymcl_u8_to_wide(path);
    BOOL ok = wt && wp && MoveFileExW(wt, wp, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
    if (!ok && wt) DeleteFileW(wt);
    free(wt);
    free(wp);
    if (!ok) { pymcl_set_error("无法写入 %s", path); return -1; }
    return 0;
}

static int hash_file(const char *path, LPCWSTR alg, char *hex, size_t hexn, int bytes) {
    wchar_t *w = pymcl_u8_to_wide(path);
    if (!w) return -1;
    FILE *f = _wfopen(w, L"rb");
    free(w);
    if (!f) return -1;
    BCRYPT_ALG_HANDLE hA = NULL;
    BCRYPT_HASH_HANDLE hH = NULL;
    if (BCryptOpenAlgorithmProvider(&hA, alg, NULL, 0) != 0) { fclose(f); return -1; }
    if (BCryptCreateHash(hA, &hH, NULL, 0, NULL, 0, 0) != 0) { BCryptCloseAlgorithmProvider(hA, 0); fclose(f); return -1; }
    unsigned char buf[1 << 16];
    size_t n;
    while ((n = fread(buf, 1, sizeof(buf), f)) > 0)
        BCryptHashData(hH, buf, (ULONG)n, 0);
    fclose(f);
    unsigned char dig[64];
    BCryptFinishHash(hH, dig, (ULONG)bytes, 0);
    BCryptDestroyHash(hH);
    BCryptCloseAlgorithmProvider(hA, 0);
    static const char *x = "0123456789abcdef";
    for (int i = 0; i < bytes && (size_t)(i * 2 + 1) < hexn; i++) {
        hex[i * 2] = x[dig[i] >> 4];
        hex[i * 2 + 1] = x[dig[i] & 15];
    }
    hex[bytes * 2] = 0;
    return 0;
}
int pymcl_sha1_file(const char *path, char hex[41]) {
    return hash_file(path, BCRYPT_SHA1_ALGORITHM, hex, 41, 20);
}
int pymcl_sha512_file(const char *path, char hex[129]) {
    return hash_file(path, BCRYPT_SHA512_ALGORITHM, hex, 129, 64);
}
void pymcl_sha1_bytes(const void *data, size_t n, char hex[41]) {
    BCRYPT_ALG_HANDLE hA = NULL;
    BCRYPT_HASH_HANDLE hH = NULL;
    BCryptOpenAlgorithmProvider(&hA, BCRYPT_SHA1_ALGORITHM, NULL, 0);
    BCryptCreateHash(hA, &hH, NULL, 0, NULL, 0, 0);
    BCryptHashData(hH, (PUCHAR)data, (ULONG)n, 0);
    unsigned char d[20];
    BCryptFinishHash(hH, d, 20, 0);
    BCryptDestroyHash(hH);
    BCryptCloseAlgorithmProvider(hA, 0);
    static const char *x = "0123456789abcdef";
    for (int i = 0; i < 20; i++) { hex[i * 2] = x[d[i] >> 4]; hex[i * 2 + 1] = x[d[i] & 15]; }
    hex[40] = 0;
}
void pymcl_md5_bytes(const void *data, size_t n, unsigned char out[16]) {
    BCRYPT_ALG_HANDLE hA = NULL;
    BCRYPT_HASH_HANDLE hH = NULL;
    BCryptOpenAlgorithmProvider(&hA, BCRYPT_MD5_ALGORITHM, NULL, 0);
    BCryptCreateHash(hA, &hH, NULL, 0, NULL, 0, 0);
    BCryptHashData(hH, (PUCHAR)data, (ULONG)n, 0);
    BCryptFinishHash(hH, out, 16, 0);
    BCryptDestroyHash(hH);
    BCryptCloseAlgorithmProvider(hA, 0);
}
int pymcl_file_matches(const char *path, const char *sha1, long long size) {
    if (!pymcl_file_exists(path)) return 0;
    if (size >= 0 && pymcl_file_size(path) != size) return 0;
    if (sha1 && sha1[0]) {
        char hex[41];
        if (pymcl_sha1_file(path, hex) != 0) return 0;
        return _stricmp(hex, sha1) == 0;
    }
    return size >= 0;
}

int pymcl_open_folder(const char *path) {
    wchar_t *w = pymcl_u8_to_wide(path);
    if (!w) return -1;
    ShellExecuteW(NULL, L"open", w, NULL, NULL, SW_SHOWNORMAL);
    free(w);
    return 0;
}

static char *quote_arg(const char *a) {
    size_t n = strlen(a);
    int need = 0;
    for (size_t i = 0; i < n; i++) if (a[i] == ' ' || a[i] == '"') need = 1;
    if (!need) return pymcl_strdup(a);
    char *o = (char *)malloc(n * 2 + 3);
    char *p = o;
    *p++ = '"';
    for (size_t i = 0; i < n; i++) {
        if (a[i] == '"') *p++ = '\\';
        *p++ = a[i];
    }
    *p++ = '"'; *p = 0;
    return o;
}
static char *join_cmdline(const char **argv, int argc) {
    size_t cap = 16;
    char *s = (char *)malloc(cap);
    s[0] = 0;
    size_t len = 0;
    for (int i = 0; i < argc; i++) {
        char *q = quote_arg(argv[i]);
        size_t n = strlen(q);
        if (len + n + 2 > cap) { cap = (len + n + 2) * 2; s = (char *)realloc(s, cap); }
        if (len) s[len++] = ' ';
        memcpy(s + len, q, n + 1);
        len += n;
        free(q);
    }
    return s;
}
int pymcl_run_process(const char **argv, int argc, const char *cwd,
                      void (*on_line)(void *, const char *), void *ud, int timeout_sec) {
    HANDLE rd = NULL;
    HANDLE proc = pymcl_spawn_process(argv, argc, cwd, &rd);
    if (!proc) return -1;
    DWORD deadline = timeout_sec > 0 ? GetTickCount() + (DWORD)timeout_sec * 1000 : 0;
    char buf[4096]; char acc[8192]; size_t al = 0; acc[0] = 0;
    for (;;) {
        DWORD got = 0, avail = 0;
        if (PeekNamedPipe(rd, NULL, 0, NULL, &avail, NULL) && avail) {
            if (avail > sizeof(buf)) avail = sizeof(buf);
            if (ReadFile(rd, buf, avail, &got, NULL) && got) {
                for (DWORD i = 0; i < got; i++) {
                    if (buf[i] == '\n' || al >= sizeof(acc) - 2) {
                        acc[al] = 0;
                        if (al && acc[al - 1] == '\r') acc[al - 1] = 0;
                        if (on_line) on_line(ud, acc);
                        al = 0;
                    } else acc[al++] = buf[i];
                }
            }
        }
        DWORD st = WaitForSingleObject(proc, 50);
        if (st == WAIT_OBJECT_0) break;
        if (deadline && GetTickCount() > deadline) {
            TerminateProcess(proc, 1);
            CloseHandle(rd); CloseHandle(proc);
            return -1;
        }
    }
    if (al && on_line) { acc[al] = 0; on_line(ud, acc); }
    DWORD code = 1;
    GetExitCodeProcess(proc, &code);
    CloseHandle(rd); CloseHandle(proc);
    return (int)code;
}
HANDLE pymcl_spawn_process(const char **argv, int argc, const char *cwd, HANDLE *out_read) {
    SECURITY_ATTRIBUTES sa = { sizeof(sa), NULL, TRUE };
    HANDLE rd, wr;
    if (!CreatePipe(&rd, &wr, &sa, 0)) return NULL;
    SetHandleInformation(rd, HANDLE_FLAG_INHERIT, 0);
    STARTUPINFOW si; PROCESS_INFORMATION pi;
    memset(&si, 0, sizeof(si)); memset(&pi, 0, sizeof(pi));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    si.hStdOutput = wr;
    si.hStdError = wr;
    si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    char *cmd = join_cmdline(argv, argc);
    wchar_t *wcmd = pymcl_u8_to_wide(cmd);
    wchar_t *wcwd = cwd ? pymcl_u8_to_wide(cwd) : NULL;
    free(cmd);
    BOOL ok = CreateProcessW(NULL, wcmd, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, wcwd, &si, &pi);
    free(wcmd); free(wcwd);
    CloseHandle(wr);
    if (!ok) {
        CloseHandle(rd);
        pymcl_set_error("无法启动进程");
        return NULL;
    }
    CloseHandle(pi.hThread);
    if (out_read) *out_read = rd;
    else CloseHandle(rd);
    return pi.hProcess;
}

void pymcl_dashed_uuid(const char *in, char out[40]) {
    char hex[33] = {0};
    int j = 0;
    for (const char *p = in ? in : ""; *p && j < 32; p++) {
        if ((*p >= '0' && *p <= '9') || (*p >= 'a' && *p <= 'f') || (*p >= 'A' && *p <= 'F'))
            hex[j++] = (char)tolower((unsigned char)*p);
    }
    if (j != 32) { snprintf(out, 40, "%s", in ? in : ""); return; }
    snprintf(out, 40, "%.8s-%.4s-%.4s-%.4s-%.12s", hex, hex + 8, hex + 12, hex + 16, hex + 20);
}
void pymcl_offline_uuid(const char *name, char out[40]) {
    char key[512];
    snprintf(key, sizeof(key), "OfflinePlayer:%s", name ? name : "Player");
    unsigned char d[16];
    pymcl_md5_bytes(key, strlen(key), d);
    d[6] = (unsigned char)((d[6] & 0x0F) | 0x30);
    d[8] = (unsigned char)((d[8] & 0x3F) | 0x80);
    char hex[33];
    static const char *x = "0123456789abcdef";
    for (int i = 0; i < 16; i++) { hex[i * 2] = x[d[i] >> 4]; hex[i * 2 + 1] = x[d[i] & 15]; }
    hex[32] = 0;
    pymcl_dashed_uuid(hex, out);
}
void pymcl_format_size(double n, char *out, size_t cap) {
    const char *u[] = {"B", "KB", "MB", "GB", "TB"};
    int i = 0;
    while (n >= 1024 && i < 4) { n /= 1024; i++; }
    if (i == 0) snprintf(out, cap, "%d B", (int)n);
    else snprintf(out, cap, "%.1f %s", n, u[i]);
}
int pymcl_maven_path(const char *name, const char *suffix, char *out, size_t n) {
    char buf[512];
    snprintf(buf, sizeof(buf), "%s", name ? name : "");
    if (buf[0] == '[' && buf[strlen(buf) - 1] == ']') {
        buf[strlen(buf) - 1] = 0;
        memmove(buf, buf + 1, strlen(buf));
    }
    const char *ext = suffix ? suffix : "jar";
    char *at = strrchr(buf, '@');
    if (at) { *at = 0; ext = at + 1; }
    char *p1 = strchr(buf, ':');
    if (!p1) return -1;
    *p1 = 0;
    char *p2 = strchr(p1 + 1, ':');
    if (!p2) return -1;
    *p2 = 0;
    char *p3 = strchr(p2 + 1, ':');
    const char *group = buf, *art = p1 + 1, *ver = p2 + 1, *cls = NULL;
    if (p3) { *p3 = 0; cls = p3 + 1; }
    char g[256]; snprintf(g, sizeof(g), "%s", group);
    pymcl_replace_char(g, '.', '/');
    if (cls && cls[0])
        snprintf(out, n, "%s/%s/%s/%s-%s-%s.%s", g, art, ver, art, ver, cls, ext);
    else
        snprintf(out, n, "%s/%s/%s/%s-%s.%s", g, art, ver, art, ver, ext);
    return 0;
}
int pymcl_check_rules(cJSON *rules, int has_custom_res) {
    if (!cJSON_IsArray(rules) || cJSON_GetArraySize(rules) == 0) return 1;
    int allow = 0;
    cJSON *rule;
    cJSON_ArrayForEach(rule, rules) {
        int matched = 1;
        cJSON *os = cJSON_GetObjectItem(rule, "os");
        if (cJSON_IsObject(os)) {
            cJSON *name = cJSON_GetObjectItem(os, "name");
            if (cJSON_IsString(name) && strcmp(name->valuestring, pymcl_os_name()) != 0) matched = 0;
            cJSON *arch = cJSON_GetObjectItem(os, "arch");
            if (cJSON_IsString(arch) && strcmp(arch->valuestring, pymcl_arch()) != 0) matched = 0;
        }
        cJSON *feat = cJSON_GetObjectItem(rule, "features");
        if (cJSON_IsObject(feat) && matched) {
            cJSON *f;
            cJSON_ArrayForEach(f, feat) {
                int want = cJSON_IsTrue(f);
                int have = 0;
                if (strcmp(f->string, "has_custom_resolution") == 0) have = has_custom_res;
                if (want != have) matched = 0;
            }
        }
        if (matched) {
            cJSON *act = cJSON_GetObjectItem(rule, "action");
            allow = !act || !cJSON_IsString(act) || strcmp(act->valuestring, "allow") == 0;
        }
    }
    return allow;
}
void pymcl_replace_placeholders(const char *text, cJSON *map, char *out, size_t n) {
    if (!text) { out[0] = 0; return; }
    size_t o = 0;
    for (const char *p = text; *p && o + 1 < n;) {
        if (p[0] == '$' && p[1] == '{') {
            const char *e = strchr(p + 2, '}');
            if (e) {
                char key[128];
                size_t kn = (size_t)(e - (p + 2));
                if (kn > sizeof(key) - 1) kn = sizeof(key) - 1;
                memcpy(key, p + 2, kn); key[kn] = 0;
                cJSON *v = cJSON_GetObjectItem(map, key);
                if (cJSON_IsString(v)) {
                    size_t vl = strlen(v->valuestring);
                    if (o + vl >= n) vl = n - o - 1;
                    memcpy(out + o, v->valuestring, vl);
                    o += vl;
                    p = e + 1;
                    continue;
                }
            }
        }
        out[o++] = *p++;
    }
    out[o] = 0;
}
int pymcl_has_placeholder(const char *text) {
    return text && strstr(text, "${") != NULL;
}
const char *pymcl_os_name(void) { return "windows"; }
const char *pymcl_arch(void) {
#if defined(_M_ARM64) || defined(__aarch64__)
    return "arm64";
#elif defined(_M_IX86) || defined(__i386__)
    return "x86";
#else
    return "x64";
#endif
}
int pymcl_is_windows(void) { return 1; }
void pymcl_native_arch_token(char *out, size_t n) {
    snprintf(out, n, "%s", strcmp(pymcl_arch(), "x86") == 0 ? "32" : "64");
}

void pymcl_set_root(const char *root) {
    wchar_t *win = pymcl_u8_to_wide(root && root[0] ? root : ".");
    wchar_t full[PYMCL_PATH];
    DWORD n = win ? GetFullPathNameW(win, PYMCL_PATH, full, NULL) : 0;
    /* 环境变量 TMP 常是 8.3 短路径（ADMINI~1），Python 端 Path.resolve() 会展开成长路径，
       这里跟齐，否则两边拼出的绝对路径对不上 */
    if (n && n < PYMCL_PATH) {
        wchar_t longp[PYMCL_PATH];
        DWORD ln = GetLongPathNameW(full, longp, PYMCL_PATH);
        if (ln > 0 && ln < PYMCL_PATH) {
            memcpy(full, longp, sizeof(wchar_t) * (size_t)ln);
            full[ln] = 0;
        }
    }
    free(win);
    char *u8 = (n && n < PYMCL_PATH) ? pymcl_wide_to_u8(full) : pymcl_strdup(root ? root : ".");
    snprintf(g_root, sizeof(g_root), "%s", u8 ? u8 : ".");
    free(u8);
    wchar_t *w = pymcl_u8_to_wide(g_root);
    if (w) {
        SetEnvironmentVariableW(L"PYMCL_HOME", w);
        SetCurrentDirectoryW(w);
        free(w);
    }
}
void pymcl_instances_dir(char *out, size_t n) {
    pymcl_path_join(out, n, g_root, config_str("instances_dir", ".minecraft"));
}
void pymcl_java_dir(char *out, size_t n) {
    pymcl_path_join(out, n, g_root, config_str("java_dir", "java"));
}
void pymcl_cache_dir(char *out, size_t n) {
    pymcl_path_join(out, n, g_root, "cache");
}

/* ---------- argsplit.split_args：shlex POSIX 风格切分（认引号） ---------- */

static void split_args_push(char ***out, int *n, const char *begin, size_t len) {
    *out = (char **)realloc(*out, sizeof(char *) * (size_t)(*n + 1));
    char *s = (char *)malloc(len + 1);
    memcpy(s, begin, len);
    s[len] = 0;
    (*out)[(*n)++] = s;
}

int pymcl_split_args(const char *text, char ***out, int *n) {
    *out = NULL; *n = 0;
    const char *p = text ? text : "";
    while (*p && isspace((unsigned char)*p)) p++;
    if (!*p) return 0;
    char buf[8192];
    size_t bl = 0;
    int unbalanced = 0;
    const char *tok = NULL;
    for (; *p; p++) {
        if (tok && isspace((unsigned char)*p)) {   /* 段结束 */
            split_args_push(out, n, buf, bl);
            buf[0] = 0; bl = 0; tok = NULL;
            continue;
        }
        if (!tok) tok = p;
        if (*p == '\'') {                          /* 单引号：内容原样 */
            const char *e = strchr(p + 1, '\'');
            if (!e) { unbalanced = 1; break; }
            for (const char *q = p + 1; q < e && bl < sizeof(buf) - 1; q++) buf[bl++] = *q;
            p = e;
        } else if (*p == '"') {                    /* 双引号：反斜杠转义引号、反斜杠等 */
            p++;
            while (*p && *p != '"') {
                if (*p == '\\' && (p[1] == '"' || p[1] == '\\' || p[1] == '$' || p[1] == '`') && bl < sizeof(buf) - 1) {
                    p++; buf[bl++] = *p++;
                } else if (bl < sizeof(buf) - 1) buf[bl++] = *p++;
            }
            if (*p != '"') { unbalanced = 1; break; }
        } else if (*p == '\\' && p[1]) {           /* 引号外：反斜杠转义下一字符 */
            if (bl < sizeof(buf) - 1) buf[bl++] = *++p;
        } else if (bl < sizeof(buf) - 1) {
            buf[bl++] = *p;
        }
    }
    if (unbalanced) {                              /* shlex ValueError → 退回空白切分 */
        for (int i = 0; i < *n; i++) free((*out)[i]);
        free(*out); *out = NULL; *n = 0;
        const char *q = text ? text : "";
        while (*q) {
            while (*q && isspace((unsigned char)*q)) q++;
            if (!*q) break;
            const char *e = q;
            while (*e && !isspace((unsigned char)*e)) e++;
            split_args_push(out, n, q, (size_t)(e - q));
            q = e;
        }
        return *n;
    }
    if (tok || bl) split_args_push(out, n, buf, bl);
    return *n;
}

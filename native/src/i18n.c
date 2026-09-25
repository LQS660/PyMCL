#include "pymcl.h"
#include <ctype.h>
#include <pthread.h>

/* mclauncher/i18n.py 的移植：词表是 mclauncher/locales/<lang>.json，键就是中文原文。
   zh_CN 与 en 互不回退（中文界面上漏译也不许冒英文），第三方语言回退 en 再回退原文。 */

#define DEFAULT_LANG "zh_CN"

static cJSON *g_strings;           /* { lang: { key: text } } */
static char g_lang[32] = DEFAULT_LANG;
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;

static int exe_dir(char *out, size_t n) {
    wchar_t w[PYMCL_PATH];
    DWORD len = GetModuleFileNameW(NULL, w, PYMCL_PATH);
    if (!len || len >= PYMCL_PATH) return -1;
    char *u = pymcl_wide_to_u8(w);
    if (!u) return -1;
    pymcl_parent(u, out, n);
    free(u);
    return 0;
}

/* 词表位置：打包后在 native\data\locales；开发时 exe 在 native\build，往上两级就是项目根 */
static int find_locales(char *out, size_t n) {
    char ed[PYMCL_PATH], up[PYMCL_PATH], cand[PYMCL_PATH];
    if (exe_dir(ed, sizeof(ed)) == 0) {
        pymcl_parent(ed, up, sizeof(up));
        pymcl_path_join3(cand, sizeof(cand), up, "data", "locales");
        if (pymcl_dir_exists(cand)) { snprintf(out, n, "%s", cand); return 0; }
        char up2[PYMCL_PATH];
        pymcl_parent(up, up2, sizeof(up2));
        pymcl_path_join3(cand, sizeof(cand), up2, "mclauncher", "locales");
        if (pymcl_dir_exists(cand)) { snprintf(out, n, "%s", cand); return 0; }
    }
    pymcl_path_join3(cand, sizeof(cand), g_root, "mclauncher", "locales");
    if (pymcl_dir_exists(cand)) { snprintf(out, n, "%s", cand); return 0; }
    pymcl_path_join3(cand, sizeof(cand), g_root, "native", "data");
    pymcl_path_join(cand, sizeof(cand), cand, "locales");
    if (pymcl_dir_exists(cand)) { snprintf(out, n, "%s", cand); return 0; }
    return -1;
}

static void load_strings(void) {
    g_strings = cJSON_CreateObject();
    char dir[PYMCL_PATH];
    if (find_locales(dir, sizeof(dir)) == 0) {
        cJSON *names = pymcl_list_dir(dir, 0, 0);
        cJSON *it;
        cJSON_ArrayForEach(it, names) {
            const char *fn = it->valuestring;
            if (!pymcl_endswith(fn, ".json")) continue;
            char lang[64];
            snprintf(lang, sizeof(lang), "%.*s", (int)(strlen(fn) - 5), fn);
            char p[PYMCL_PATH];
            pymcl_path_join(p, sizeof(p), dir, fn);
            cJSON *data = pymcl_read_json(p);
            if (cJSON_IsObject(data)) cJSON_AddItemToObject(g_strings, lang, data);
            else cJSON_Delete(data);
        }
        cJSON_Delete(names);
    }
    if (!cJSON_GetObjectItemCaseSensitive(g_strings, DEFAULT_LANG))
        cJSON_AddItemToObject(g_strings, DEFAULT_LANG, cJSON_CreateObject());
    if (!cJSON_GetObjectItemCaseSensitive(g_strings, "en"))
        cJSON_AddItemToObject(g_strings, "en", cJSON_CreateObject());
}

static void ensure(void) {
    pthread_mutex_lock(&g_mu);
    if (!g_strings) load_strings();
    pthread_mutex_unlock(&g_mu);
}

static void normalize_lang(const char *raw, char *out, size_t n) {
    const char *s = raw ? raw : "";
    while (*s && isspace((unsigned char)*s)) s++;
    snprintf(out, n, "%s", s);
    size_t len = strlen(out);
    while (len && isspace((unsigned char)out[len - 1])) out[--len] = 0;
    for (char *p = out; *p; p++) if (*p == '-') *p = '_';
}

cJSON *i18n_available_languages(void) {
    ensure();
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "zh_CN", "简体中文");
    cJSON_AddStringToObject(o, "en", "English");
    cJSON *it;
    cJSON_ArrayForEach(it, g_strings) {
        if (!cJSON_GetObjectItemCaseSensitive(o, it->string))
            cJSON_AddStringToObject(o, it->string, it->string);
    }
    return o;
}

const char *i18n_current(void) { return g_lang; }

/* set_language：认不出的语言回 zh_CN，并写进 config.json */
void i18n_set_language(const char *lang) {
    ensure();
    char l[64];
    normalize_lang(lang && lang[0] ? lang : DEFAULT_LANG, l, sizeof(l));
    if (!l[0]) snprintf(l, sizeof(l), DEFAULT_LANG);
    if (!cJSON_GetObjectItemCaseSensitive(g_strings, l)) snprintf(l, sizeof(l), DEFAULT_LANG);
    snprintf(g_lang, sizeof(g_lang), "%s", l);
    config_set_str("language", l);
    config_save();
}

/* bridge/server.py _init_language：PYMCL_LANG 只管本进程、不落盘；否则按 config.json 的 language */
void i18n_init(const char *override_lang) {
    ensure();
    char o[64];
    normalize_lang(override_lang && override_lang[0] ? override_lang : getenv("PYMCL_LANG"), o, sizeof(o));
    if (!o[0]) {
        i18n_set_language(config_str("language", ""));
        return;
    }
    if (cJSON_GetObjectItemCaseSensitive(g_strings, o)) snprintf(g_lang, sizeof(g_lang), "%s", o);
}

static const char *lookup(const char *key, const char *lang) {
    cJSON *data = cJSON_GetObjectItemCaseSensitive(g_strings, lang);
    cJSON *v = data ? cJSON_GetObjectItemCaseSensitive(data, key) : NULL;
    if (v) return cJSON_IsString(v) ? v->valuestring : NULL;
    if (strcmp(lang, DEFAULT_LANG) != 0 && strcmp(lang, "en") != 0) {
        cJSON *en = cJSON_GetObjectItemCaseSensitive(g_strings, "en");
        v = en ? cJSON_GetObjectItemCaseSensitive(en, key) : NULL;
        if (cJSON_IsString(v)) return v->valuestring;
    }
    return NULL;
}

/* _(key, lang)：找不到返回 key 本身。返回的指针归词表或调用方的 key 所有，别 free。 */
const char *tr_lang(const char *key, const char *lang) {
    if (!key) return "";
    ensure();
    const char *v = lookup(key, lang && lang[0] ? lang : g_lang);
    return v ? v : key;
}

const char *tr(const char *key) { return tr_lang(key, NULL); }

void tr_fmt0(char *out, size_t n, const char *key, const char *arg) {
    const char *t = tr(key);
    const char *ph = strstr(t, "{0}");
    if (!ph || !arg) { snprintf(out, n, "%s", t); return; }
    snprintf(out, n, "%.*s%s%s", (int)(ph - t), t, arg, ph + 3);
}

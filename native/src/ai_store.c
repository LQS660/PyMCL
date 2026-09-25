#include "pymcl.h"
#include <bcrypt.h>
#include <ctype.h>

/* AI 的持久化部分：mclauncher/ai/store.py（多对话）、permission.py 的规则库、
   client.py 的 resolve_endpoint / test_connection。回合内核在 ai_agent.c。 */

#define MAX_CHATS 40
#define MAX_MESSAGES 200
#define DEFAULT_MODEL "deepseek-v4-flash"
#define CLIENT_HEADER "PyMCL/1.0.1"
#define RULE_SEP "\x1f"   /* Python 端是 \0；进出桥时 server.c 负责互换 */

static const char *pstr(cJSON *o, const char *k, const char *def) {
    const char *s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, k));
    return s ? s : def;
}

static CRITICAL_SECTION g_cs;
static volatile LONG g_cs_state;

void ai_store_lock(void) {
    if (InterlockedCompareExchange(&g_cs_state, 1, 0) == 0) {
        InitializeCriticalSection(&g_cs);
        g_cs_state = 2;
    }
    while (g_cs_state != 2) Sleep(0);
    EnterCriticalSection(&g_cs);
}
void ai_store_unlock(void) { LeaveCriticalSection(&g_cs); }

void ai_new_id(char out[13]) {
    unsigned char b[6];
    BCryptGenRandom(NULL, b, sizeof(b), BCRYPT_USE_SYSTEM_PREFERRED_RNG);
    static const char hex[] = "0123456789abcdef";
    for (int i = 0; i < 6; i++) { out[i * 2] = hex[b[i] >> 4]; out[i * 2 + 1] = hex[b[i] & 15]; }
    out[12] = 0;
}

static void store_path(char *out, size_t n) { pymcl_path_join(out, n, g_root, "ai_chats.json"); }

static void u8_trunc(char *s, size_t max) {
    size_t chars = 0;
    for (char *p = s; *p; p++) {
        if (((unsigned char)*p & 0xC0) != 0x80) {
            if (chars == max) { *p = 0; return; }
            chars++;
        }
    }
}

static cJSON *blank_chat(const char *cid) {
    cJSON *c = cJSON_CreateObject();
    char id[13];
    if (!cid) { ai_new_id(id); cid = id; }
    cJSON_AddStringToObject(c, "id", cid);
    cJSON_AddStringToObject(c, "title", "新对话");
    cJSON_AddNumberToObject(c, "updated", (double)time(NULL));
    cJSON_AddItemToObject(c, "messages", cJSON_CreateArray());
    return c;
}

/* store._load_message：role/content + 工具轨迹字段 */
cJSON *ai_load_message(cJSON *m) {
    cJSON *o = cJSON_CreateObject();
    cJSON *role = cJSON_GetObjectItemCaseSensitive(m, "role");
    cJSON_AddItemToObject(o, "role", role ? cJSON_Duplicate(role, 1) : cJSON_CreateNull());
    cJSON *content = cJSON_GetObjectItemCaseSensitive(m, "content");
    cJSON_AddItemToObject(o, "content", py_truthy(content) ? cJSON_Duplicate(content, 1) : cJSON_CreateString(""));
    static const char *keep[] = {"tool_calls", "tool_call_id", "name", "id", "note"};
    for (int i = 0; i < 5; i++) {
        cJSON *v = cJSON_GetObjectItemCaseSensitive(m, keep[i]);
        if (v && !cJSON_IsNull(v)) cJSON_AddItemToObject(o, keep[i], cJSON_Duplicate(v, 1));
    }
    return o;
}

void ai_store_save(cJSON *data) {
    cJSON *chats = cJSON_GetObjectItemCaseSensitive(data, "chats");
    while (cJSON_GetArraySize(chats) > MAX_CHATS) cJSON_DeleteItemFromArray(chats, MAX_CHATS);
    const char *active = pstr(data, "active_id", "");
    int found = 0;
    cJSON *c;
    cJSON_ArrayForEach(c, chats) if (!strcmp(pstr(c, "id", ""), active)) found = 1;
    if (cJSON_GetArraySize(chats) && !found) {
        cJSON_ReplaceItemInObjectCaseSensitive(data, "active_id", cJSON_CreateString(pstr(cJSON_GetArrayItem(chats, 0), "id", "")));
    }
    cJSON *out = cJSON_CreateObject();
    cJSON_AddStringToObject(out, "active_id", cJSON_GetArraySize(chats) ? pstr(data, "active_id", "") : "");
    cJSON_AddItemToObject(out, "chats", chats ? cJSON_Duplicate(chats, 1) : cJSON_CreateArray());
    char p[PYMCL_PATH];
    store_path(p, sizeof(p));
    pymcl_write_json(p, out);
    cJSON_Delete(out);
}

static cJSON *empty_store(void) {
    char id[13];
    ai_new_id(id);
    cJSON *d = cJSON_CreateObject();
    cJSON_AddStringToObject(d, "active_id", id);
    cJSON *chats = cJSON_CreateArray();
    cJSON_AddItemToArray(chats, blank_chat(id));
    cJSON_AddItemToObject(d, "chats", chats);
    return d;
}

static int valid_role(const char *r) {
    return r && (!strcmp(r, "user") || !strcmp(r, "assistant") || !strcmp(r, "error") || !strcmp(r, "tool"));
}

/* store.load */
cJSON *ai_store_load(void) {
    char p[PYMCL_PATH];
    store_path(p, sizeof(p));
    cJSON *data = pymcl_read_json(p);
    cJSON *raw_chats = cJSON_GetObjectItemCaseSensitive(data, "chats");
    if (!cJSON_IsObject(data) || !cJSON_IsArray(raw_chats) || cJSON_GetArraySize(raw_chats) == 0) {
        cJSON_Delete(data);
        cJSON *d = empty_store();
        ai_store_save(d);
        return d;
    }
    cJSON *chats = cJSON_CreateArray();
    cJSON *raw;
    cJSON_ArrayForEach(raw, raw_chats) {
        cJSON *rid = cJSON_GetObjectItemCaseSensitive(raw, "id");
        if (!cJSON_IsObject(raw) || !py_truthy(rid)) continue;
        cJSON *e = cJSON_CreateObject();
        char buf[1024];
        py_str(rid, buf, sizeof(buf));
        cJSON_AddStringToObject(e, "id", buf);
        cJSON *t = cJSON_GetObjectItemCaseSensitive(raw, "title");
        if (py_truthy(t)) py_str(t, buf, sizeof(buf)); else snprintf(buf, sizeof(buf), "对话");
        u8_trunc(buf, 40);
        cJSON_AddStringToObject(e, "title", buf);
        cJSON *up = cJSON_GetObjectItemCaseSensitive(raw, "updated");
        cJSON_AddNumberToObject(e, "updated", (double)(py_truthy(up) ? py_int_or(up, 0) : 0));
        cJSON *msgs = cJSON_CreateArray();
        cJSON *m;
        cJSON_ArrayForEach(m, cJSON_GetObjectItemCaseSensitive(raw, "messages")) {
            if (cJSON_IsObject(m) && valid_role(cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(m, "role"))))
                cJSON_AddItemToArray(msgs, ai_load_message(m));
        }
        while (cJSON_GetArraySize(msgs) > MAX_MESSAGES) cJSON_DeleteItemFromArray(msgs, 0);
        cJSON_AddItemToObject(e, "messages", msgs);
        cJSON *plan = cJSON_GetObjectItemCaseSensitive(raw, "plan");
        if (cJSON_IsObject(plan)) cJSON_AddItemToObject(e, "plan", cJSON_Duplicate(plan, 1));
        cJSON_AddItemToArray(chats, e);
    }
    if (cJSON_GetArraySize(chats) == 0) {
        cJSON_Delete(chats);
        cJSON_Delete(data);
        cJSON *d = empty_store();
        ai_store_save(d);
        return d;
    }
    char active[256] = "";
    cJSON *av = cJSON_GetObjectItemCaseSensitive(data, "active_id");
    if (py_truthy(av)) py_str(av, active, sizeof(active));
    int found = 0;
    cJSON *c;
    cJSON_ArrayForEach(c, chats) if (!strcmp(pstr(c, "id", ""), active)) found = 1;
    if (!found) snprintf(active, sizeof(active), "%s", pstr(cJSON_GetArrayItem(chats, 0), "id", ""));
    cJSON_Delete(data);
    cJSON *out = cJSON_CreateObject();
    cJSON_AddStringToObject(out, "active_id", active);
    cJSON_AddItemToObject(out, "chats", chats);
    return out;
}

cJSON *ai_store_get_chat(cJSON *data, const char *cid) {
    cJSON *c;
    cJSON_ArrayForEach(c, cJSON_GetObjectItemCaseSensitive(data, "chats"))
        if (!strcmp(pstr(c, "id", ""), cid ? cid : "")) return c;
    return NULL;
}

/* BackendAPI._localize_chats：只翻返回的拷贝 */
static cJSON *localize_chats(cJSON *data) {
    cJSON *out = cJSON_Duplicate(data, 1);
    cJSON *c;
    cJSON_ArrayForEach(c, cJSON_GetObjectItemCaseSensitive(out, "chats")) {
        const char *t = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(c, "title"));
        if (t && (!t[0] || !strcmp(t, "新对话")))
            cJSON_ReplaceItemInObjectCaseSensitive(c, "title", cJSON_CreateString(tr("新对话")));
    }
    return out;
}

/* ---------- 权限规则库 permission.py ---------- */

static const char *k_tools[] = {
    "ask_user", "get_launcher_state", "list_instances", "list_installed_versions", "search_versions",
    "search_mods", "search_modpacks", "list_mods", "install_game", "install_mod", "install_modpack",
    "install_shader", "install_resourcepack", "install_datapack", "search_content", "search_worlds",
    "install_world", "create_instance", "delete_instance", "delete_mod", "disable_mod", "enable_mod",
    "get_java_list", "download_java", "launch_game", "diagnose_launch", "get_latest_log",
    "get_crash_report", "scan_mod_conflicts", "inspect_mod", "list_mod_configs", "read_mod_config",
    "write_mod_config", "read_artifact", "dispatch_subagent", "update_plan", NULL};

int ai_is_tool(const char *name) {
    for (int i = 0; k_tools[i]; i++) if (!strcmp(k_tools[i], name)) return 1;
    return 0;
}

static void rules_path(char *out, size_t n) { pymcl_path_join(out, n, g_root, "ai_permissions.json"); }

static cJSON *blank_rule_store(void) {
    return cJSON_Parse("{\"version\":1,\"global\":{\"allow\":[],\"deny\":[],\"ask\":[]},\"per_instance\":{}}");
}

static const char *k_buckets[] = {"allow", "deny", "ask"};

cJSON *ai_rule_store_load(void) {
    char p[PYMCL_PATH];
    rules_path(p, sizeof(p));
    cJSON *data = pymcl_read_json(p);
    cJSON *store = blank_rule_store();
    if (!cJSON_IsObject(data)) { cJSON_Delete(data); return store; }
    cJSON *g = cJSON_GetObjectItemCaseSensitive(data, "global");
    for (int i = 0; i < 3; i++) {
        cJSON *vals = cJSON_GetObjectItemCaseSensitive(g, k_buckets[i]);
        if (cJSON_IsArray(vals))
            cJSON_ReplaceItemInObjectCaseSensitive(cJSON_GetObjectItemCaseSensitive(store, "global"), k_buckets[i], cJSON_Duplicate(vals, 1));
    }
    cJSON *per = cJSON_GetObjectItemCaseSensitive(data, "per_instance");
    if (cJSON_IsObject(per)) {
        cJSON *np = cJSON_CreateObject();
        cJSON *it;
        cJSON_ArrayForEach(it, per) {
            if (!cJSON_IsObject(it)) continue;
            cJSON *sec = cJSON_CreateObject();
            for (int i = 0; i < 3; i++) {
                cJSON *v = cJSON_GetObjectItemCaseSensitive(it, k_buckets[i]);
                cJSON_AddItemToObject(sec, k_buckets[i], cJSON_IsArray(v) ? cJSON_Duplicate(v, 1) : cJSON_CreateArray());
            }
            cJSON_AddItemToObject(np, it->string, sec);
        }
        cJSON_ReplaceItemInObjectCaseSensitive(store, "per_instance", np);
    }
    cJSON_Delete(data);
    return store;
}

static void rule_store_save(cJSON *store) {
    char p[PYMCL_PATH];
    rules_path(p, sizeof(p));
    pymcl_write_json(p, store);
}

/* _coerce_rule：认得的才算，behavior 非法就丢 */
static int coerce_rule(cJSON *raw, char *tool, size_t tn, char *content, size_t cn) {
    if (!cJSON_IsObject(raw)) return 0;
    cJSON *t = cJSON_GetObjectItemCaseSensitive(raw, "toolName");
    if (!py_truthy(t)) t = cJSON_GetObjectItemCaseSensitive(raw, "tool_name");
    tool[0] = 0;
    if (py_truthy(t)) py_str(t, tool, tn);
    cJSON *rc = cJSON_GetObjectItemCaseSensitive(raw, "ruleContent");
    content[0] = 0;
    if (py_truthy(rc)) py_str(rc, content, cn);
    cJSON *b = cJSON_GetObjectItemCaseSensitive(raw, "behavior");
    char beh[64] = "allow";
    if (py_truthy(b)) py_str(b, beh, sizeof(beh));
    return !strcmp(beh, "allow") || !strcmp(beh, "deny") || !strcmp(beh, "ask");
}

static const char *behavior_label(const char *b) {
    if (!strcmp(b, "allow")) return "允许";
    if (!strcmp(b, "deny")) return "禁止";
    return "每次问";
}

static void add_rule_rows(cJSON *out, cJSON *section, const char *inst) {
    for (int i = 0; i < 3; i++) {
        cJSON *raw;
        cJSON_ArrayForEach(raw, cJSON_GetObjectItemCaseSensitive(section, k_buckets[i])) {
            char tool[256], content[1024], key[1400];
            if (!coerce_rule(raw, tool, sizeof(tool), content, sizeof(content))) continue;
            snprintf(key, sizeof(key), "%s" RULE_SEP "%s", tool, content);
            cJSON *r = cJSON_CreateObject();
            cJSON_AddStringToObject(r, "key", key);
            cJSON_AddStringToObject(r, "toolName", tool);
            cJSON_AddStringToObject(r, "ruleContent", content);
            cJSON_AddStringToObject(r, "behavior", k_buckets[i]);
            cJSON_AddStringToObject(r, "behavior_label", tr(behavior_label(k_buckets[i])));
            cJSON_AddStringToObject(r, "instance", inst);
            if (inst[0]) {
                char scope[512];
                const char *fmt = tr("实例 {0}");
                const char *ph = strstr(fmt, "{0}");
                if (ph) snprintf(scope, sizeof(scope), "%.*s%s%s", (int)(ph - fmt), fmt, inst, ph + 3);
                else snprintf(scope, sizeof(scope), "%s", fmt);
                cJSON_AddStringToObject(r, "scope", scope);
            } else {
                cJSON_AddStringToObject(r, "scope", tr("全局"));
            }
            cJSON_AddItemToArray(out, r);
        }
    }
}

cJSON *ai_list_stored_rules(void) {
    cJSON *store = ai_rule_store_load();
    cJSON *out = cJSON_CreateArray();
    add_rule_rows(out, cJSON_GetObjectItemCaseSensitive(store, "global"), "");
    cJSON *it;
    cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(store, "per_instance")) add_rule_rows(out, it, it->string);
    cJSON_Delete(store);
    return out;
}

/* permission.append_rule */
void ai_append_rule(const char *tool, const char *content, const char *behavior, const char *instance) {
    ai_store_lock();
    cJSON *store = ai_rule_store_load();
    cJSON *target;
    if (instance && instance[0]) {
        cJSON *per = cJSON_GetObjectItemCaseSensitive(store, "per_instance");
        target = cJSON_GetObjectItemCaseSensitive(per, instance);
        if (!target) {
            target = cJSON_Parse("{\"allow\":[],\"deny\":[],\"ask\":[]}");
            cJSON_AddItemToObject(per, instance, target);
        }
    } else {
        target = cJSON_GetObjectItemCaseSensitive(store, "global");
    }
    cJSON *lst = cJSON_GetObjectItemCaseSensitive(target, behavior);
    if (!lst) { lst = cJSON_CreateArray(); cJSON_AddItemToObject(target, behavior, lst); }
    int exists = 0;
    cJSON *r;
    cJSON_ArrayForEach(r, lst) {
        char t[256] = "", c[1024] = "";
        cJSON *tv = cJSON_GetObjectItemCaseSensitive(r, "toolName"), *cv = cJSON_GetObjectItemCaseSensitive(r, "ruleContent");
        if (tv) py_str(tv, t, sizeof(t));
        if (py_truthy(cv)) py_str(cv, c, sizeof(c));
        if (!strcmp(t, tool) && !strcmp(c, content ? content : "")) exists = 1;
    }
    if (!exists) {
        cJSON *e = cJSON_CreateObject();
        cJSON_AddStringToObject(e, "toolName", tool);
        if (content && content[0]) cJSON_AddStringToObject(e, "ruleContent", content);
        cJSON_AddItemToArray(lst, e);
    }
    rule_store_save(store);
    cJSON_Delete(store);
    ai_store_unlock();
}

/* permission.remove_rule(key, instance)：instance "" 只删全局那条 */
static void remove_rule(const char *key, const char *instance) {
    ai_store_lock();
    cJSON *store = ai_rule_store_load();
    cJSON *sections[1] = {NULL};
    if (!instance[0]) sections[0] = cJSON_GetObjectItemCaseSensitive(store, "global");
    else sections[0] = cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(store, "per_instance"), instance);
    int removed = 0;
    if (sections[0]) {
        for (int i = 0; i < 3; i++) {
            cJSON *lst = cJSON_GetObjectItemCaseSensitive(sections[0], k_buckets[i]);
            cJSON *keep = cJSON_CreateArray();
            cJSON *raw;
            cJSON_ArrayForEach(raw, lst) {
                char tool[256], content[1024], k[1400];
                if (coerce_rule(raw, tool, sizeof(tool), content, sizeof(content))) {
                    snprintf(k, sizeof(k), "%s" RULE_SEP "%s", tool, content);
                    if (!strcmp(k, key)) { removed = 1; continue; }
                }
                cJSON_AddItemToArray(keep, cJSON_Duplicate(raw, 1));
            }
            if (lst) cJSON_ReplaceItemInObjectCaseSensitive(sections[0], k_buckets[i], keep);
            else cJSON_AddItemToObject(sections[0], k_buckets[i], keep);
        }
    }
    if (removed) rule_store_save(store);
    cJSON_Delete(store);
    ai_store_unlock();
}

/* ---------- client.resolve_endpoint / test_connection ---------- */

static void strip_copy(const char *s, char *out, size_t n) {
    while (s && *s && isspace((unsigned char)*s)) s++;
    snprintf(out, n, "%s", s ? s : "");
    size_t len = strlen(out);
    while (len && isspace((unsigned char)out[len - 1])) out[--len] = 0;
}

/* 返回 0 成功；失败时 pymcl_error 里是 AIClientError 的文案 */
int ai_resolve_endpoint(cJSON *settings, ai_endpoint *ep) {
    memset(ep, 0, sizeof(*ep));
    char mode[64], model[256];
    cJSON *mv = cJSON_GetObjectItemCaseSensitive(settings, "ai_mode");
    char raw[256] = "public";
    if (py_truthy(mv)) py_str(mv, raw, sizeof(raw));
    strip_copy(raw, mode, sizeof(mode));
    for (char *p = mode; *p; p++) *p = (char)tolower((unsigned char)*p);
    cJSON *md = cJSON_GetObjectItemCaseSensitive(settings, "ai_model");
    snprintf(raw, sizeof(raw), "%s", DEFAULT_MODEL);
    if (py_truthy(md)) py_str(md, raw, sizeof(raw));
    strip_copy(raw, model, sizeof(model));
    if (!model[0]) snprintf(model, sizeof(model), "%s", DEFAULT_MODEL);
    snprintf(ep->model, sizeof(ep->model), "%s", model);
    if (!strcmp(mode, "custom") || !strcmp(mode, "newapi") || !strcmp(mode, "自定义")) {
        char base[1024] = "", key[1024] = "";
        cJSON *b = cJSON_GetObjectItemCaseSensitive(settings, "ai_base_url"), *k = cJSON_GetObjectItemCaseSensitive(settings, "ai_api_key");
        char tmp[1024] = "";
        if (py_truthy(b)) py_str(b, tmp, sizeof(tmp));
        strip_copy(tmp, base, sizeof(base));
        size_t bl = strlen(base);
        while (bl && base[bl - 1] == '/') base[--bl] = 0;
        if (bl && !(bl >= 3 && !strcmp(base + bl - 3, "/v1"))) strncat(base, "/v1", sizeof(base) - strlen(base) - 1);
        tmp[0] = 0;
        if (py_truthy(k)) py_str(k, tmp, sizeof(tmp));
        strip_copy(tmp, key, sizeof(key));
        if (!base[0]) { pymcl_set_error("请在设置里填写自定义 NewAPI 地址（到 /v1 为止）"); return -1; }
        if (!key[0]) { pymcl_set_error("请在设置里填写 NewAPI 令牌"); return -1; }
        snprintf(ep->url, sizeof(ep->url), "%s/chat/completions", base);
        snprintf(ep->models_url, sizeof(ep->models_url), "%s/models", base);
        snprintf(ep->headers, sizeof(ep->headers), "Authorization: Bearer %s\r\nContent-Type: application/json", key);
        ep->is_public = 0;
        return 0;
    }
    char gw[1024] = "", tmp[1024] = "";
    cJSON *g = cJSON_GetObjectItemCaseSensitive(settings, "ai_gateway_url");
    if (py_truthy(g)) py_str(g, tmp, sizeof(tmp));
    strip_copy(tmp, gw, sizeof(gw));
    size_t gl = strlen(gw);
    while (gl && gw[gl - 1] == '/') gw[--gl] = 0;
    if (gw[0]) {
        snprintf(ep->url, sizeof(ep->url), "%s/pymcl/chat", gw);
        snprintf(ep->models_url, sizeof(ep->models_url), "%s/health", gw);
        snprintf(ep->headers, sizeof(ep->headers), "Content-Type: application/json\r\nX-PyMCL-Client: %s", CLIENT_HEADER);
        snprintf(ep->model, sizeof(ep->model), "%s", DEFAULT_MODEL);
        ep->is_public = 1;
        return 0;
    }
    pymcl_set_error("还没有配置 AI 网关：请到「设置 → AI 助手」填入自建公益网关地址，"
                    "或切到「自定义 NewAPI」模式填地址与令牌。搭建方法见 ai_gateway/README.md。");
    return -1;
}

/* client._err_text：HTTP 状态 + 上游 error.message（取不到就原文） */
void ai_err_text(int status, const char *body, char *out, size_t n) {
    char prefix[32] = "";
    if (status) snprintf(prefix, sizeof(prefix), "HTTP %d ", status);
    char text[1024] = "";
    cJSON *data = body ? cJSON_Parse(body) : NULL;
    cJSON *err = cJSON_GetObjectItemCaseSensitive(data, "error");
    if (cJSON_IsObject(err)) {
        char msg[512] = "", extra[256] = "", rid[256] = "";
        cJSON *m = cJSON_GetObjectItemCaseSensitive(err, "message");
        if (!py_truthy(m)) m = cJSON_GetObjectItemCaseSensitive(err, "msg");
        if (!py_truthy(m)) m = cJSON_GetObjectItemCaseSensitive(err, "code");
        if (py_truthy(m)) py_str(m, msg, sizeof(msg));
        cJSON *x = cJSON_GetObjectItemCaseSensitive(err, "type");
        if (!py_truthy(x)) x = cJSON_GetObjectItemCaseSensitive(err, "code");
        if (py_truthy(x)) py_str(x, extra, sizeof(extra));
        const char *rk[] = {"request_id", "requestId", "id"};
        for (int i = 0; i < 3 && !rid[0]; i++) {
            cJSON *a = cJSON_GetObjectItemCaseSensitive(data, rk[i]), *b = cJSON_GetObjectItemCaseSensitive(err, rk[i]);
            if (py_truthy(a)) py_str(a, rid, sizeof(rid)); else if (py_truthy(b)) py_str(b, rid, sizeof(rid));
        }
        strip_copy(msg, text, sizeof(text));
        if (extra[0] && !strstr(text, extra)) { strncat(text, text[0] ? " " : "", sizeof(text) - strlen(text) - 1); strncat(text, extra, sizeof(text) - strlen(text) - 1); }
        if (rid[0] && !strstr(msg, rid)) {
            char r2[300];
            snprintf(r2, sizeof(r2), "%srequest id: %s", text[0] ? " " : "", rid);
            strncat(text, r2, sizeof(text) - strlen(text) - 1);
        }
        if (!text[0]) { char *s = cJSON_PrintUnformatted(err); snprintf(text, sizeof(text), "%s", s ? s : ""); cJSON_free(s); }
    } else if (cJSON_IsString(err) && err->valuestring[0]) {
        snprintf(text, sizeof(text), "%s", err->valuestring);
    } else if (cJSON_IsObject(data) && (py_truthy(cJSON_GetObjectItemCaseSensitive(data, "message")) || py_truthy(cJSON_GetObjectItemCaseSensitive(data, "msg")))) {
        cJSON *m = cJSON_GetObjectItemCaseSensitive(data, "message");
        if (!py_truthy(m)) m = cJSON_GetObjectItemCaseSensitive(data, "msg");
        py_str(m, text, sizeof(text));
    } else {
        snprintf(text, sizeof(text), "%s", body && body[0] ? body : "接口错误");
    }
    cJSON_Delete(data);
    snprintf(out, n, "%s%s", prefix, text[0] ? text : "接口错误");
    u8_trunc(out, 800);
}

static cJSON *test_connection(cJSON *settings) {
    ai_endpoint ep;
    if (ai_resolve_endpoint(settings, &ep) != 0) return NULL;
    http_resp r;
    memset(&r, 0, sizeof(r));
    if (http_get(ep.models_url, &r, ep.headers, 15) != 0) {
        char msg[1024];
        snprintf(msg, sizeof(msg), "%s", pymcl_error());
        http_resp_free(&r);
        pymcl_set_error("%s", msg);
        return NULL;
    }
    if (r.status >= 400) {
        char msg[1024];
        ai_err_text(r.status, r.body, msg, sizeof(msg));
        http_resp_free(&r);
        pymcl_set_error("%s", msg);
        return NULL;
    }
    cJSON *data = r.body ? cJSON_Parse(r.body) : NULL;
    http_resp_free(&r);
    if (!data) return cJSON_CreateString("已连通");
    char out[1024];
    cJSON *models = cJSON_GetObjectItemCaseSensitive(data, "data");
    const char *first = NULL;
    int count = 0, has_locked = 0;
    cJSON *m;
    cJSON_ArrayForEach(m, models) {
        const char *id = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(m, "id"));
        if (cJSON_IsObject(m) && id && id[0]) {
            if (!first) first = id;
            count++;
            if (!strcmp(id, ep.model)) has_locked = 1;
        }
    }
    if (ep.is_public) {
        cJSON *svc = cJSON_GetObjectItemCaseSensitive(data, "service");
        if (py_truthy(svc)) {
            char s[256];
            py_str(svc, s, sizeof(s));
            snprintf(out, sizeof(out), "公益接口正常（%s）", s);
        } else if (has_locked || !count) snprintf(out, sizeof(out), "公益接口正常，模型 %s", ep.model);
        else snprintf(out, sizeof(out), "公益接口已连通，但列表里没有 %s（当前有 %s）", ep.model, first);
    } else if (count) {
        snprintf(out, sizeof(out), "NewAPI 正常，可用模型 %d 个，例如 %s", count, first);
    } else {
        snprintf(out, sizeof(out), "NewAPI 已连通");
    }
    cJSON_Delete(data);
    return cJSON_CreateString(out);
}

cJSON *rpc_ai_store_call(const char *method, cJSON *params, sse_emit_fn emit, int *handled) {
    *handled = 1;
    if (!strcmp(method, "ai_list_chats")) {
        ai_store_lock();
        cJSON *data = ai_store_load();
        ai_store_unlock();
        cJSON *out = localize_chats(data);
        cJSON_Delete(data);
        cJSON_AddBoolToObject(out, "busy", ai_is_busy());
        cJSON *card = ai_pending_card();
        cJSON_AddItemToObject(out, "pending_card", card ? card : cJSON_CreateNull());
        return out;
    }
    if (!strcmp(method, "ai_new_chat") || !strcmp(method, "ai_delete_chat") || !strcmp(method, "ai_set_active")) {
        ai_store_lock();
        cJSON *data = ai_store_load();
        const char *cid = pstr(params, "chat_id", "");
        cJSON *chats = cJSON_GetObjectItemCaseSensitive(data, "chats");
        if (!strcmp(method, "ai_new_chat")) {
            cJSON_InsertItemInArray(chats, 0, blank_chat(NULL));
            while (cJSON_GetArraySize(chats) > MAX_CHATS) cJSON_DeleteItemFromArray(chats, MAX_CHATS);
            cJSON_ReplaceItemInObjectCaseSensitive(data, "active_id", cJSON_CreateString(pstr(cJSON_GetArrayItem(chats, 0), "id", "")));
            ai_store_save(data);
        } else if (!strcmp(method, "ai_delete_chat")) {
            int n = cJSON_GetArraySize(chats);
            for (int i = n - 1; i >= 0; i--)
                if (!strcmp(pstr(cJSON_GetArrayItem(chats, i), "id", ""), cid)) cJSON_DeleteItemFromArray(chats, i);
            if (cJSON_GetArraySize(chats) == 0) {
                cJSON *c = blank_chat(NULL);
                cJSON_ReplaceItemInObjectCaseSensitive(data, "active_id", cJSON_CreateString(pstr(c, "id", "")));
                cJSON_AddItemToArray(chats, c);
            } else if (!strcmp(pstr(data, "active_id", ""), cid)) {
                cJSON_ReplaceItemInObjectCaseSensitive(data, "active_id", cJSON_CreateString(pstr(cJSON_GetArrayItem(chats, 0), "id", "")));
            }
            ai_store_save(data);
        } else if (ai_store_get_chat(data, cid)) {
            cJSON_ReplaceItemInObjectCaseSensitive(data, "active_id", cJSON_CreateString(cid));
            ai_store_save(data);
        }
        ai_store_unlock();
        cJSON *out = localize_chats(data);
        cJSON_Delete(data);
        return out;
    }
    if (!strcmp(method, "ai_permission_rules")) return ai_list_stored_rules();
    if (!strcmp(method, "ai_permission_rule_add")) {
        const char *tool = pstr(params, "tool", "");
        if (!ai_is_tool(tool)) {
            const char *fmt = tr("未知工具：{0}");
            const char *ph = strstr(fmt, "{0}");
            pymcl_set_error("%.*s%s%s", ph ? (int)(ph - fmt) : (int)strlen(fmt), fmt, ph ? tool : "", ph ? ph + 3 : "");
            return NULL;
        }
        char beh[64] = "allow";
        cJSON *b = cJSON_GetObjectItemCaseSensitive(params, "behavior");
        if (py_truthy(b)) py_str(b, beh, sizeof(beh));
        if (strcmp(beh, "allow") && strcmp(beh, "deny") && strcmp(beh, "ask")) {
            const char *fmt = tr("未知行为：{0}");
            const char *ph = strstr(fmt, "{0}");
            pymcl_set_error("%.*s%s%s", ph ? (int)(ph - fmt) : (int)strlen(fmt), fmt, ph ? beh : "", ph ? ph + 3 : "");
            return NULL;
        }
        char content[1024];
        strip_copy(pstr(params, "content", ""), content, sizeof(content));
        ai_append_rule(tool, content, beh, pstr(params, "instance", ""));
        return ai_list_stored_rules();
    }
    if (!strcmp(method, "ai_permission_rule_remove")) {
        remove_rule(pstr(params, "key", ""), pstr(params, "instance", ""));
        return ai_list_stored_rules();
    }
    if (!strcmp(method, "test_ai_connection")) {
        cJSON *s = cJSON_GetObjectItemCaseSensitive(params, "settings");
        if (s && !cJSON_IsNull(s)) return test_connection(s);
        cJSON *cur = rpc_get_settings();
        cJSON *r = test_connection(cur);
        cJSON_Delete(cur);
        return r;
    }
    (void)emit;
    *handled = 0;
    return NULL;
}

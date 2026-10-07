#include "pymcl.h"
#include <ctype.h>
#include <limits.h>
#include <wincrypt.h>

#pragma comment(lib, "crypt32.lib")

/* login.live.com 老端点。Azure AD v2 只认在 Azure 注册过的 GUID 客户端 ID，
   默认那个官方启动器 ID 送过去会被 AADSTS700016 拒掉。 */
#define MS_DEVICE "https://login.live.com/oauth20_connect.srf"
#define MS_TOKEN "https://login.live.com/oauth20_token.srf"
/* 百分号是成对写的：这个宏只拼进 snprintf 的格式串，单个 %3A 会被当成转换说明 */
#define MS_SCOPE "service%%3A%%3Auser.auth.xboxlive.com%%3A%%3AMBI_SSL"
#define XBL_AUTH "https://user.auth.xboxlive.com/user/authenticate"
#define XSTS_AUTH "https://xsts.auth.xboxlive.com/xsts/authorize"
#define MC_LOGIN "https://api.minecraftservices.com/authentication/login_with_xbox"
#define MC_ENTITLEMENTS "https://api.minecraftservices.com/entitlements/mcstore"
#define MC_PROFILE "https://api.minecraftservices.com/minecraft/profile"

static void accounts_path(char *out, size_t n) {
    pymcl_path_join(out, n, g_root, "accounts.json");
}

/* ---------- 账号令牌密封（逐字段对齐 mclauncher/auth.py） ----------
   Python 的 seal_secret/open_secret 把 access_token / refresh_token 用 Windows
   DPAPI 密封成 "dpapi:<b64>" 落盘（非 Windows 走 "keyring:<name>"）。C 桥读同一份
   accounts.json，此前不认这个前缀，会把密文当合法令牌塞进 --accessToken 交给游戏，
   表现是「登录态无效 / 进不了正版服务器」，很难归因。这里复现 Python 的编码口径：

     · CryptProtectData 的 szDescription / pOptionalEntropy / pvReserved 全传 NULL、
       dwFlags 传 0（auth.py 里就是 CryptProtectData(..., None, None, None, None, 0, ...)）；
     · 密文走标准 base64（字母表与 '=' 填充同 Python base64.b64encode）；
     · 解封后按 UTF-8 严格解码（Python 是 .decode("utf-8")，非法字节抛 ValueError）。

   前缀语义也与 Python 一致：空值原样；已带 dpapi:/keyring:/unavailable: 的值在 seal
   时原样保留（重复密封会变成 Python 解不开的垃圾）；keyring: 与 unavailable: 在 open
   时给空串（C 侧没有系统凭据库可读），但**不能被 C 覆盖**，否则 Python 那边就再也
   取不回令牌了。 */
#define SECRET_DPAPI "dpapi:"
#define SECRET_KEYRING "keyring:"
#define SECRET_UNAVAILABLE "unavailable:"

/* 已经是「落盘形态」的引用：C 侧拿不到明文，也不能当明文用 */
static int secret_is_sealed(const char *v) {
    return v && (pymcl_startswith(v, SECRET_DPAPI) || pymcl_startswith(v, SECRET_KEYRING)
                 || pymcl_startswith(v, SECRET_UNAVAILABLE));
}

/* 这个值能不能直接当令牌用：空的、或还是个密封引用都不行。
   对齐 Python open_secret 返回 "" 之后 `account.get(k) or "0"` 的口径。 */
int account_secret_usable(const char *v) {
    return v && v[0] && !secret_is_sealed(v);
}

static int utf8_is_valid(const char *s, size_t n) {
    if (n == 0) return 1;
    if (n > (size_t)INT_MAX) return 0;
    return MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, (int)n, NULL, 0) > 0;
}

/* 明文 → "dpapi:<b64>" 的 base64 部分；失败返回 NULL */
static char *dpapi_seal_b64(const char *plain, size_t len) {
    DATA_BLOB in, out;
    in.pbData = (BYTE *)plain;
    in.cbData = (DWORD)len;
    out.pbData = NULL;
    out.cbData = 0;
    if (!CryptProtectData(&in, NULL, NULL, NULL, NULL, 0, &out)) return NULL;
    char *b64 = pymcl_b64encode(out.pbData, out.cbData);
    LocalFree(out.pbData);
    return b64;
}

/* "dpapi:" 后面的 base64 → 明文；失败返回 NULL */
static char *dpapi_open_b64(const char *b64) {
    size_t raw_len = 0;
    unsigned char *raw = pymcl_b64decode(b64, &raw_len);
    if (!raw) return NULL;
    DATA_BLOB in, out;
    in.pbData = raw;
    in.cbData = (DWORD)raw_len;
    out.pbData = NULL;
    out.cbData = 0;
    char *plain = NULL;
    if (CryptUnprotectData(&in, NULL, NULL, NULL, NULL, 0, &out)) {
        if (utf8_is_valid((const char *)out.pbData, out.cbData)) {
            plain = (char *)malloc((size_t)out.cbData + 1);
            if (plain) {
                memcpy(plain, out.pbData, out.cbData);
                plain[out.cbData] = 0;
            }
        }
        LocalFree(out.pbData);
    }
    free(raw);
    return plain;
}

/* 明文 → 落盘形态。空值原样；已带前缀原样；DPAPI 不可用时给 "unavailable:" 哨兵
   （绝不退回明文）。返回 malloc 串，调用方 free。 */
char *account_seal_secret(const char *plain) {
    if (!plain || !plain[0]) return pymcl_strdup(plain ? plain : "");
    if (secret_is_sealed(plain)) return pymcl_strdup(plain);
    char *b64 = dpapi_seal_b64(plain, strlen(plain));
    if (!b64) return pymcl_strdup(SECRET_UNAVAILABLE);
    size_t need = strlen(SECRET_DPAPI) + strlen(b64) + 1;
    char *out = (char *)malloc(need);
    if (!out) {
        free(b64);
        return pymcl_strdup(SECRET_UNAVAILABLE);
    }
    snprintf(out, need, "%s%s", SECRET_DPAPI, b64);
    free(b64);
    return out;
}

/* 落盘形态 → 明文。这是 Python open_secret 的对外口径：
   unavailable: / keyring: 返回空串（C 侧读不到系统凭据库），无前缀的历史明文原样返回，
   dpapi: 走 CryptUnprotectData（解不开也给空串，同 Python 的 except 分支）。 */
char *account_open_secret(const char *value) {
    if (!value || !value[0]) return pymcl_strdup(value ? value : "");
    if (pymcl_startswith(value, SECRET_UNAVAILABLE)) return pymcl_strdup("");
    if (pymcl_startswith(value, SECRET_KEYRING)) return pymcl_strdup("");
    if (!pymcl_startswith(value, SECRET_DPAPI)) return pymcl_strdup(value);
    char *plain = dpapi_open_b64(value + strlen(SECRET_DPAPI));
    return plain ? plain : pymcl_strdup("");
}

/* 同 auth.py 的 _TOKEN_KEYS：client_token 不密封 */
static const char *const k_secret_keys[] = {"access_token", "refresh_token"};

/* 读盘时只把 dpapi: 解成明文；keyring: / unavailable: 原样留在树里。

   为什么不一律走 account_open_secret：那两个前缀 C 侧解不开，解成空串后
   accounts_save 会把空串写回磁盘，把 Python 的 keyring 引用整条抹掉——用户下次
   在 Python 侧就读不到自己的令牌了。留在树里则「读 → 改别的键 → 写回」是无损的，
   而「能不能当令牌用」由 account_secret_usable 单独回答。 */
static char *accounts_load_transform(const char *v) {
    if (pymcl_startswith(v, SECRET_DPAPI)) {
        char *plain = dpapi_open_b64(v + strlen(SECRET_DPAPI));
        if (plain) return plain;      /* 解不开就保留密文，等 Python 侧处理 */
    }
    return pymcl_strdup(v);
}

static void accounts_tree_apply(cJSON *root, char *(*fn)(const char *)) {
    cJSON *acc;
    cJSON_ArrayForEach(acc, cJSON_GetObjectItemCaseSensitive(root, "accounts")) {
        for (size_t i = 0; i < sizeof(k_secret_keys) / sizeof(k_secret_keys[0]); i++) {
            cJSON *it = cJSON_GetObjectItemCaseSensitive(acc, k_secret_keys[i]);
            if (!cJSON_IsString(it) || !it->valuestring || !it->valuestring[0]) continue;
            char *v = fn(it->valuestring);
            if (!v) continue;
            cJSON_ReplaceItemInObjectCaseSensitive(acc, k_secret_keys[i], cJSON_CreateString(v));
            free(v);
        }
    }
}

cJSON *accounts_load(void) {
    char p[PYMCL_PATH];
    accounts_path(p, sizeof(p));
    cJSON *j = pymcl_read_json(p);
    if (!j) return cJSON_Parse("{\"accounts\":[],\"active\":null}");
    /* 读进来就把 dpapi: 解开：此后所有调用方（启动参数、令牌刷新、官方账号导入、
       读改写回）看到的都是明文，与 Python AccountManager.load() 的 open_account 一致。 */
    accounts_tree_apply(j, accounts_load_transform);
    return j;
}
void accounts_save(cJSON *root) {
    char p[PYMCL_PATH];
    accounts_path(p, sizeof(p));
    /* 落盘前密封回去，等价 Python AccountManager.save() 的 seal_account。
       明文变 dpapi:，已带前缀的（含 keyring:）原样保留——重复密封会变成
       Python 解不开的垃圾，覆盖 keyring: 引用则会丢令牌。 */
    accounts_tree_apply(root, account_seal_secret);
    pymcl_write_json(p, root);
}

cJSON *account_offline_skin(const char *username, const char *skin) {
    /* 同 Python auth.py offline_account：去空白、缺省 Player，皮肤决定 UUID */
    char n[256];
    snprintf(n, sizeof(n), "%s", username ? username : "");
    char *s = n;
    while (*s && isspace((unsigned char)*s)) s++;
    size_t len = strlen(s);
    while (len && isspace((unsigned char)s[len - 1])) s[--len] = 0;
    if (!s[0]) snprintf(s, sizeof(n), "Player");
    char sk[32];
    snprintf(sk, sizeof(sk), "%s",
             (skin && skin[0]) ? skin : config_str("offline_skin", "default"));
    for (char *q = sk; *q; q++) *q = (char)tolower((unsigned char)*q);
    char uuid[40];
    if (strcmp(sk, "steve") == 0) snprintf(uuid, sizeof(uuid), "8667ba71-b85a-4004-af54-457a9734eed7");
    else if (strcmp(sk, "alex") == 0) snprintf(uuid, sizeof(uuid), "ec561538-f3fd-461d-a7c9-7aa354f5bba9");
    else pymcl_offline_uuid(s, uuid);
    cJSON *o = cJSON_CreateObject();
    cJSON_AddStringToObject(o, "type", "offline");
    cJSON_AddStringToObject(o, "name", s);
    cJSON_AddStringToObject(o, "uuid", uuid);
    cJSON_AddStringToObject(o, "skin", sk);
    return o;
}

cJSON *account_offline(const char *username) {
    return account_offline_skin(username, NULL);
}

/* 启动参数里的令牌：拿不到明文就退回 "0"（Python 是 `account.get("access_token") or "0"`）。
   accounts_load 已经把 dpapi: 解开了；keyring:/unavailable: 会被解成空串，
   这里再兜一层，保证不会把空串或密文塞进 --accessToken。 */
static const char *account_token_or_zero(cJSON *acc) {
    const char *tok = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "access_token"));
    return account_secret_usable(tok) ? tok : "0";
}

cJSON *account_launch_props(cJSON *acc) {
    cJSON *o = cJSON_CreateObject();
    const char *type = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "type"));
    const char *name = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "name")) ?: "Player";
    if (type && strcmp(type, "microsoft") == 0) {
        char uuid[40];
        pymcl_dashed_uuid(cJSON_GetStringValue(cJSON_GetObjectItem(acc, "uuid")) ?: "", uuid);
        cJSON_AddStringToObject(o, "name", name);
        cJSON_AddStringToObject(o, "uuid", uuid);
        cJSON_AddStringToObject(o, "token", account_token_or_zero(acc));
        cJSON_AddStringToObject(o, "user_type", "msa");
        cJSON_AddStringToObject(o, "xuid", cJSON_GetStringValue(cJSON_GetObjectItem(acc, "xuid")) ?: "");
    } else if (type && strcmp(type, "authlib") == 0) {
        char uuid[40];
        pymcl_dashed_uuid(cJSON_GetStringValue(cJSON_GetObjectItem(acc, "uuid")) ?: "", uuid);
        cJSON_AddStringToObject(o, "name", name);
        cJSON_AddStringToObject(o, "uuid", uuid);
        cJSON_AddStringToObject(o, "token", account_token_or_zero(acc));
        cJSON_AddStringToObject(o, "user_type", "mojang");
        cJSON_AddStringToObject(o, "xuid", "");
        cJSON_AddStringToObject(o, "authlib_api", cJSON_GetStringValue(cJSON_GetObjectItem(acc, "api")) ?: "");
    } else if (type && strcmp(type, "nide8") == 0) {
        char uuid[40];
        pymcl_dashed_uuid(cJSON_GetStringValue(cJSON_GetObjectItem(acc, "uuid")) ?: "", uuid);
        cJSON_AddStringToObject(o, "name", name);
        cJSON_AddStringToObject(o, "uuid", uuid);
        cJSON_AddStringToObject(o, "token", account_token_or_zero(acc));
        cJSON_AddStringToObject(o, "user_type", "mojang");
        cJSON_AddStringToObject(o, "xuid", "");
        cJSON_AddStringToObject(o, "nide8_id", cJSON_GetStringValue(cJSON_GetObjectItem(acc, "server_id")) ?: "");
    } else {
        char uuid[40] = "";
        const char *u = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "uuid"));
        if (u && u[0]) pymcl_dashed_uuid(u, uuid);
        if (!uuid[0]) pymcl_offline_uuid(name, uuid);
        cJSON_AddStringToObject(o, "name", name);
        cJSON_AddStringToObject(o, "uuid", uuid);
        cJSON_AddStringToObject(o, "token", "0");
        cJSON_AddStringToObject(o, "user_type", "legacy");
        cJSON_AddStringToObject(o, "xuid", "");
        /* 自定义皮肤要在启动时起一个本地 Yggdrasil 服务（launcher._offline_skin_api，C 端未移植） */
        cJSON_AddStringToObject(o, "skin_file", cJSON_GetStringValue(cJSON_GetObjectItem(acc, "skin_file")) ?: "");
        cJSON_AddStringToObject(o, "skin_model", cJSON_GetStringValue(cJSON_GetObjectItem(acc, "skin_model")) ?: "");
    }
    return o;
}

static int ms_refresh(cJSON *acc) {
    const char *rt = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "refresh_token"));
    /* accounts_load 已解封；keyring:/unavailable: 会解成空串，这里和 Python 一样当缺失处理 */
    if (!account_secret_usable(rt)) { pymcl_set_error("缺少刷新令牌，需要重新登录。"); return -1; }
    const char *cid = config_str("microsoft_client_id", PYMCL_MS_CLIENT_DEFAULT);
    char form[2048];
    snprintf(form, sizeof(form),
        "grant_type=refresh_token&client_id=%s&refresh_token=%s&scope=" MS_SCOPE,
        cid, rt);
    http_resp r;
    if (http_post_form(MS_TOKEN, form, &r, 20) != 0 || r.status != 200) {
        http_resp_free(&r);
        pymcl_set_error("刷新令牌失败，需要重新登录。");
        return -1;
    }
    cJSON *tok = cJSON_Parse(r.body);
    http_resp_free(&r);
    const char *ms = cJSON_GetStringValue(cJSON_GetObjectItem(tok, "access_token"));
    const char *nrt = cJSON_GetStringValue(cJSON_GetObjectItem(tok, "refresh_token"));
    /* XBL：MBI_SSL 令牌直接当票据用，Azure AD 令牌要带 d= 前缀，按顺序试 */
    char body[8192];
    static const char *const rps_prefix[] = {"", "d="};
    http_resp xr;
    cJSON *xj = NULL;
    for (int p = 0; p < 2 && !xj; p++) {
        snprintf(body, sizeof(body),
            "{\"Properties\":{\"AuthMethod\":\"RPS\",\"SiteName\":\"user.auth.xboxlive.com\",\"RpsTicket\":\"%s%s\"},"
            "\"RelyingParty\":\"http://auth.xboxlive.com\",\"TokenType\":\"JWT\"}", rps_prefix[p], ms ? ms : "");
        if (http_post_json(XBL_AUTH, body, &xr, NULL, 20) == 0 && xr.status == 200)
            xj = cJSON_Parse(xr.body);
        http_resp_free(&xr);
    }
    if (!xj) { cJSON_Delete(tok); pymcl_set_error("Xbox Live 认证失败"); return -1; }
    const char *xbl = cJSON_GetStringValue(cJSON_GetObjectItem(xj, "Token"));
    snprintf(body, sizeof(body),
        "{\"Properties\":{\"SandboxId\":\"RETAIL\",\"UserTokens\":[\"%s\"]},"
        "\"RelyingParty\":\"rp://api.minecraftservices.com/\",\"TokenType\":\"JWT\"}", xbl ? xbl : "");
    http_resp sr;
    if (http_post_json(XSTS_AUTH, body, &sr, NULL, 20) != 0) {
        cJSON_Delete(tok); cJSON_Delete(xj); http_resp_free(&sr); return -1;
    }
    cJSON *sj = cJSON_Parse(sr.body); http_resp_free(&sr);
    const char *xsts = cJSON_GetStringValue(cJSON_GetObjectItem(sj, "Token"));
    const char *uhs = NULL;
    cJSON *xui = cJSON_GetObjectItem(cJSON_GetObjectItem(cJSON_GetObjectItem(sj, "DisplayClaims"), "xui"), "0");
    /* DisplayClaims.xui is array */
    cJSON *claims = cJSON_GetObjectItem(sj, "DisplayClaims");
    cJSON *arr = claims ? cJSON_GetObjectItem(claims, "xui") : NULL;
    if (cJSON_IsArray(arr) && cJSON_GetArraySize(arr) > 0)
        uhs = cJSON_GetStringValue(cJSON_GetObjectItem(cJSON_GetArrayItem(arr, 0), "uhs"));
    snprintf(body, sizeof(body), "{\"identityToken\":\"XBL3.0 x=%s;%s\"}", uhs ? uhs : "", xsts ? xsts : "");
    http_resp mr;
    if (http_post_json(MC_LOGIN, body, &mr, NULL, 20) != 0) {
        cJSON_Delete(tok); cJSON_Delete(xj); cJSON_Delete(sj); http_resp_free(&mr); return -1;
    }
    cJSON *mj = cJSON_Parse(mr.body); http_resp_free(&mr);
    const char *mct = cJSON_GetStringValue(cJSON_GetObjectItem(mj, "access_token"));
    char hdr[1024];
    snprintf(hdr, sizeof(hdr), "Authorization: Bearer %s", mct ? mct : "");
    /* 正版资格：只看 items 非空。条目名会随 XGP、捆绑包变，认名字会误伤真买了的人 */
    http_resp er;
    int ent_ok = http_get(MC_ENTITLEMENTS, &er, hdr, 20) == 0 && er.status == 200;
    cJSON *ej = ent_ok ? cJSON_Parse(er.body ? er.body : "{}") : NULL;
    int er_status = er.status;
    http_resp_free(&er);
    cJSON *items = ej ? cJSON_GetObjectItem(ej, "items") : NULL;
    int owned = cJSON_IsArray(items) && cJSON_GetArraySize(items) > 0;
    cJSON_Delete(ej);
    if (!ent_ok || !owned) {
        if (ent_ok)
            pymcl_set_error("该账号尚未购买正版 Minecraft，或 Xbox Game Pass 已到期。");
        else
            pymcl_set_error("检查正版资格失败 (HTTP %d)", er_status);
        cJSON_Delete(tok); cJSON_Delete(xj); cJSON_Delete(sj); cJSON_Delete(mj);
        return -1;
    }
    cJSON *prof = http_get_json_hdr(MC_PROFILE, hdr, 20);
    if (mct) {
        cJSON_DeleteItemFromObject(acc, "access_token");
        cJSON_AddStringToObject(acc, "access_token", mct);
    }
    if (nrt) {
        cJSON_DeleteItemFromObject(acc, "refresh_token");
        cJSON_AddStringToObject(acc, "refresh_token", nrt);
    }
    if (uhs) {
        cJSON_DeleteItemFromObject(acc, "xuid");
        cJSON_AddStringToObject(acc, "xuid", uhs);
    }
    if (prof) {
        const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(prof, "name"));
        const char *id = cJSON_GetStringValue(cJSON_GetObjectItem(prof, "id"));
        if (nm) { cJSON_DeleteItemFromObject(acc, "name"); cJSON_AddStringToObject(acc, "name", nm); }
        if (id) {
            char uuid[40]; pymcl_dashed_uuid(id, uuid);
            cJSON_DeleteItemFromObject(acc, "uuid");
            cJSON_AddStringToObject(acc, "uuid", uuid);
        }
        cJSON_Delete(prof);
    }
    cJSON_DeleteItemFromObject(acc, "expires_at");
    cJSON_AddNumberToObject(acc, "expires_at", (double)time(NULL) + 20 * 3600);
    cJSON_Delete(tok); cJSON_Delete(xj); cJSON_Delete(sj); cJSON_Delete(mj);
    (void)xui;
    return 0;
}

cJSON *account_ensure_valid(cJSON *acc) {
    if (!acc) return NULL;
    const char *type = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "type"));
    if (!type || strcmp(type, "microsoft") != 0) return cJSON_Duplicate(acc, 1);
    double exp = cJSON_GetNumberValue(cJSON_GetObjectItem(acc, "expires_at"));
    const char *tok = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "access_token"));
    if (time(NULL) < exp && account_secret_usable(tok)) return cJSON_Duplicate(acc, 1);
    cJSON *copy = cJSON_Duplicate(acc, 1);
    if (ms_refresh(copy) != 0) { cJSON_Delete(copy); return NULL; }
    cJSON *root = accounts_load();
    cJSON *arr = cJSON_GetObjectItem(root, "accounts");
    const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(copy, "name"));
    if (cJSON_IsArray(arr)) {
        int i = 0;
        cJSON *it;
        cJSON_ArrayForEach(it, arr) {
            if (nm && strcmp(cJSON_GetStringValue(cJSON_GetObjectItem(it, "name")) ?: "", nm) == 0) {
                cJSON_ReplaceItemInArray(arr, i, cJSON_Duplicate(copy, 1));
                break;
            }
            i++;
        }
    }
    accounts_save(root);
    cJSON_Delete(root);
    return copy;
}

int ms_login(pymcl_ctx *ctx, void (*on_code)(void *, const char *, const char *), void *ud, cJSON **out_acc) {
    const char *cid = config_str("microsoft_client_id", PYMCL_MS_CLIENT_DEFAULT);
    char form[512];
    snprintf(form, sizeof(form), "client_id=%s&scope=" MS_SCOPE "&response_type=device_code", cid);
    http_resp r;
    if (http_post_form(MS_DEVICE, form, &r, 15) != 0 || r.status != 200) {
        http_resp_free(&r);
        pymcl_set_error("获取设备码失败");
        return -1;
    }
    cJSON *dc = cJSON_Parse(r.body);
    http_resp_free(&r);
    const char *user = cJSON_GetStringValue(cJSON_GetObjectItem(dc, "user_code"));
    const char *uri = cJSON_GetStringValue(cJSON_GetObjectItem(dc, "verification_uri"));
    const char *dcode = cJSON_GetStringValue(cJSON_GetObjectItem(dc, "device_code"));
    int interval = (int)cJSON_GetNumberValue(cJSON_GetObjectItem(dc, "interval"));
    int expires = (int)cJSON_GetNumberValue(cJSON_GetObjectItem(dc, "expires_in"));
    if (interval <= 0) interval = 5;
    if (on_code) on_code(ud, user ? user : "", uri ? uri : "");
    if (uri) ShellExecuteA(NULL, "open", uri, NULL, NULL, SW_SHOWNORMAL);
    if (ctx && ctx->on_log) {
        char msg[256];
        snprintf(msg, sizeof(msg), "请打开 %s 并输入代码 %s", uri ? uri : "", user ? user : "");
        ctx->on_log(ctx->ud, msg);
    }
    time_t deadline = time(NULL) + (expires > 0 ? expires : 900);
    cJSON *tokens = NULL;
    while (time(NULL) < deadline) {
        if (ctx && ctx->cancel && ctx->cancel(ctx->ud)) { cJSON_Delete(dc); pymcl_set_error("用户取消"); return -1; }
        Sleep((DWORD)interval * 1000);
        char pf[1024];
        snprintf(pf, sizeof(pf),
            "grant_type=urn:ietf:params:oauth:grant-type:device_code&client_id=%s&device_code=%s",
            cid, dcode ? dcode : "");
        http_resp tr;
        http_post_form(MS_TOKEN, pf, &tr, 15);
        cJSON *tj = tr.body ? cJSON_Parse(tr.body) : NULL;
        if (tr.status == 200 && tj) {
            tokens = tj;
            http_resp_free(&tr);
            break;
        }
        const char *err = tj ? cJSON_GetStringValue(cJSON_GetObjectItem(tj, "error")) : "";
        if (err && (strcmp(err, "expired_token") == 0 || strcmp(err, "authorization_declined") == 0)) {
            cJSON_Delete(tj); http_resp_free(&tr); cJSON_Delete(dc);
            pymcl_set_error("授权已过期或被拒绝，请重试。");
            return -1;
        }
        if (err && strcmp(err, "slow_down") == 0) interval += 5;
        if (ctx && ctx->on_log) ctx->on_log(ctx->ud, "等待授权中…");
        cJSON_Delete(tj);
        http_resp_free(&tr);
    }
    cJSON_Delete(dc);
    if (!tokens) { pymcl_set_error("授权超时。"); return -1; }
    /* reuse refresh path by stuffing tokens into a temp account */
    cJSON *acc = cJSON_CreateObject();
    cJSON_AddStringToObject(acc, "type", "microsoft");
    cJSON_AddStringToObject(acc, "refresh_token",
        cJSON_GetStringValue(cJSON_GetObjectItem(tokens, "refresh_token")) ?: "");
    cJSON_AddStringToObject(acc, "access_token",
        cJSON_GetStringValue(cJSON_GetObjectItem(tokens, "access_token")) ?: "");
    cJSON_Delete(tokens);
    if (ms_refresh(acc) != 0) { cJSON_Delete(acc); return -1; }
    cJSON *root = accounts_load();
    cJSON *arr = cJSON_GetObjectItem(root, "accounts");
    if (!cJSON_IsArray(arr)) {
        arr = cJSON_CreateArray();
        cJSON_AddItemToObject(root, "accounts", arr);
    }
    const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(acc, "name"));
    int i = 0, replaced = 0;
    cJSON *it;
    cJSON_ArrayForEach(it, arr) {
        if (nm && strcmp(cJSON_GetStringValue(cJSON_GetObjectItem(it, "name")) ?: "", nm) == 0) {
            cJSON_ReplaceItemInArray(arr, i, cJSON_Duplicate(acc, 1));
            replaced = 1;
            break;
        }
        i++;
    }
    if (!replaced) cJSON_AddItemToArray(arr, cJSON_Duplicate(acc, 1));
    cJSON_DeleteItemFromObject(root, "active");
    cJSON_AddStringToObject(root, "active", nm ? nm : "");
    accounts_save(root);
    cJSON_Delete(root);
    *out_acc = acc;
    return 0;
}

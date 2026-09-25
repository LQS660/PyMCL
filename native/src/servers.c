#include "pymcl.h"
#include <ctype.h>
#include <zlib.h>

/* mclauncher/servers.py + terracotta.py 里 servers.dat 的读写。
   以 servers.dat 为准，servers.json 只存图标、简介等游戏不认的字段。
   注意：Python 参考实现把 servers.dat 按 gzip 读写（原版游戏读的是未压缩 NBT），
   这里照搬以保持两边一致，问题记在去 Python 化进度报告里。 */

static const char *pstr(cJSON *o, const char *k, const char *def) {
    const char *s = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(o, k));
    return s ? s : def;
}

/* ---------- NBT ---------- */

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
    if (!s) { r->bad = 1; return pymcl_strdup(""); }
    memcpy(s, r->p + r->pos, n);
    s[n] = 0;
    r->pos += n;
    return s;
}
static void rd_skip(rd_t *r, size_t n) {
    if (r->pos + n > r->len) { r->bad = 1; return; }
    r->pos += n;
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
        int32_t n = (int32_t)rd_be(r, 4);
        for (int32_t i = 0; i < n && !r->bad; i++) skip_nbt(r, child, depth + 1);
        return;
    }
    case 10:
        for (;;) {
            int child = rd_u8(r);
            if (r->bad || child == 0) return;
            free(rd_str(r));
            skip_nbt(r, child, depth + 1);
        }
    case 11: { int32_t n = (int32_t)rd_be(r, 4); if (n > 0) rd_skip(r, (size_t)n * 4); return; }
    case 12: { int32_t n = (int32_t)rd_be(r, 4); if (n > 0) rd_skip(r, (size_t)n * 8); return; }
    default: r->bad = 1;
    }
}

static cJSON *read_compound_body(rd_t *r, int depth) {
    cJSON *data = cJSON_CreateObject();
    while (!r->bad && depth < 64) {
        int tag = rd_u8(r);
        if (r->bad || tag == 0) break;
        char *name = rd_str(r);
        if (tag == 1) {
            int v = rd_u8(r);
            cJSON_DeleteItemFromObjectCaseSensitive(data, name);
            cJSON_AddNumberToObject(data, name, v);
        } else if (tag == 8) {
            char *s = rd_str(r);
            cJSON_DeleteItemFromObjectCaseSensitive(data, name);
            cJSON_AddStringToObject(data, name, s);
            free(s);
        } else if (tag == 9) {
            int child = rd_u8(r);
            int32_t n = (int32_t)rd_be(r, 4);
            cJSON *items = cJSON_CreateArray();
            for (int32_t i = 0; i < n && !r->bad; i++) {
                if (child == 10) cJSON_AddItemToArray(items, read_compound_body(r, depth + 1));
                else skip_nbt(r, child, depth + 1);
            }
            cJSON_DeleteItemFromObjectCaseSensitive(data, name);
            cJSON_AddItemToObject(data, name, items);
        } else {
            skip_nbt(r, tag, depth + 1);
        }
        free(name);
    }
    return data;
}

static unsigned char *gunzip(const unsigned char *in, size_t inlen, size_t *outlen) {
    z_stream s;
    memset(&s, 0, sizeof(s));
    if (inflateInit2(&s, 16 + MAX_WBITS) != Z_OK) return NULL;
    size_t cap = inlen * 4 + 1024, len = 0;
    unsigned char *out = (unsigned char *)malloc(cap);
    if (!out) { inflateEnd(&s); return NULL; }
    s.next_in = (Bytef *)in;
    s.avail_in = (uInt)inlen;
    int rc;
    do {
        if (len == cap) {
            cap *= 2;
            unsigned char *nb = (unsigned char *)realloc(out, cap);
            if (!nb) { free(out); inflateEnd(&s); return NULL; }
            out = nb;
        }
        s.next_out = out + len;
        s.avail_out = (uInt)(cap - len);
        rc = inflate(&s, Z_NO_FLUSH);
        len = cap - s.avail_out;
    } while (rc == Z_OK);
    inflateEnd(&s);
    if (rc != Z_STREAM_END) { free(out); return NULL; }
    *outlen = len;
    return out;
}

static cJSON *dat_read(const char *path) {
    cJSON *rows = cJSON_CreateArray();
    char *raw = NULL;
    size_t rl = 0;
    if (!pymcl_file_exists(path) || pymcl_read_file(path, &raw, &rl) != 0) return rows;
    size_t n = 0;
    unsigned char *buf = gunzip((unsigned char *)raw, rl, &n);
    free(raw);
    if (!buf) return rows;
    rd_t r = {buf, n, 0, 0};
    if (rd_u8(&r) == 10) {
        free(rd_str(&r));
        cJSON *root = read_compound_body(&r, 0);
        if (!r.bad) {
            cJSON *list = cJSON_GetObjectItemCaseSensitive(root, "servers");
            cJSON *it;
            cJSON_ArrayForEach(it, list) if (cJSON_IsObject(it)) cJSON_AddItemToArray(rows, cJSON_Duplicate(it, 1));
        }
        cJSON_Delete(root);
    }
    free(buf);
    return rows;
}

typedef struct { unsigned char *p; size_t len, cap; } wb_t;
static void wb_put(wb_t *b, const void *d, size_t n) {
    if (b->len + n > b->cap) {
        size_t cap = b->cap ? b->cap * 2 : 256;
        while (b->len + n > cap) cap *= 2;
        unsigned char *np = (unsigned char *)realloc(b->p, cap);
        if (!np) return;
        b->p = np;
        b->cap = cap;
    }
    memcpy(b->p + b->len, d, n);
    b->len += n;
}
static void wb_u8(wb_t *b, int v) { unsigned char c = (unsigned char)v; wb_put(b, &c, 1); }
static void wb_str(wb_t *b, const char *s) {
    size_t n = strlen(s ? s : "");
    unsigned char h[2] = {(unsigned char)(n >> 8), (unsigned char)n};
    wb_put(b, h, 2);
    wb_put(b, s ? s : "", n);
}

static int dat_write(const char *path, cJSON *rows) {
    wb_t b = {0};
    wb_u8(&b, 10); wb_str(&b, "");
    wb_u8(&b, 9); wb_str(&b, "servers");
    wb_u8(&b, 10);
    uint32_t n = (uint32_t)cJSON_GetArraySize(rows);
    unsigned char cnt[4] = {(unsigned char)(n >> 24), (unsigned char)(n >> 16), (unsigned char)(n >> 8), (unsigned char)n};
    wb_put(&b, cnt, 4);
    cJSON *it;
    cJSON_ArrayForEach(it, rows) {
        char name[1024], ip[1024];
        cJSON *nm = cJSON_GetObjectItem(it, "name"), *ipv = cJSON_GetObjectItem(it, "ip");
        if (py_truthy(nm)) py_str(nm, name, sizeof(name)); else snprintf(name, sizeof(name), "%s", "陶瓦联机大厅");
        if (py_truthy(ipv)) py_str(ipv, ip, sizeof(ip)); else ip[0] = 0;
        wb_u8(&b, 8); wb_str(&b, "name"); wb_str(&b, name);
        wb_u8(&b, 8); wb_str(&b, "ip"); wb_str(&b, ip);
        wb_u8(&b, 1); wb_str(&b, "hidden"); wb_u8(&b, py_truthy(cJSON_GetObjectItem(it, "hidden")) ? 1 : 0);
        wb_u8(&b, 0);
    }
    wb_u8(&b, 0);
    /* gzip.compress 默认 compresslevel=9 */
    z_stream s;
    memset(&s, 0, sizeof(s));
    if (deflateInit2(&s, 9, Z_DEFLATED, 16 + MAX_WBITS, 8, Z_DEFAULT_STRATEGY) != Z_OK) { free(b.p); return -1; }
    size_t cap = deflateBound(&s, (uLong)b.len) + 64;
    unsigned char *out = (unsigned char *)malloc(cap);
    if (!out) { deflateEnd(&s); free(b.p); return -1; }
    s.next_in = b.p;
    s.avail_in = (uInt)b.len;
    s.next_out = out;
    s.avail_out = (uInt)cap;
    deflate(&s, Z_FINISH);
    size_t outlen = cap - s.avail_out;
    deflateEnd(&s);
    free(b.p);
    char parent[PYMCL_PATH];
    pymcl_parent(path, parent, sizeof(parent));
    pymcl_ensure_dir(parent);
    int r = pymcl_write_file(path, out, outlen);
    free(out);
    return r;
}

/* ---------- servers.py ---------- */

static void strip_copy(const char *s, char *out, size_t n) {
    while (s && *s && isspace((unsigned char)*s)) s++;
    snprintf(out, n, "%s", s ? s : "");
    size_t len = strlen(out);
    while (len && isspace((unsigned char)out[len - 1])) out[--len] = 0;
}

static int all_digits(const char *s) {
    if (!*s) return 0;
    for (; *s; s++) if (!isdigit((unsigned char)*s)) return 0;
    return 1;
}

/* _split_addr(ip, port)：显式端口合法就用它，否则尝试从 host:port 里拆 */
static void split_addr(cJSON *ipv, cJSON *portv, char *host, size_t hn, long long *port) {
    char text[1024] = "";
    if (py_truthy(ipv)) py_str(ipv, text, sizeof(text));
    strip_copy(text, host, hn);
    if (portv && !cJSON_IsNull(portv) && !(cJSON_IsString(portv) && !portv->valuestring[0])) {
        long long p;
        if (py_int(portv, &p) && p >= 1 && p <= 65535) { *port = p; return; }
    }
    char *colon = strrchr(host, ':');
    if (colon && all_digits(colon + 1)) {
        long long p = atoll(colon + 1);
        if (p >= 1 && p <= 65535) { *colon = 0; *port = p; return; }
    }
    *port = 25565;
}

static void inst_file(const char *inst, const char *name, char *out, size_t n) {
    char ip[PYMCL_PATH];
    instance_path(inst, ip, sizeof(ip));
    pymcl_path_join(out, n, ip, name);
}

static cJSON *read_servers(const char *inst) {
    char dat[PYMCL_PATH], js[PYMCL_PATH];
    inst_file(inst, "servers.dat", dat, sizeof(dat));
    inst_file(inst, "servers.json", js, sizeof(js));
    cJSON *dat_rows = dat_read(dat);
    cJSON *json_rows = pymcl_read_json(js);
    if (!cJSON_IsArray(json_rows)) { cJSON_Delete(json_rows); json_rows = cJSON_CreateArray(); }
    cJSON *out = cJSON_CreateArray();
    cJSON *it;
    if (cJSON_GetArraySize(dat_rows) > 0) {
        cJSON_ArrayForEach(it, dat_rows) {
            char host[1024];
            long long port;
            split_addr(cJSON_GetObjectItem(it, "ip"), NULL, host, sizeof(host), &port);
            cJSON *extra = NULL, *j;
            cJSON_ArrayForEach(j, json_rows) {
                if (!cJSON_IsObject(j)) continue;
                char h2[1024];
                long long p2;
                split_addr(cJSON_GetObjectItem(j, "ip"), cJSON_GetObjectItem(j, "port"), h2, sizeof(h2), &p2);
                if (!strcmp(h2, host) && p2 == port) extra = j;
            }
            cJSON *row = cJSON_CreateObject();
            cJSON *nm = cJSON_GetObjectItem(it, "name");
            cJSON *en = extra ? cJSON_GetObjectItem(extra, "name") : NULL;
            cJSON_AddItemToObject(row, "name", py_truthy(nm) ? cJSON_Duplicate(nm, 1) : py_truthy(en) ? cJSON_Duplicate(en, 1) : cJSON_CreateString(host));
            cJSON_AddStringToObject(row, "ip", host);
            cJSON_AddNumberToObject(row, "port", (double)port);
            cJSON *ic = extra ? cJSON_GetObjectItem(extra, "icon") : NULL;
            cJSON *ds = extra ? cJSON_GetObjectItem(extra, "description") : NULL;
            cJSON_AddItemToObject(row, "icon", py_truthy(ic) ? cJSON_Duplicate(ic, 1) : cJSON_CreateString(""));
            cJSON_AddItemToObject(row, "description", py_truthy(ds) ? cJSON_Duplicate(ds, 1) : cJSON_CreateString(""));
            cJSON_AddBoolToObject(row, "hidden", py_truthy(cJSON_GetObjectItem(it, "hidden")));
            cJSON_AddItemToArray(out, row);
        }
    } else {
        cJSON_ArrayForEach(it, json_rows) if (cJSON_IsObject(it)) cJSON_AddItemToArray(out, cJSON_Duplicate(it, 1));
    }
    cJSON_Delete(dat_rows);
    cJSON_Delete(json_rows);
    return out;
}

static int write_servers(const char *inst, cJSON *servers) {
    char ip[PYMCL_PATH], js[PYMCL_PATH], dat[PYMCL_PATH];
    instance_path(inst, ip, sizeof(ip));
    pymcl_ensure_dir(ip);
    pymcl_path_join(js, sizeof(js), ip, "servers.json");
    pymcl_path_join(dat, sizeof(dat), ip, "servers.dat");
    if (pymcl_write_json(js, servers) != 0) return -1;
    cJSON *rows = cJSON_CreateArray();
    cJSON *it;
    cJSON_ArrayForEach(it, servers) {
        if (!cJSON_IsObject(it)) continue;
        char host[1024];
        long long port;
        split_addr(cJSON_GetObjectItem(it, "ip"), cJSON_GetObjectItem(it, "port"), host, sizeof(host), &port);
        if (!host[0]) continue;
        cJSON *r = cJSON_CreateObject();
        cJSON *nm = cJSON_GetObjectItem(it, "name");
        cJSON_AddItemToObject(r, "name", py_truthy(nm) ? cJSON_Duplicate(nm, 1) : cJSON_CreateString(host));
        char addr[1100];
        if (port == 25565) snprintf(addr, sizeof(addr), "%s", host);
        else snprintf(addr, sizeof(addr), "%s:%lld", host, port);
        cJSON_AddStringToObject(r, "ip", addr);
        cJSON_AddNumberToObject(r, "hidden", py_truthy(cJSON_GetObjectItem(it, "hidden")) ? 1 : 0);
        cJSON_AddItemToArray(rows, r);
    }
    int rc = dat_write(dat, rows);
    cJSON_Delete(rows);
    return rc;
}

static cJSON *normalize(cJSON *s, int index) {
    char host[1024], buf[1024];
    long long port;
    split_addr(cJSON_GetObjectItem(s, "ip"), cJSON_GetObjectItem(s, "port"), host, sizeof(host), &port);
    cJSON *o = cJSON_CreateObject();
    cJSON *nm = cJSON_GetObjectItem(s, "name");
    if (py_truthy(nm)) py_str(nm, buf, sizeof(buf));
    else if (host[0]) snprintf(buf, sizeof(buf), "%s", host);
    else snprintf(buf, sizeof(buf), "服务器 #%d", index + 1);
    cJSON_AddStringToObject(o, "name", buf);
    cJSON_AddStringToObject(o, "ip", host);
    cJSON_AddNumberToObject(o, "port", (double)port);
    cJSON *ic = cJSON_GetObjectItem(s, "icon"), *ds = cJSON_GetObjectItem(s, "description");
    if (ic) py_str(ic, buf, sizeof(buf)); else buf[0] = 0;
    cJSON_AddStringToObject(o, "icon", buf);
    if (ds) py_str(ds, buf, sizeof(buf)); else buf[0] = 0;
    cJSON_AddStringToObject(o, "description", buf);
    cJSON_AddBoolToObject(o, "hidden", py_truthy(cJSON_GetObjectItem(s, "hidden")));
    cJSON_AddNumberToObject(o, "index", index);
    return o;
}

static cJSON *list_servers(const char *inst) {
    cJSON *data = read_servers(inst);
    cJSON *out = cJSON_CreateArray();
    int i = 0;
    cJSON *it;
    cJSON_ArrayForEach(it, data) {
        if (cJSON_IsObject(it)) cJSON_AddItemToArray(out, normalize(it, i));
        i++;
    }
    cJSON_Delete(data);
    return out;
}

static int port_param(cJSON *v, long long *port) {
    if (!py_truthy(v)) { *port = 25565; return 1; }
    return py_int(v, port);
}

cJSON *rpc_servers_call(const char *method, cJSON *params, sse_emit_fn emit, int *handled) {
    *handled = 1;
    const char *inst = pstr(params, "instance", "");
    if (strcmp(method, "list_servers") == 0 || strcmp(method, "add_server") == 0 ||
        strcmp(method, "update_server") == 0 || strcmp(method, "delete_server") == 0 ||
        strcmp(method, "import_servers") == 0 || strcmp(method, "export_servers") == 0) {
        char ip[PYMCL_PATH];
        if (instance_open(inst, ip, sizeof(ip)) != 0) return NULL;
    }
    if (strcmp(method, "list_servers") == 0) return list_servers(inst);

    if (strcmp(method, "add_server") == 0) {
        const char *ipraw = pstr(params, "ip", "");
        char ipv[1024], name[1024], desc[1024];
        strip_copy(ipraw, ipv, sizeof(ipv));
        if (!ipv[0]) { pymcl_set_error("服务器地址不能为空"); return NULL; }
        long long port;
        if (!port_param(cJSON_GetObjectItem(params, "port"), &port)) { pymcl_set_error("端口号必须在 1-65535 之间"); return NULL; }
        if (port < 1 || port > 65535) { pymcl_set_error("端口号必须在 1-65535 之间"); return NULL; }
        const char *nm = pstr(params, "name", "");
        strip_copy(nm[0] ? nm : ipraw, name, sizeof(name));
        strip_copy(pstr(params, "description", ""), desc, sizeof(desc));
        cJSON *servers = read_servers(inst);
        cJSON *e = cJSON_CreateObject();
        cJSON_AddStringToObject(e, "name", name);
        cJSON_AddStringToObject(e, "ip", ipv);
        cJSON_AddNumberToObject(e, "port", (double)port);
        cJSON_AddStringToObject(e, "icon", "");
        cJSON_AddStringToObject(e, "description", desc);
        cJSON_AddItemToArray(servers, cJSON_Duplicate(e, 1));
        int idx = cJSON_GetArraySize(servers) - 1;
        int rc = write_servers(inst, servers);
        cJSON_Delete(servers);
        cJSON *out = rc == 0 ? normalize(e, idx) : NULL;
        cJSON_Delete(e);
        if (out && emit) emit("ui_changed", cJSON_CreateObject());
        return out;
    }

    if (strcmp(method, "update_server") == 0 || strcmp(method, "delete_server") == 0) {
        long long index = py_int_or(cJSON_GetObjectItem(params, "index"), -1);
        cJSON *servers = read_servers(inst);
        int n = cJSON_GetArraySize(servers);
        if (index < 0 || index >= n) {
            cJSON_Delete(servers);
            pymcl_set_error("服务器索引 %lld 不存在", index);
            return NULL;
        }
        if (strcmp(method, "delete_server") == 0) {
            cJSON_DeleteItemFromArray(servers, (int)index);
            int rc = write_servers(inst, servers);
            cJSON_Delete(servers);
            if (rc != 0) return NULL;
            if (emit) emit("ui_changed", cJSON_CreateObject());
            return cJSON_CreateNull();
        }
        cJSON *entry = cJSON_GetArrayItem(servers, (int)index);
        if (!cJSON_IsObject(entry)) { cJSON_Delete(servers); pymcl_set_error("服务器数据损坏: %lld", index); return NULL; }
        char buf[1024];
        cJSON *v;
        if ((v = cJSON_GetObjectItem(params, "name")) != NULL) {
            char t[1024]; py_str(v, t, sizeof(t)); strip_copy(t, buf, sizeof(buf));
            cJSON_DeleteItemFromObject(entry, "name"); cJSON_AddStringToObject(entry, "name", buf);
        }
        if ((v = cJSON_GetObjectItem(params, "ip")) != NULL) {
            char t[1024]; py_str(v, t, sizeof(t)); strip_copy(t, buf, sizeof(buf));
            if (!buf[0]) { cJSON_Delete(servers); pymcl_set_error("服务器地址不能为空"); return NULL; }
            cJSON_DeleteItemFromObject(entry, "ip"); cJSON_AddStringToObject(entry, "ip", buf);
        }
        if ((v = cJSON_GetObjectItem(params, "port")) != NULL) {
            long long port;
            if (!py_int(v, &port) || port < 1 || port > 65535) { cJSON_Delete(servers); pymcl_set_error("端口号必须在 1-65535 之间"); return NULL; }
            cJSON_DeleteItemFromObject(entry, "port"); cJSON_AddNumberToObject(entry, "port", (double)port);
        }
        if ((v = cJSON_GetObjectItem(params, "description")) != NULL) {
            char t[1024]; py_str(v, t, sizeof(t)); strip_copy(t, buf, sizeof(buf));
            cJSON_DeleteItemFromObject(entry, "description"); cJSON_AddStringToObject(entry, "description", buf);
        }
        if ((v = cJSON_GetObjectItem(params, "icon")) != NULL) {
            py_str(v, buf, sizeof(buf));
            cJSON_DeleteItemFromObject(entry, "icon"); cJSON_AddStringToObject(entry, "icon", buf);
        }
        if ((v = cJSON_GetObjectItem(params, "hidden")) != NULL) {
            cJSON_DeleteItemFromObject(entry, "hidden"); cJSON_AddBoolToObject(entry, "hidden", py_truthy(v));
        }
        int rc = write_servers(inst, servers);
        cJSON *out = rc == 0 ? normalize(entry, (int)index) : NULL;
        cJSON_Delete(servers);
        return out;
    }

    if (strcmp(method, "import_servers") == 0) {
        const char *text = pstr(params, "text", "");
        cJSON *servers = read_servers(inst);
        cJSON *existing = cJSON_CreateObject();
        cJSON *it;
        cJSON_ArrayForEach(it, servers) {
            if (!cJSON_IsObject(it)) continue;
            char ipbuf[1024] = "", pbuf[32] = "25565", addr[1100];
            cJSON *a = cJSON_GetObjectItem(it, "ip"), *p = cJSON_GetObjectItem(it, "port");
            if (a) py_str(a, ipbuf, sizeof(ipbuf));
            if (p) py_str(p, pbuf, sizeof(pbuf));
            snprintf(addr, sizeof(addr), "%s:%s", ipbuf, pbuf);
            if (!cJSON_GetObjectItemCaseSensitive(existing, addr)) cJSON_AddTrueToObject(existing, addr);
        }
        int imported = 0;
        char *copy = pymcl_strdup(text);
        for (char *line = copy; line && *line;) {
            char *nl = line + strcspn(line, "\r\n\v\f");
            char save = *nl;
            *nl = 0;
            char l[2048];
            strip_copy(line, l, sizeof(l));
            if (l[0] && l[0] != '#') {
                char name[1024] = "", addr_part[1024];
                char *tab = strchr(l, '\t');
                if (tab) {
                    *tab = 0;
                    strip_copy(l, name, sizeof(name));
                    strip_copy(tab + 1, addr_part, sizeof(addr_part));
                } else {
                    snprintf(addr_part, sizeof(addr_part), "%s", l);
                }
                char host[1024];
                long long port = 25565;
                char *colon = strrchr(addr_part, ':');
                if (colon) {
                    char ps[64];
                    strip_copy(colon + 1, ps, sizeof(ps));
                    char *end = NULL;
                    long long p = strtoll(ps, &end, 10);
                    port = (ps[0] && end && !*end) ? p : 25565;
                    *colon = 0;
                    strip_copy(addr_part, host, sizeof(host));
                } else {
                    snprintf(host, sizeof(host), "%s", addr_part);
                }
                if (host[0]) {
                    char addr[1100];
                    snprintf(addr, sizeof(addr), "%s:%lld", host, port);
                    if (!cJSON_GetObjectItemCaseSensitive(existing, addr)) {
                        cJSON *e = cJSON_CreateObject();
                        cJSON_AddStringToObject(e, "name", name[0] ? name : host);
                        cJSON_AddStringToObject(e, "ip", host);
                        cJSON_AddNumberToObject(e, "port", (double)port);
                        cJSON_AddItemToArray(servers, e);
                        cJSON_AddTrueToObject(existing, addr);
                        imported++;
                    }
                }
            }
            if (!save) break;
            line = nl + 1;
            if (save == '\r' && *line == '\n') line++;
        }
        free(copy);
        cJSON_Delete(existing);
        int rc = imported > 0 ? write_servers(inst, servers) : 0;
        cJSON_Delete(servers);
        if (rc != 0) return NULL;
        return cJSON_CreateNumber(imported);
    }

    if (strcmp(method, "export_servers") == 0) {
        cJSON *servers = list_servers(inst);
        size_t cap = 256 + (size_t)cJSON_GetArraySize(servers) * 2200;
        char *out = (char *)malloc(cap);
        if (!out) { cJSON_Delete(servers); return NULL; }
        snprintf(out, cap, "# PyMCL 服务器列表导出\n# 共 %d 个服务器\n", cJSON_GetArraySize(servers));
        cJSON *s;
        cJSON_ArrayForEach(s, servers) {
            const char *nm = cJSON_GetStringValue(cJSON_GetObjectItem(s, "name"));
            const char *ipv = cJSON_GetStringValue(cJSON_GetObjectItem(s, "ip"));
            int port = (int)cJSON_GetNumberValue(cJSON_GetObjectItem(s, "port"));
            char line[2200];
            if (nm && nm[0] && strcmp(nm, ipv) != 0) snprintf(line, sizeof(line), "\n%s\t%s:%d", nm, ipv, port);
            else snprintf(line, sizeof(line), "\n%s:%d", ipv, port);
            strncat(out, line, cap - strlen(out) - 1);
        }
        cJSON_Delete(servers);
        cJSON *r = cJSON_CreateString(out);
        free(out);
        return r;
    }

    return rpc_versions_call(method, params, emit, handled);
}

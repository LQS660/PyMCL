#include "pymcl.h"
#include <zlib.h>

static FILE *fopen_rb(const char *p) {
    wchar_t *w = pymcl_u8_to_wide(p);
    FILE *f = w ? _wfopen(w, L"rb") : NULL;
    free(w);
    return f;
}
static uint32_t ru32(const unsigned char *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint16_t ru16(const unsigned char *p) {
    return (uint16_t)(p[0] | (p[1] << 8));
}
static int name_eq(const char *a, const char *b) {
    if (!a || !b) return 0;
    while (*a == '/' || *a == '\\') a++;
    while (*b == '/' || *b == '\\') b++;
    return pymcl_ieq(a, b);
}
static int inflate_raw(const unsigned char *in, size_t inlen, unsigned char *out, size_t outlen) {
    z_stream s;
    memset(&s, 0, sizeof(s));
    if (inflateInit2(&s, -MAX_WBITS) != Z_OK) return -1;
    s.next_in = (Bytef *)in;
    s.avail_in = (uInt)inlen;
    s.next_out = out;
    s.avail_out = (uInt)outlen;
    int r = inflate(&s, Z_FINISH);
    inflateEnd(&s);
    return r == Z_STREAM_END ? 0 : -1;
}

typedef struct {
    char name[PYMCL_PATH];
    uint16_t method;
    uint32_t crc, comp, uncomp, local_off;
    int is_dir;
} zip_ent;

static int find_eocd(FILE *f, uint32_t *cd_off, uint32_t *cd_size, uint16_t *nrec) {
    if (fseek(f, 0, SEEK_END) != 0) return -1;
    long sz = ftell(f);
    if (sz < 22) return -1;
    long maxscan = sz < 65557 ? sz : 65557;
    unsigned char *buf = (unsigned char *)malloc((size_t)maxscan);
    if (!buf) return -1;
    if (fseek(f, sz - maxscan, SEEK_SET) != 0) { free(buf); return -1; }
    size_t n = fread(buf, 1, (size_t)maxscan, f);
    int found = 0;
    for (long i = (long)n - 22; i >= 0; i--) {
        if (ru32(buf + i) == 0x06054b50u) {
            *nrec = ru16(buf + i + 10);
            *cd_size = ru32(buf + i + 12);
            *cd_off = ru32(buf + i + 16);
            found = 1;
            break;
        }
    }
    free(buf);
    return found ? 0 : -1;
}

static int read_central(FILE *f, zip_ent **out, int *nout) {
    uint32_t cd_off = 0, cd_size = 0;
    uint16_t nrec = 0;
    if (find_eocd(f, &cd_off, &cd_size, &nrec) != 0) return -1;
    if (fseek(f, (long)cd_off, SEEK_SET) != 0) return -1;
    unsigned char *cd = (unsigned char *)malloc(cd_size ? cd_size : 1);
    if (!cd) return -1;
    if (fread(cd, 1, cd_size, f) != cd_size) { free(cd); return -1; }
    zip_ent *ents = (zip_ent *)calloc(nrec ? nrec : 1, sizeof(zip_ent));
    int n = 0;
    size_t off = 0;
    while (off + 46 <= cd_size && n < nrec) {
        if (ru32(cd + off) != 0x02014b50u) break;
        uint16_t nl = ru16(cd + off + 28);
        uint16_t el = ru16(cd + off + 30);
        uint16_t cl = ru16(cd + off + 32);
        zip_ent *e = &ents[n];
        e->method = ru16(cd + off + 10);
        e->crc = ru32(cd + off + 16);
        e->comp = ru32(cd + off + 20);
        e->uncomp = ru32(cd + off + 24);
        e->local_off = ru32(cd + off + 42);
        size_t nn = nl < PYMCL_PATH - 1 ? nl : PYMCL_PATH - 1;
        memcpy(e->name, cd + off + 46, nn);
        e->name[nn] = 0;
        pymcl_replace_char(e->name, '\\', '/');
        size_t ln = strlen(e->name);
        e->is_dir = ln && e->name[ln - 1] == '/';
        off += 46u + nl + el + cl;
        n++;
    }
    free(cd);
    *out = ents;
    *nout = n;
    return 0;
}

static int extract_ent(FILE *f, const zip_ent *e, unsigned char **out, size_t *len) {
    if (e->is_dir) { *out = NULL; *len = 0; return 0; }
    if (fseek(f, (long)e->local_off, SEEK_SET) != 0) return -1;
    unsigned char lh[30];
    if (fread(lh, 1, 30, f) != 30 || ru32(lh) != 0x04034b50u) return -1;
    uint16_t nl = ru16(lh + 26), el = ru16(lh + 28);
    if (fseek(f, nl + el, SEEK_CUR) != 0) return -1;
    unsigned char *comp = NULL;
    if (e->comp) {
        comp = (unsigned char *)malloc(e->comp);
        if (!comp || fread(comp, 1, e->comp, f) != e->comp) { free(comp); return -1; }
    }
    unsigned char *raw = (unsigned char *)malloc(e->uncomp + 1);
    if (!raw) { free(comp); return -1; }
    raw[e->uncomp] = 0;
    int ok = -1;
    if (e->method == 0) {
        if (e->comp == e->uncomp) {
            memcpy(raw, comp ? comp : (const unsigned char *)"", e->uncomp);
            ok = 0;
        }
    } else if (e->method == 8) {
        ok = inflate_raw(comp, e->comp, raw, e->uncomp);
    }
    free(comp);
    if (ok != 0) { free(raw); return -1; }
    *out = raw;
    *len = e->uncomp;
    return 0;
}

static const zip_ent *find_ent(zip_ent *ents, int n, const char *inner) {
    for (int i = 0; i < n; i++)
        if (name_eq(ents[i].name, inner)) return &ents[i];
    return NULL;
}

int pymcl_extract_zip(const char *zip_path, const char *dest) {
    pymcl_ensure_dir(dest);
    FILE *f = fopen_rb(zip_path);
    if (!f) { pymcl_set_error("无法打开压缩包 %s", zip_path); return -1; }
    zip_ent *ents = NULL; int n = 0;
    if (read_central(f, &ents, &n) != 0) {
        fclose(f);
        pymcl_set_error("无法读取压缩包 %s", zip_path);
        return -1;
    }
    int rc = 0;
    for (int i = 0; i < n; i++) {
        if (strstr(ents[i].name, "..")) continue;
        char name[PYMCL_PATH];
        snprintf(name, sizeof(name), "%s", ents[i].name);
        pymcl_replace_char(name, '/', '\\');
        char outp[PYMCL_PATH];
        pymcl_path_join(outp, sizeof(outp), dest, name);
        if (ents[i].is_dir) { pymcl_ensure_dir(outp); continue; }
        char parent[PYMCL_PATH];
        pymcl_parent(outp, parent, sizeof(parent));
        pymcl_ensure_dir(parent);
        unsigned char *data = NULL; size_t len = 0;
        if (extract_ent(f, &ents[i], &data, &len) != 0) {
            pymcl_set_error("解压失败 %s", ents[i].name);
            rc = -1;
            break;
        }
        if (pymcl_write_file(outp, data, len) != 0) { free(data); rc = -1; break; }
        free(data);
    }
    free(ents);
    fclose(f);
    return rc;
}

int pymcl_extract_jar_natives(const char *jar, const char *dest, cJSON *exclude) {
    pymcl_ensure_dir(dest);
    FILE *f = fopen_rb(jar);
    if (!f) return -1;
    zip_ent *ents = NULL; int n = 0;
    if (read_central(f, &ents, &n) != 0) { fclose(f); return -1; }
    for (int i = 0; i < n; i++) {
        if (ents[i].is_dir || strstr(ents[i].name, "..")) continue;
        int skip = 0;
        if (cJSON_IsArray(exclude)) {
            cJSON *e;
            cJSON_ArrayForEach(e, exclude) {
                if (cJSON_IsString(e) && pymcl_startswith(ents[i].name, e->valuestring)) skip = 1;
            }
        }
        if (skip) continue;
        char name[PYMCL_PATH];
        snprintf(name, sizeof(name), "%s", ents[i].name);
        pymcl_replace_char(name, '/', '\\');
        char outp[PYMCL_PATH];
        pymcl_path_join(outp, sizeof(outp), dest, name);
        char parent[PYMCL_PATH];
        pymcl_parent(outp, parent, sizeof(parent));
        pymcl_ensure_dir(parent);
        unsigned char *data = NULL; size_t len = 0;
        if (extract_ent(f, &ents[i], &data, &len) == 0) {
            pymcl_write_file(outp, data, len);
            free(data);
        }
    }
    free(ents);
    fclose(f);
    return 0;
}

int pymcl_zip_has(const char *zip_path, const char *inner) {
    FILE *f = fopen_rb(zip_path);
    if (!f) return 0;
    zip_ent *ents = NULL; int n = 0;
    if (read_central(f, &ents, &n) != 0) { fclose(f); return 0; }
    int hit = find_ent(ents, n, inner) != NULL;
    free(ents);
    fclose(f);
    return hit;
}

char *pymcl_zip_read(const char *zip_path, const char *inner, size_t *len) {
    if (len) *len = 0;
    FILE *f = fopen_rb(zip_path);
    if (!f) return NULL;
    zip_ent *ents = NULL; int n = 0;
    if (read_central(f, &ents, &n) != 0) { fclose(f); return NULL; }
    const zip_ent *e = find_ent(ents, n, inner);
    unsigned char *data = NULL; size_t nout = 0;
    if (e) extract_ent(f, e, &data, &nout);
    free(ents);
    fclose(f);
    if (len) *len = nout;
    return (char *)data;
}

int pymcl_zip_extract_one(const char *zip_path, const char *inner, const char *dest) {
    size_t n = 0;
    char *p = pymcl_zip_read(zip_path, inner, &n);
    if (!p) return -1;
    int r = pymcl_write_file(dest, p, n);
    free(p);
    return r;
}

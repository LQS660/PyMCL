#include "zipmin.h"
#include <zlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <windows.h>

static uint32_t ru32(const unsigned char *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static uint16_t ru16(const unsigned char *p) {
    return (uint16_t)(p[0] | (p[1] << 8));
}
static FILE *wfopen_rb(const wchar_t *p) { return _wfopen(p, L"rb"); }
static FILE *wfopen_wb(const wchar_t *p) { return _wfopen(p, L"wb"); }

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

static int mkdir_p(const wchar_t *path) {
    wchar_t buf[4096];
    wcsncpy(buf, path, 4095); buf[4095] = 0;
    size_t n = wcslen(buf);
    if (n && (buf[n - 1] == L'\\' || buf[n - 1] == L'/')) buf[n - 1] = 0;
    for (wchar_t *p = buf; *p; p++) {
        if (*p == L'/' ) *p = L'\\';
        if (*p == L'\\' && p > buf + 2) {
            wchar_t c = *p; *p = 0;
            CreateDirectoryW(buf, NULL);
            *p = c;
        }
    }
    return CreateDirectoryW(buf, NULL) || GetLastError() == ERROR_ALREADY_EXISTS ? 0 : -1;
}

static void parent_w(const wchar_t *p, wchar_t *out, size_t n) {
    wcsncpy(out, p, n - 1); out[n - 1] = 0;
    wchar_t *s = out + wcslen(out);
    while (s > out && (s[-1] == L'\\' || s[-1] == L'/')) *--s = 0;
    while (s > out && s[-1] != L'\\' && s[-1] != L'/') *--s = 0;
    if (s > out) s[-1] = 0;
}

static int write_file(const wchar_t *path, const void *data, size_t len) {
    wchar_t par[4096];
    parent_w(path, par, 4096);
    if (par[0]) mkdir_p(par);
    FILE *f = wfopen_wb(path);
    if (!f) return -1;
    size_t w = fwrite(data, 1, len, f);
    fclose(f);
    return w == len ? 0 : -1;
}

int zipmin_extract(const wchar_t *zip_path, const wchar_t *dest) {
    FILE *f = wfopen_rb(zip_path);
    if (!f) return -1;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return -1; }
    long sz = ftell(f);
    if (sz < 22) { fclose(f); return -1; }
    long maxscan = sz < 65557 ? sz : 65557;
    unsigned char *tail = (unsigned char *)malloc((size_t)maxscan);
    if (!tail) { fclose(f); return -1; }
    if (fseek(f, sz - maxscan, SEEK_SET) != 0) { free(tail); fclose(f); return -1; }
    size_t n = fread(tail, 1, (size_t)maxscan, f);
    uint32_t cd_off = 0, cd_size = 0;
    uint16_t nrec = 0;
    int found = 0;
    for (long i = (long)n - 22; i >= 0; i--) {
        if (ru32(tail + i) == 0x06054b50u) {
            nrec = ru16(tail + i + 10);
            cd_size = ru32(tail + i + 12);
            cd_off = ru32(tail + i + 16);
            found = 1;
            break;
        }
    }
    free(tail);
    if (!found) { fclose(f); return -1; }
    if (fseek(f, (long)cd_off, SEEK_SET) != 0) { fclose(f); return -1; }
    unsigned char *cd = (unsigned char *)malloc(cd_size ? cd_size : 1);
    if (!cd || fread(cd, 1, cd_size, f) != cd_size) { free(cd); fclose(f); return -1; }
    mkdir_p(dest);
    int rc = 0;
    size_t off = 0;
    for (int i = 0; i < nrec && off + 46 <= cd_size; i++) {
        if (ru32(cd + off) != 0x02014b50u) break;
        uint16_t method = ru16(cd + off + 10);
        uint32_t comp = ru32(cd + off + 20);
        uint32_t uncomp = ru32(cd + off + 24);
        uint16_t nl = ru16(cd + off + 28);
        uint16_t el = ru16(cd + off + 30);
        uint16_t cl = ru16(cd + off + 32);
        uint32_t local_off = ru32(cd + off + 42);
        char name[1024];
        size_t nn = nl < 1023 ? nl : 1023;
        memcpy(name, cd + off + 46, nn);
        name[nn] = 0;
        off += 46u + nl + el + cl;
        if (strstr(name, "..")) continue;
        int is_dir = nn && (name[nn - 1] == '/' || name[nn - 1] == '\\');
        wchar_t wname[1024], outp[4096];
        MultiByteToWideChar(CP_UTF8, 0, name, -1, wname, 1024);
        for (wchar_t *q = wname; *q; q++) if (*q == L'/') *q = L'\\';
        _snwprintf(outp, 4096, L"%s\\%s", dest, wname);
        if (is_dir) { mkdir_p(outp); continue; }
        if (fseek(f, (long)local_off, SEEK_SET) != 0) { rc = -1; break; }
        unsigned char lh[30];
        if (fread(lh, 1, 30, f) != 30 || ru32(lh) != 0x04034b50u) { rc = -1; break; }
        uint16_t lnl = ru16(lh + 26), lel = ru16(lh + 28);
        if (fseek(f, lnl + lel, SEEK_CUR) != 0) { rc = -1; break; }
        unsigned char *rawc = NULL, *raw = NULL;
        if (comp) {
            rawc = (unsigned char *)malloc(comp);
            if (!rawc || fread(rawc, 1, comp, f) != comp) { free(rawc); rc = -1; break; }
        }
        raw = (unsigned char *)malloc(uncomp + 1);
        if (!raw) { free(rawc); rc = -1; break; }
        int ok = -1;
        if (method == 0 && comp == uncomp) {
            memcpy(raw, rawc ? rawc : (const unsigned char *)"", uncomp);
            ok = 0;
        } else if (method == 8) {
            ok = inflate_raw(rawc, comp, raw, uncomp);
        }
        free(rawc);
        if (ok != 0) { free(raw); rc = -1; break; }
        if (write_file(outp, raw, uncomp) != 0) { free(raw); rc = -1; break; }
        free(raw);
    }
    free(cd);
    fclose(f);
    return rc;
}

#include "pymcl.h"
#include <math.h>

/* Python 语义的小工具：bool(x)、int(x)、x or default、str(x)。
   移植 bridge/api.py 时照着 Python 表达式逐个套用，别各处手写一遍真假判断。 */

int py_truthy(const cJSON *v) {
    if (!v || cJSON_IsNull(v) || cJSON_IsFalse(v)) return 0;
    if (cJSON_IsTrue(v)) return 1;
    if (cJSON_IsNumber(v)) return v->valuedouble != 0;
    if (cJSON_IsString(v)) return v->valuestring && v->valuestring[0];
    if (cJSON_IsArray(v) || cJSON_IsObject(v)) return v->child != NULL;
    return 1;
}

int py_int(const cJSON *v, long long *out) {
    if (!v) return 0;
    if (cJSON_IsBool(v)) { *out = cJSON_IsTrue(v); return 1; }
    if (cJSON_IsNumber(v)) {
        double d = v->valuedouble;
        if (d != d || isinf(d)) return 0;
        *out = (long long)trunc(d);
        return 1;
    }
    if (cJSON_IsString(v) && v->valuestring) {
        const char *s = v->valuestring;
        while (*s == ' ' || *s == '\t' || *s == '\n' || *s == '\r') s++;
        char *end = NULL;
        long long x = strtoll(s, &end, 10);
        if (!end || end == s) return 0;
        while (*end == ' ' || *end == '\t' || *end == '\n' || *end == '\r') end++;
        if (*end) return 0;
        *out = x;
        return 1;
    }
    return 0;
}

long long py_int_or(const cJSON *v, long long fallback) {
    long long x;
    return py_int(v, &x) ? x : fallback;
}

cJSON *py_or(const cJSON *v, cJSON *def) {
    if (py_truthy(v)) {
        cJSON_Delete(def);
        return cJSON_Duplicate(v, 1);
    }
    return def;
}

const char *py_or_str(const cJSON *v, const char *def) {
    if (cJSON_IsString(v) && v->valuestring && v->valuestring[0]) return v->valuestring;
    return def;
}

void py_str(const cJSON *v, char *out, size_t n) {
    if (!v || cJSON_IsNull(v)) { snprintf(out, n, "None"); return; }
    if (cJSON_IsTrue(v)) { snprintf(out, n, "True"); return; }
    if (cJSON_IsFalse(v)) { snprintf(out, n, "False"); return; }
    if (cJSON_IsString(v)) { snprintf(out, n, "%s", v->valuestring ? v->valuestring : ""); return; }
    if (cJSON_IsNumber(v)) {
        double d = v->valuedouble;
        if (d == floor(d) && fabs(d) < 9007199254740992.0) snprintf(out, n, "%lld", (long long)d);
        else snprintf(out, n, "%.17g", d);
        return;
    }
    char *s = cJSON_PrintUnformatted(v);
    snprintf(out, n, "%s", s ? s : "");
    cJSON_free(s);
}

/* list(x)：None/空 → []；list → 拷贝；dict → 键；str → 逐字符 */
cJSON *py_list(const cJSON *v) {
    cJSON *out = cJSON_CreateArray();
    if (!py_truthy(v)) return out;
    if (cJSON_IsArray(v)) {
        cJSON_Delete(out);
        return cJSON_Duplicate(v, 1);
    }
    if (cJSON_IsObject(v)) {
        const cJSON *c;
        cJSON_ArrayForEach(c, v) cJSON_AddItemToArray(out, cJSON_CreateString(c->string));
        return out;
    }
    if (cJSON_IsString(v)) {
        const char *s = v->valuestring;
        while (*s) {
            int len = 1;
            unsigned char c = (unsigned char)*s;
            if (c >= 0xF0) len = 4; else if (c >= 0xE0) len = 3; else if (c >= 0xC0) len = 2;
            char ch[8] = {0};
            memcpy(ch, s, (size_t)len);
            cJSON_AddItemToArray(out, cJSON_CreateString(ch));
            s += len;
        }
    }
    return out;
}

long long py_clamp_int(const cJSON *v, long long lo, long long hi, long long fallback) {
    long long x;
    if (!py_int(v, &x)) return fallback;
    return x < lo ? lo : (x > hi ? hi : x);
}

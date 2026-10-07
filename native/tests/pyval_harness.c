/* Standalone regression tests for native/src/pyval.c.
   From the project root (MinGW):
   gcc -std=c11 -Wall -Wextra -Wno-unused-parameter -Inative/include -Inative/vendor \
       native/tests/pyval_harness.c native/src/pyval.c native/vendor/cJSON.c \
       -o native/tests/pyval_harness.exe -lm
   native/tests/pyval_harness.exe
*/
#include "pymcl.h"
#include <errno.h>
#include <limits.h>
#include <math.h>

static int failures;

static void check_int(const char *json, int expected_ok, long long expected) {
    cJSON *v = cJSON_Parse(json);
    long long result = 1234;
    if (!v) {
        fprintf(stderr, "cannot parse: %s\n", json);
        failures++;
        return;
    }
    int ok = py_int(v, &result);
    if (ok != expected_ok || (ok && result != expected) || (!ok && result != 1234)) {
        fprintf(stderr, "py_int(%s): ok=%d value=%lld, expected ok=%d value=%lld\n",
                json, ok, result, expected_ok, expected);
        failures++;
    }
    cJSON_Delete(v);
}

int main(void) {
    check_int("true", 1, 1);
    check_int("-2.75", 1, -2);
    check_int("\"  +42 \"", 1, 42);
    check_int("\"9223372036854775807\"", 1, LLONG_MAX);
    check_int("\"-9223372036854775808\"", 1, LLONG_MIN);
    check_int("-9223372036854775808", 1, LLONG_MIN);
    check_int("9223372036854774784", 1, LLONG_MAX - 1023);
    check_int("9223372036854775808", 0, 0);
    check_int("-9223372036854777856", 0, 0);
    check_int("\"9223372036854775808\"", 0, 0);
    check_int("\"-9223372036854775809\"", 0, 0);
    check_int("\" 9999999999999999999999999999999999999\"", 0, 0);
    check_int("\"not a number\"", 0, 0);
    cJSON *bounds = cJSON_CreateNumber(-0x1p63);
    long long min_result = 0;
    if (!bounds || !py_int(bounds, &min_result) || min_result != LLONG_MIN) {
        fprintf(stderr, "numeric LLONG_MIN should convert successfully\n");
        failures++;
    }
    cJSON_Delete(bounds);
    bounds = cJSON_CreateNumber(nextafter(0x1p63, 0));
    if (!bounds || !py_int(bounds, &min_result) || min_result != LLONG_MAX - 1023) {
        fprintf(stderr, "largest in-range double should convert successfully\n");
        failures++;
    }
    cJSON_Delete(bounds);
    bounds = cJSON_CreateNumber(INFINITY);
    if (!bounds || py_int(bounds, &min_result)) {
        fprintf(stderr, "infinite number should be rejected\n");
        failures++;
    }
    cJSON_Delete(bounds);
    cJSON *v = cJSON_Parse("\"9223372036854775808\"");
    if (!v || py_int_or(v, 37) != 37 || py_clamp_int(v, 1, 100, 37) != 37) {
        fprintf(stderr, "overflow string must use caller fallback\n");
        failures++;
    }
    cJSON_Delete(v);
    errno = ERANGE;
    v = cJSON_Parse("\"15\"");
    if (!v || !py_int(v, &min_result) || min_result != 15) {
        fprintf(stderr, "previous errno should not invalidate a valid number\n");
        failures++;
    }
    cJSON_Delete(v);
    fprintf(stdout, "pyval checks: %s (%d failures)\n", failures ? "FAIL" : "PASS", failures);
    return failures ? 1 : 0;
}

#include "pymcl.h"

/* AI 回合状态（bridge/api.py 的 _ai_busy / _ai_pending_card）。回合内核随 M5 逐步移植进来。 */

static volatile LONG g_busy;
static cJSON *g_pending_card;

int ai_is_busy(void) { return g_busy != 0; }

cJSON *ai_pending_card(void) {
    if (!g_busy || !g_pending_card) return NULL;
    return cJSON_Duplicate(g_pending_card, 1);
}

# -*- coding: utf-8 -*-
"""AI 默认值。

内置公益网关（开箱即用）：这是一个标准 NewAPI 服务，所以默认接入方式是
ai_mode="custom" + ai_base_url=<内置网关>/v1 + ai_api_key=<内置令牌>。

网关地址与令牌在此做了「中度」混淆：仅按字节 XOR + Base64 存储，运行时解码，
目的是让 strings 扫描 / 顺手抄袭的小白拿不到明文字符串。这不是安全边界——
真正想白嫖的人反编译照样能还原，所以不在这里面塞任何高价值凭证。
"""

from mclauncher import APP_VERSION

# ---------------- 内置公益网关（中度混淆，防小白顺手抄，非安全边界） ----------------
# 逐字节 XOR 掩码后的数组，运行时解码回字符串（与 C 桥 native/src/settings.c 一致）。
_GW_MASK = 0x5A
_GW_BYTES = (50, 46, 46, 42, 41, 96, 117, 117, 52, 63, 45, 116,
             105, 43, 116, 50, 59, 51, 40)

# 令牌掩码 + 字节数组（同上）。
_TOK_MASK = 0x37
_TOK_BYTES = (68, 92, 26, 64, 116, 0, 7, 110, 86, 3, 125, 98, 98, 94, 100, 93, 71, 97, 123, 92,
              121, 113, 113, 83, 120, 6, 97, 85, 99, 65, 91, 89, 123, 124, 85, 6, 88, 96, 94,
              127, 125, 112, 69, 97, 96, 6, 0, 2, 127, 85, 66)


def _unmask(data, mask: int) -> str:
    return bytes((b ^ mask) & 0xFF for b in data).decode("utf-8", errors="replace")


def default_gateway_url() -> str:
    """内置公益网关根地址（不带 /v1）。"""
    try:
        return _unmask(_GW_BYTES, _GW_MASK).strip().rstrip("/")
    except Exception:  # noqa: BLE001
        return ""


def default_api_base() -> str:
    """内置网关的 OpenAI 兼容 base_url（到 /v1 为止）。"""
    gw = default_gateway_url()
    return gw + "/v1" if gw else ""


def default_api_key() -> str:
    """内置公益网关令牌（混淆存储，运行期解码）。"""
    try:
        return _unmask(_TOK_BYTES, _TOK_MASK).strip()
    except Exception:  # noqa: BLE001
        return ""


# 兼容旧引用：旧代码把网关根地址当默认值用。现在语义是「NewAPI 兼容 base」。
DEFAULT_GATEWAY_URL = default_gateway_url()
DEFAULT_API_BASE = default_api_base()
DEFAULT_API_KEY = default_api_key()
DEFAULT_MODEL = "deepseek-v4-flash"
CLIENT_HEADER = f"PyMCL/{APP_VERSION}"

# maxTurns 分层（对齐 ZCode）：主循环放宽到 20，子代理为将来预留
MAX_TOOL_ROUNDS_MAIN = 20
MAX_TOOL_ROUNDS_SUBAGENT = 4
MAX_TOOL_ROUNDS = MAX_TOOL_ROUNDS_MAIN   # 主循环别名，兼容既有引用
MAX_HISTORY = 24
MAX_TOOL_RESULT = 8000

STREAM_CONNECT_TIMEOUT = 15
STREAM_READ_TIMEOUT = 90
ONCE_TIMEOUT = 90

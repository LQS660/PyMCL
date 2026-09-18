# -*- coding: utf-8 -*-
"""AI 默认值。打包给小白前把 DEFAULT_GATEWAY_URL 改成你的公益网关公网地址。"""

from mclauncher import APP_VERSION

# 例: "https://ai.your-domain.com"  不要带 /v1 或 /pymcl/chat
DEFAULT_GATEWAY_URL = ""
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

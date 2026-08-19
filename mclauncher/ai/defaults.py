# -*- coding: utf-8 -*-
"""AI 默认值。打包给小白前把 DEFAULT_GATEWAY_URL 改成你的公益网关公网地址。"""

from mclauncher import APP_VERSION

# 例: "https://ai.your-domain.com"  不要带 /v1 或 /pymcl/chat
DEFAULT_GATEWAY_URL = ""
DEFAULT_MODEL = "deepseek-v4-flash"
CLIENT_HEADER = f"PyMCL/{APP_VERSION}"

# 写操作必须二次确认
WRITE_TOOLS = {
    "install_game",
    "install_mod",
    "install_modpack",
    "install_shader",
    "install_resourcepack",
    "install_datapack",
    "download_java",
    "launch_game",
    "create_instance",
    "delete_instance",
    "delete_mod",
    "disable_mod",
    "enable_mod",
    "write_mod_config",
}

MAX_TOOL_ROUNDS = 10
MAX_HISTORY = 24
MAX_TOOL_RESULT = 8000

# 这些会进下载任务栏，对话里不要卡到结束
LONG_TOOLS = {
    "install_game",
    "install_mod",
    "install_modpack",
    "install_shader",
    "install_resourcepack",
    "install_datapack",
    "download_java",
}

STREAM_CONNECT_TIMEOUT = 15
STREAM_READ_TIMEOUT = 90
ONCE_TIMEOUT = 90

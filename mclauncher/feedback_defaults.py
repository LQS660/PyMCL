# -*- coding: utf-8 -*-
"""反馈上报默认值。打包给用户前把 DEFAULT_FEEDBACK_URL 改成你的反馈中心公网地址。"""

from mclauncher import APP_VERSION

# 例: "https://feedback.your-domain.com"  指向上报口，不要带 /api，不要填看板端口
DEFAULT_FEEDBACK_URL = "http://114.66.28.184:53611"
CLIENT_HEADER = f"PyMCL/{APP_VERSION}"
HEARTBEAT_SEC = 30
COLLECT_CACHE_SEC = 120
CATEGORIES = (
    ("bug", "功能异常"),
    ("crash", "崩溃闪退"),
    ("download", "下载问题"),
    ("multiplayer", "联机"),
    ("ai", "AI 助手"),
    ("ui", "界面体验"),
    ("suggest", "建议"),
    ("other", "其他"),
)

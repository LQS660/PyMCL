# -*- coding: utf-8 -*-
"""兼容入口：布局数据层已下沉到 mclauncher.ui_layout，供 Qt 与 eziapp 桥接共用。

这里只做 re-export，app/dashboard.py、pages/launch_page.py、pages/layout_settings.py
及历次冒烟脚本里的 `from app import layout_model` 一律不必改。
"""

from mclauncher.ui_layout import *  # noqa: F401,F403
from mclauncher.ui_layout import (  # noqa: F401  显式列出，IDE / 静态检查能看见
    CARD_MIN_SIZE, DEFAULT_PROFILE, FALLBACK_MIN, LAYOUT_VERSION,
    LayoutDoc, LayoutItem, _cfg, _clamp01, active_profile, activate_profile,
    default_doc, delete_profile, export_doc, import_doc, list_profiles,
    load_active_doc, min_size_for, parse_doc, reset_to_default,
    save_active_doc, save_profile,
)

# -*- coding: utf-8 -*-
"""界面动效开关。"""


def ui_motion_ok() -> bool:
    """换页淡出 / 画布微动效 / 进度补间等是否播放。

    只看应用内设置 ui_motion（默认开），不跟随 Windows「窗口内动画」系统
    标志：那个标志常被系统优化或远程会话静默关掉，用户侧表现为所有
    动效全部消失。
    """
    try:
        from mclauncher.config import CONFIG
        return bool(CONFIG.get("ui_motion", True))
    except Exception:
        return True

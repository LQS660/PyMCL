# -*- coding: utf-8 -*-
"""系统动画偏好：Windows「在窗口内显示动画」等。"""


def system_animations_enabled() -> bool:
    """读 SPI_GETCLIENTAREAANIMATION；失败时默认开。"""
    try:
        import ctypes
        from ctypes import wintypes

        SPI_GETCLIENTAREAANIMATION = 0x1042
        flag = wintypes.BOOL()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(flag), 0
        )
        if ok:
            return bool(flag.value)
    except Exception:
        pass
    return True


def ui_motion_ok() -> bool:
    """换页 / Shine / 悬停等通用动效是否应播放。"""
    return system_animations_enabled()

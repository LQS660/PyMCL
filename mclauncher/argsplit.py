# -*- coding: utf-8 -*-
"""拆 JVM / 游戏附加参数，兼容引号。"""
import shlex


def split_args(text) -> list:
    raw = str(text or "").strip()
    if not raw:
        return []
    try:
        # JVM/游戏参数按 POSIX 引号写（PCL/HMCL 同款），不要用 Windows shlex。
        return [a for a in shlex.split(raw, posix=True) if a]
    except ValueError:
        return raw.split()

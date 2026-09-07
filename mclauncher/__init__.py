# -*- coding: utf-8 -*-
"""PyMCL - 一个支持全部 Minecraft 版本的 Python 启动器。"""

APP_NAME = "PyMCL"
APP_DISPLAY_NAME = "PyMCL 启动器"
APP_VERSION = "1.0.1"
APP_ID = "pymcl"

LAUNCHER_NAME = "PyMCL"
LAUNCHER_VERSION = "1.0.1"

__version__ = APP_VERSION

from .net import apply_proxy_policy

apply_proxy_policy()

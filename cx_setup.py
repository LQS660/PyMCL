# -*- coding: utf-8 -*-
# cx_Freeze 打包配置（不需要 PyInstaller，绕开 Python 指令表损坏的问题）
import sys

from cx_Freeze import Executable, setup

base = "Win32GUI" if sys.platform == "win32" else None  # Win32GUI = 无黑色控制台窗口

setup(
    name="PyMCL",
    version="1.0.0",
    description="PyMCL Minecraft Launcher",
    options={"build_exe": {}},
    executables=[
        Executable(
            "launcher_entry.py",
            base=base,
            target_name="PyMCL",
        )
    ],
)

# -*- mode: python ; coding: utf-8 -*-
"""EziApp 单文件 exe：本地桥接 + 前端产物，双击即用，不依赖 Qt。

入口是 eziapp_launcher.py——它起一个只听回环的桥接服务、把 eziapp/dist 用本地
静态服务器发出去，再拿一次性 token 打开浏览器。前端产物直接打进包里（解包到
_MEIPASS），配置 / 实例 / 缓存仍然落在 exe 旁边（见 mclauncher.utils._resolve_root）。

    pyinstaller --noconfirm --clean PyMCL-EziApp.spec   →  dist/PyMCL-EziApp.exe

前置：eziapp/dist 得是最新的（cd eziapp && npm run build:web）。
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

_DIST = Path("eziapp/dist")
if not _DIST.is_dir():
    raise SystemExit("缺少 eziapp/dist，请先 cd eziapp && npm run build:web")

datas = [
    ("eziapp/dist", "eziapp/dist"),
    # 语言包是 JSON 数据文件，collect_submodules 带不进来
    ("mclauncher/locales", "mclauncher/locales"),
]

# 桥接是按方法名反射派发的，整包收进来，别让哪个 RPC 在 exe 里变成 ImportError
hiddenimports = collect_submodules("mclauncher") + collect_submodules("bridge")

# 这份 exe 不带界面层：Qt 那一套、打包用的工具链、科学计算全部排除
excludes = [
    "PySide6", "shiboken6", "qfluentwidgets", "qframelesswindow", "app",
    "tkinter", "_tkinter", "turtle", "turtledemo", "test", "unittest",
    "pydoc", "doctest", "xmlrpc", "lib2to3", "ensurepip", "idlelib", "venv",
    "setuptools", "pkg_resources", "numpy", "PIL", "Pillow", "scipy",
    "matplotlib", "colorthief", "PyInstaller",
]

a = Analysis(
    ["eziapp_launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PyMCL-EziApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    # 控制台留着：这一个窗口就是桥接服务的寿命，关掉它等于退出；
    # 出错时的 traceback 也只有这儿看得见。
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

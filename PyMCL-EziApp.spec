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

_UIHOST = Path("uihost/build/pymcl-ui.exe")
if not _UIHOST.is_file():
    raise SystemExit("缺少 uihost/build/pymcl-ui.exe，请先运行 uihost\\build.bat")

datas = [
    ("eziapp/dist", "eziapp/dist"),
    # 内嵌窗口宿主 + 它要的加载器（界面不再开浏览器，见 eziapp_launcher._open_window）
    ("uihost/build/pymcl-ui.exe", "uihost"),
    ("uihost/build/WebView2Loader.dll", "uihost"),
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

    # 下面这些是「开发机上装了就会被收进来」的可选件，运行时一个都走不到。
    # 改这份清单前先跑 python _excludes_check.py：它把这里的名字全屏蔽掉，
    # 再把 mclauncher + bridge 整包 import 一遍，谁真的要用会当场报出来。
    # urllib3 的可选传输层：br 压缩、HTTP/2、SOCKS、pyOpenSSL 注入，缺了它只是不启用
    "brotli", "brotlicffi", "_brotli", "h2", "hpack", "hyperframe",
    "socks", "OpenSSL",
    # cryptography 只在读 OpenSSH 私钥时要 bcrypt；我们只用 PKCS#8 PEM
    "bcrypt",
    # cffi 的 Python 层（_cffi_backend 那个扩展还得留着，cryptography 导入时要）
    "cffi", "pycparser",
    # 只有 concurrent.futures.ProcessPoolExecutor 会牵出 multiprocessing，我们只用线程池
    "multiprocessing",
    # 没有任何一条路径用协程
    "asyncio",
    # decimal 的纯 Python 后备，_decimal 扩展在包里
    "_pydecimal",
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
    # -OO：字节码里不留文档字符串（这个仓库的中文 docstring 很密），assert 也一并去掉；
    # mclauncher / bridge 里没有 assert，也没有谁读 __doc__
    optimize=2,
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

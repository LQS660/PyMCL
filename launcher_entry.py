# -*- coding: utf-8 -*-
"""冻结后 exe 的真正入口：捕获一切启动错误，弹窗显示 + 写日志。

双击 exe 没反应时，有它就能看到具体报错，方便排查。
"""
import sys
import traceback
from pathlib import Path


def _fail(msg):
    # 1. 写日志到 exe 所在目录
    try:
        exe_dir = Path(sys.executable).resolve().parent
        with open(exe_dir / "pymcl-error.log", "a", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write(msg + "\n")
    except OSError:
        pass
    # 2. 弹窗显示（不依赖 tkinter，用系统 API，tkinter 坏了也能弹）
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, msg[-1500:], "PyMCL 启动失败", 0x10)
    except Exception:
        pass
    sys.exit(1)


if __name__ == "__main__":
    try:
        import main
        from mclauncher.guard import install
        install()
        main.main()
    except SystemExit:
        raise
    except Exception:
        _fail(traceback.format_exc())

# -*- coding: utf-8 -*-
"""像素级验证：壁纸真从内容区透出来，侧栏调半透明后也透得出来。

必须整窗 grab 再按几何取样：壁纸是压在最底层的**兄弟**控件，
单独 grab 侧栏或 stackedWidget 只会画它自己那棵子树，下层兄弟不在里面。
"""
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mclauncher import feedback as _fb  # noqa: E402
_fb.start_heartbeat = lambda *a, **k: None
_fb.stop_heartbeat = lambda *a, **k: None

# 同 _bg_probe.py：配置改指到临时目录，探针怎么折腾都碰不到用户那份 config.json。
# 注意光重定向不够：CONFIG 单例构造时已经把本机 config.json 读进了内存，
# 不复位的话门禁会继承开发者本机的主题/壁纸等设置，结果随机器漂移。
from mclauncher import config as _config  # noqa: E402
_probe_home = tempfile.mkdtemp(prefix="pymcl-bgvisual-")
_config.CONFIG_FILE = Path(_probe_home) / "config.json"
_config.CONFIG.data = dict(_config.DEFAULT_CONFIG)
_config.CONFIG.save()

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

app = QApplication([])
tmp = os.path.abspath("_bg_visual_tmp.png").replace(os.sep, "/")
img = QImage(600, 400, QImage.Format_RGB32)
img.fill(0xFF2E7D32)
img.save(tmp)

from app.main_window import MainWindow  # noqa: E402

# 首启向导和反馈授权都是模态框，show() 之后 400ms 由定时器弹出来。
# 这个探针要反复 processEvents，不掐掉它就会停在一个看不见的对话框上。
MainWindow._boot_extras = lambda self: None

BG = (0x2E, 0x7D, 0x32)


def greenish(name: str, tol: int) -> bool:
    """壁纸是纯绿；半透明混过一层侧栏底色后允许偏一些。"""
    r, g, b = (int(name[i:i + 2], 16) for i in (1, 3, 5))
    return all(abs(a - c) < tol for a, c in zip((r, g, b), BG))


win = MainWindow()
code = 1
try:
    win.resize(1180, 760)
    win.show()
    app.processEvents()

    def sample(widget, tol=14):
        shot = win.grab().toImage()
        top = widget.mapTo(win, QPoint(0, 0))
        w, h = widget.width(), widget.height()
        pts = [(6, 6), (w - 7, 6), (6, h - 7), (w - 7, h - 7), (w // 2, h // 2)]
        names = [shot.pixelColor(top.x() + x, top.y() + y).name() for x, y in pts]
        return names, sum(1 for c in names if greenish(c, tol))

    win.backend.save_settings({"ui_background": "", "ui_sidebar_opacity": 100,
                               "ui_background_blur": 0, "ui_background_dim": 0})
    win.apply_theme()
    app.processEvents()
    names, hits = sample(win.stackedWidget)
    print("no-bg content :", names, "green", hits)
    ok_off = hits == 0

    win.backend.save_settings({"ui_background": tmp})
    win.apply_theme()
    app.processEvents()
    names, hits = sample(win.stackedWidget)
    print("bg-on content :", names, "green", hits)
    ok_content = hits >= 3

    # 侧栏 100% 时挡住壁纸；调到 40% 后必须透出明显的绿
    names, hits = sample(win.side)
    print("side 100%     :", names, "green", hits)
    ok_side_solid = hits == 0

    win.backend.save_settings({"ui_sidebar_opacity": 40})
    win.apply_theme()
    app.processEvents()
    names, hits = sample(win.side, tol=90)
    print("side  40%     :", names, "greenish", hits)
    ok_side_alpha = hits >= 3

    # 标题栏跟侧栏共用同一个值，这一档也该透出壁纸
    names, hits = sample(win.titleBar, tol=110)
    print("title 40%     :", names, "greenish", hits)
    ok_title = hits >= 2

    # 遮罩：主题底色是白的，浅色主题下内容区应该被提亮。ui_dark 显式钉住，
    # 不随门禁跑在谁机器上的主题漂移。
    win.backend.save_settings({"ui_sidebar_opacity": 100, "ui_background_dim": 60,
                               "ui_dark": False})
    win.apply_theme()
    app.processEvents()
    names, _ = sample(win.stackedWidget)
    lifted = [int(n[3:5], 16) for n in names[:2]]  # 取绿通道
    print("dim 60%       :", names, "green channel", lifted)
    ok_dim = all(v > 0x7D + 20 for v in lifted)

    for label, ok in (("无壁纸时内容区不见绿", ok_off),
                      ("内容区透出壁纸", ok_content),
                      ("侧栏 100% 挡住壁纸", ok_side_solid),
                      ("侧栏 40% 透出壁纸", ok_side_alpha),
                      ("标题栏 40% 透出壁纸", ok_title),
                      ("遮罩 60% 把壁纸提亮", ok_dim)):
        print(("[ok] " if ok else "[FAIL] ") + label)
    passed = all((ok_off, ok_content, ok_side_solid, ok_side_alpha, ok_title, ok_dim))
    print("VISUAL", "OK" if passed else "FAIL")
    code = 0 if passed else 1
except Exception:
    traceback.print_exc()
finally:
    if os.path.isfile(tmp):
        os.remove(tmp)
    shutil.rmtree(_probe_home, ignore_errors=True)

# 判结果看上面打印的那行 VISUAL，别看退出码：Qt 拆这棵离屏窗口树时偶尔甩一个
# 0xC0000005 出来把它盖掉（HEAD 上也这样，跟壁纸无关）。
# 别拿 os._exit() 去「修」它：ExitProcess 会等其它线程收场，实测反过来把进程永远
# 卡在退出那一步，连 taskkill 都收不掉。close() 和收尾 processEvents() 同理会卡。
sys.exit(code)

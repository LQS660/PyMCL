# -*- coding: utf-8 -*-
"""对话框冒烟：离屏构造 app 里全部对话框，抓构造期异常与关闭后回调崩溃。

_ui_smoke.py 只覆盖了页面导航，对话框一个都没碰过。
"""
import faulthandler
import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LOG = open("_ui_dialog_probe_out.txt", "w", encoding="utf-8")
faulthandler.enable(LOG)


def say(*a):
    print(*a)
    print(*a, file=LOG)
    sys.stdout.flush()
    LOG.flush()


from mclauncher import feedback as _fb  # noqa: E402
_fb.start_heartbeat = lambda *a, **k: None
_fb.stop_heartbeat = lambda *a, **k: None

from PySide6.QtCore import QTimer, qInstallMessageHandler  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

qt_msgs = []
qInstallMessageHandler(lambda t, ctx, m: qt_msgs.append((int(t), m)))

app = QApplication([])

from app.backend import BackendAPI  # noqa: E402

backend = BackendAPI()
host = QWidget()
host.resize(1180, 760)
host.show()

instances = [i["name"] for i in (backend.get_instances() or [])] or ["default"]
inst = instances[0]
versions = backend.get_installed_versions(inst) or [""]
ver = versions[0]
say(f"instance={inst!r} version={ver!r}")


def pump(ms=600):
    end = [False]
    QTimer.singleShot(ms, lambda: end.__setitem__(0, True))
    while not end[0]:
        app.processEvents()


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


@case("InputDialog")
def _c1():
    from app.widgets import InputDialog
    return InputDialog("标题", "说明", "初值", "占位", host)


@case("ComboDialog")
def _c2():
    from app.widgets import ComboDialog
    return ComboDialog("标题", "说明", ["A", "B"], "A", host)


@case("DeviceCodeDialog")
def _c3():
    from app.widgets import DeviceCodeDialog
    d = DeviceCodeDialog(host)
    d.show_code("ABCD-EFGH", "https://microsoft.com/link")
    d.show_status("等待授权…")
    return d


@case("FirstRunDialog")
def _c4():
    from app.pages.first_run import FirstRunDialog
    return FirstRunDialog(backend, host)


@case("InstallWizardDialog")
def _c5():
    from app.pages.install_wizard import InstallWizardDialog
    d = InstallWizardDialog(backend, "1.20.1", inst, host)
    d.primary.setCurrentText("Fabric")
    d.optifine.setChecked(True)
    d.payload()
    return d


@case("VersionSetupDialog")
def _c6():
    from app.pages.version_setup import VersionSetupDialog
    d = VersionSetupDialog(backend, inst, ver or "1.20.1", host)
    d.payload()
    return d


@case("SavesDialog")
def _c7():
    from app.pages.saves_dialog import SavesDialog
    d = SavesDialog(backend, inst, ver, host)
    for k in ("存档", "备份", "截图", "崩溃报告", "日志"):
        d.kind.setCurrentText(k)
    return d


@case("GlobalModsDialog")
def _c8():
    from app.pages.global_mods_dialog import GlobalModsDialog
    return GlobalModsDialog(backend, host)


@case("FilePickDialog")
def _c9():
    from app.pages.file_pick import FilePickDialog
    d = FilePickDialog(backend, {"name": "JEI", "slug": "jei", "source": "Modrinth"},
                       "mod", "", host)
    d.selected_extra()
    return d


@case("CrashDialog(report)")
def _c10():
    from app.pages.crash_dialog import CrashDialog
    return CrashDialog({"title": "崩溃", "headline": "头", "detail": "堆栈" * 50,
                        "help": "帮助", "output_tail": "tail"}, host, backend=backend)


@case("CrashDialog(no backend / no report)")
def _c11():
    from app.pages.crash_dialog import CrashDialog
    return CrashDialog(None, host, title="启动器出错", detail="x")


for label, fn in CASES:
    try:
        dlg = fn()
        app.processEvents()
        if dlg is not None:
            dlg.close()
            dlg.deleteLater()
        app.processEvents()
        say("  ok:", label)
    except Exception:
        say("  FAIL:", label)
        say(traceback.format_exc())

say("--- 关闭后异步回调（构造完立刻销毁，等回调打回来）---")
for label, fn in (("VersionSetupDialog", _c6), ("InstallWizardDialog", _c5),
                  ("FilePickDialog", _c9), ("SavesDialog", _c7)):
    try:
        dlg = fn()
        dlg.close()
        dlg.deleteLater()
        del dlg
        pump(2500)
        say("  survived:", label)
    except Exception:
        say("  DANGLING FAIL:", label)
        say(traceback.format_exc())

say("--- 深色主题下重建一遍 ---")
try:
    data = backend.get_settings()
    data["ui_dark"] = True
    backend.save_settings(data)
    from app.pcl_chrome import Theme
    Theme.apply(True)
    from qfluentwidgets import setTheme, Theme as FluentTheme
    setTheme(FluentTheme.DARK, save=False)
    for label, fn in CASES:
        try:
            dlg = fn()
            app.processEvents()
            if dlg is not None:
                dlg.close()
                dlg.deleteLater()
            app.processEvents()
            say("  dark ok:", label)
        except Exception:
            say("  DARK FAIL:", label)
            say(traceback.format_exc())
finally:
    data = backend.get_settings()
    data["ui_dark"] = False
    backend.save_settings(data)

say("--- Qt messages (deduped) ---")
seen = set()
for t, m in qt_msgs:
    if m in seen:
        continue
    seen.add(m)
    say(f"[{t}] {m}")

say("DONE")
LOG.close()

# 同 _ui_smoke.py：不能用 os._exit()。Windows 上带着已加载的 Qt 硬退出，
# 会在 DLL detach 阶段偶发 0xC0000005，那是脚本自己制造的假崩溃。
try:
    backend.shutdown()
except Exception:
    pass
host.close()
del backend
del host
app.quit()
app.processEvents()
del app
sys.exit(0)

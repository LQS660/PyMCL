# -*- coding: utf-8 -*-
"""Qt 控件的 parent：漏传一次就是一处故障。

对话框漏传会当场崩——`MaskDialogBase.__init__` 里那句 `parent.width()` 碰上 None
直接抛 AttributeError，用户点的动作断在半路；InfoBar 漏传不崩，但提示条既不排队
也不定位，飘成一个没人管的顶层窗口。两种都不挑时机、不写日志，只有点到那个按钮
的人才撞得上。

扫描器本体在 `scripts/check_qt_parent.py`（pre-commit / CI 跑的是同一份），这里
一是把它挂进测试，二是给扫描器自己做体检，三是按真实入口再走一遍服务器页——
那 5 个 `InputDialog` 全没给 parent，就是这么崩的。
"""
from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from scripts.check_qt_parent import collect_dialogs, scan, scan_calls  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[1] / "app"


class QtParentScanTests(unittest.TestCase):
    """静态扫 app/：每个对话框 / InfoBar 构造点都得有 parent。"""

    @classmethod
    def setUpClass(cls):
        cls.missing, cls.dialogs, cls.total = scan(APP_DIR)

    def test_scan_actually_sees_the_widgets(self):
        """先证明扫描器没空转：认不出类，下面那条断言就永远是绿的。"""
        self.assertIn("InputDialog", self.dialogs)
        self.assertIn("ComboDialog", self.dialogs)
        self.assertGreaterEqual(len(self.dialogs), 10, self.dialogs)
        self.assertGreater(self.total, 200, "构造点数量不对，扫描范围八成缩了")

    def test_every_widget_construction_passes_a_parent(self):
        lines = [v.render(APP_DIR.parent) for v in self.missing]
        self.assertEqual(lines, [], "这些控件没给 parent：\n" + "\n".join(lines))

    def test_scanner_catches_a_missing_dialog_parent(self):
        """扫描器的体检（对话框）：喂一段已知漏传的代码，必须只抓那两行。"""
        src = (
            "class Foo(MessageBoxBase):\n"
            "    def __init__(self, title, parent=None):\n"
            "        pass\n"
            "def go(self):\n"
            "    Foo('t')\n"               # 漏了
            "    Foo('t', self)\n"         # 位置参给了
            "    Foo('t', parent=self)\n"  # 关键字给了
            "    MessageBox('t', 'c')\n"   # 漏了
            "    MessageBox('t', 'c', self)\n"
        )
        tree = ast.parse(src)
        dialogs = collect_dialogs({Path("x.py"): tree})
        self.assertEqual(dialogs.get("Foo"), 1, "parent 的位置算错了")
        hits = scan_calls(Path("x.py"), tree, dialogs)
        self.assertEqual([(v.line, v.name) for v in hits], [(5, "Foo"), (8, "MessageBox")])

    def test_scanner_catches_a_missing_infobar_parent(self):
        """扫描器的体检（InfoBar）：它跟对话框不是一套参数，得单独验。"""
        src = (
            "def go(self):\n"
            "    InfoBar.success('已保存', '')\n"                    # 漏了
            "    InfoBar.error('失败', str(e), parent=self)\n"
            "    InfoBar.warning('注意', '', duration=2000)\n"       # 漏了
            "    InfoBar.info('提示', '', **kw)\n"                   # 看不出来，放过
        )
        tree = ast.parse(src)
        hits = scan_calls(Path("x.py"), tree, {})
        self.assertEqual([(v.line, v.name) for v in hits],
                         [(2, "InfoBar.success"), (4, "InfoBar.warning")])
        self.assertTrue(all(v.kind == "infobar" for v in hits))

    def test_scanner_catches_a_missing_statetooltip_parent(self):
        """StateToolTip 跟对话框同属「当场崩」那一类：getSuitablePos() 里
        `self.parent().width()` 没判空。"""
        src = (
            "def go(self):\n"
            "    StateToolTip('正在下载', '', self).show()\n"
            "    StateToolTip('正在下载', '')\n"  # 漏了
        )
        tree = ast.parse(src)
        hits = scan_calls(Path("x.py"), tree, {})
        self.assertEqual([(v.line, v.name) for v in hits], [(3, "StateToolTip")])
        self.assertEqual(hits[0].kind, "widget")

    def test_teachingtip_and_flyout_are_left_alone(self):
        """这两个是靠 target 定位的浮层，parent 本来就可给可不给，库里引用也判了空。
        误报会把整道卡口变成噪音，所以故意不收。"""
        src = (
            "def go(self):\n"
            "    TeachingTip.create(self.btn, '标题', '正文')\n"
            "    Flyout.create('标题', '正文', target=self.btn)\n"
        )
        hits = scan_calls(Path("x.py"), ast.parse(src), {})
        self.assertEqual(hits, [])

    def test_subclass_without_own_init_inherits_the_slot(self):
        """不写 __init__ 的子类按基类算，不能因为查不到就当它没这个参数。"""
        src = (
            "class Base(MessageBoxBase):\n"
            "    def __init__(self, title, parent=None):\n"
            "        pass\n"
            "class Child(Base):\n"
            "    def value(self):\n"
            "        pass\n"
            "def go(self):\n"
            "    Child('t')\n"
        )
        tree = ast.parse(src)
        dialogs = collect_dialogs({Path("x.py"): tree})
        self.assertEqual(dialogs.get("Child"), 1)
        hits = scan_calls(Path("x.py"), tree, dialogs)
        self.assertEqual([(v.line, v.name) for v in hits], [(8, "Child")])


class ServerPageDialogTests(unittest.TestCase):
    """服务器页的真实入口：走一遍 _on_add / _on_edit，框都得挂在页面上。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from app.pages import servers_page
        from app.widgets import InputDialog

        built = []

        class Probe(InputDialog):
            """exec() 一律当作点了「确定」，好让一个入口里的几个框全都构造一遍。"""

            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                built.append(self)

            def exec(self):
                return 1

        self.built = built
        self.servers_page = servers_page
        self._real_dialog = servers_page.InputDialog
        servers_page.InputDialog = Probe
        self.backend = _FakeBackend()
        self.page = servers_page.ServerPage(self.backend)
        self.page.resize(900, 600)

    def tearDown(self):
        self.servers_page.InputDialog = self._real_dialog
        self.page.deleteLater()

    def test_add_builds_three_dialogs_parented_to_the_page(self):
        self.page._on_add()
        self.assertEqual(len(self.built), 3, "名称 / 地址 / 端口 三个框都要弹")
        for dlg in self.built:
            self.assertIs(dlg.parent(), self.page)
        self.assertEqual(len(self.backend.added), 1)

    def test_edit_builds_two_dialogs_parented_to_the_page(self):
        self.page._servers = [{"name": "家里的服", "ip": "1.2.3.4", "port": 25565}]
        self.page._on_edit(0)
        self.assertEqual(len(self.built), 2, "名称 / 地址 两个框都要弹")
        for dlg in self.built:
            self.assertIs(dlg.parent(), self.page)
        self.assertEqual(len(self.backend.updated), 1)

    def test_missing_parent_degrades_instead_of_crashing(self):
        """兜底：真漏传了也只是遮罩认错窗口，不能像以前那样整个抛出来。"""
        from app.widgets import ComboDialog, InputDialog, dialog_parent

        host = QWidget()
        host.resize(900, 600)
        self.addCleanup(host.deleteLater)
        self.assertIsNotNone(dialog_parent(None))
        self.assertIsNotNone(InputDialog("标题", "说明", parent=None).parent())
        self.assertIsNotNone(ComboDialog("标题", "说明", ["甲", "乙"], parent=None).parent())


class _FakeBackend:
    def __init__(self):
        self.added = []
        self.updated = []

    def game_root_name(self):
        return ".minecraft"

    def list_servers(self, instance):
        return []

    def add_server(self, instance, name, ip, port):
        self.added.append((instance, name, ip, port))

    def update_server(self, instance, index, **kw):
        self.updated.append((instance, index, kw))


if __name__ == "__main__":
    unittest.main()

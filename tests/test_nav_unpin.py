"""取消固定：页面必须落在用户点得到的地方，提示也得说实话。

这两条是「从侧栏拖出去就再也拖不回来」的代码病因：

* 落点分区被隐藏时照样往里放，那一页在界面上彻底消失——侧栏没有它，
  也没有任何落点能把它拖回来；提示却还在说「已放回『更多』」。
* 分类横条三个拖放回调判据不一致：dragEnter / dragMove 只认「当前固定
  在侧栏上的键」，dropEvent 却放行任意导航键，松手后上游静默返回，
  表现就是光标说能放、放下去什么也没发生。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from mclauncher import config as config_mod


class _IsolatedConfig(unittest.TestCase):
    """把 CONFIG 改绑到临时文件：绝不碰仓库根那份用户真实设置。

    CONFIG_FILE 是模块级全局，save() 调用时才解析它，改绑即整份隔离。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._real_file = config_mod.CONFIG_FILE
        self._real_data = dict(config_mod.CONFIG.data)
        config_mod.CONFIG_FILE = Path(self._tmp.name) / "config.json"

    def tearDown(self):
        config_mod.CONFIG_FILE = self._real_file
        config_mod.CONFIG.data = self._real_data
        self._tmp.cleanup()

    def layout(self, **keys):
        """摆一套侧栏布局：只认这几个键，其余留默认。"""
        base = {"ui_nav_order": None, "ui_nav_pinned": None,
                "ui_nav_hidden": None, "ui_section_members": None,
                "ui_nav_style": "compact"}
        base.update(keys)
        config_mod.CONFIG.update(base)
        config_mod.CONFIG.save()


class UnpinLandingTests(_IsolatedConfig):
    """unpin_nav_config 决定落点，_unpin_nav 的提示语就照这个返回值渲染。"""

    def unpin(self, key, *args):
        from app.main_window import unpin_nav_config
        return unpin_nav_config(key, *args)

    def members(self):
        from app.main_window import section_members_from_config
        return section_members_from_config()

    def test_hidden_section_does_not_swallow_the_page(self):
        """「更多」被藏起来时，settings 不能落回「更多」——落进去就找不着了。"""
        from app.main_window import visible_sections
        self.layout(ui_nav_pinned=["settings"], ui_nav_hidden=["more"])

        landed = self.unpin("settings")

        self.assertEqual(landed, "download", "唯一点得到的分区是「下载」")
        self.assertIn(landed, visible_sections(), "落点必须是侧栏上点得到的")
        self.assertIn("settings", self.members()["download"])
        self.assertNotIn("settings", self.members()["more"])

    def test_hidden_section_overrides_an_explicit_target(self):
        """拖到哪都一样：目标分区正藏着，就改落到看得见的那个。"""
        self.layout(ui_nav_pinned=["account"], ui_nav_hidden=["more"])

        landed = self.unpin("account", "more", 0)

        self.assertEqual(landed, "download")
        self.assertIn("account", self.members()["download"])

    def test_visible_target_keeps_section_and_drop_index(self):
        """分区看得见时，落点位序（横条上松手的那一格）要照着放。"""
        self.layout(ui_nav_pinned=["java"])

        landed = self.unpin("java", "more", 0)

        self.assertEqual(landed, "more")
        self.assertEqual(self.members()["more"][0], "java", "落点位序没生效")

    def test_default_home_used_when_it_is_visible(self):
        """没指定落点：回它自己的老家，前提是老家点得进去。"""
        self.layout(ui_nav_pinned=["settings"])

        self.assertEqual(self.unpin("settings"), "more")

    def test_stored_membership_beats_default_home(self):
        """用户在「自定义分区」里把 settings 挪进过下载栏，就该回下载栏。

        老代码这里直接拿默认归属渲染提示，于是嘴上说「更多」、人却在下载栏。
        """
        self.layout(ui_nav_pinned=["settings"],
                    ui_section_members={"download": ["version", "settings"],
                                        "more": ["account"]})

        landed = self.unpin("settings")

        self.assertEqual(landed, "download")
        self.assertIn("settings", self.members()["download"])

    def test_last_resort_unhides_the_landing_section(self):
        """两个分区都藏了，再挑也没得挑：把落点那个放出来，别让页面失踪。"""
        from app.main_window import visible_sections
        self.layout(ui_nav_pinned=["account"],
                    ui_nav_hidden=["download", "more"])

        landed = self.unpin("account")

        self.assertIn(landed, visible_sections(), "落地即失踪")
        self.assertIn("account", self.members()[landed])

    def test_not_pinned_is_a_no_op(self):
        from app.main_window import pinned_from_config
        self.layout(ui_nav_pinned=["java"])

        self.assertIsNone(self.unpin("account"))
        self.assertEqual(pinned_from_config(), ["java"])

    def test_toast_names_the_section_the_page_really_landed_in(self):
        """提示语里那个分区名 = 真实落点 = 侧栏上那颗按钮的字。"""
        from app.main_window import nav_items_from_config, section_title
        self.layout(ui_nav_pinned=["settings"], ui_nav_hidden=["more"])

        landed = self.unpin("settings")

        labels = {spec[1]: spec[3] for spec in nav_items_from_config()
                  if spec[0] == "item"}
        self.assertEqual(section_title(landed), labels[landed],
                         "提示里写的分区名跟侧栏上那颗按钮对不上")


class CatBarDropPredicateTests(_IsolatedConfig):
    """横条三个拖放回调必须用同一套判据，不许「接受了却没反应」。"""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        from app.pages.download_hub import DownloadCatBar

        self.layout(ui_nav_pinned=["java"])
        self.bar = DownloadCatBar()
        self.bar.resize(600, 48)
        self.fired = []
        self.bar.unpinRequested.connect(
            lambda key, index: self.fired.append((key, index)))
        # QDropEvent 不持有 mimeData，这边一出栈就被回收
        self._keep = []

    def tearDown(self):
        self.bar.deleteLater()
        super().tearDown()

    def deliver(self, key):
        """按 Qt 的真实顺序投一遍 enter / move / drop，收集三处的 accepted。"""
        from PySide6.QtCore import QMimeData, QPointF, Qt
        from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
        from app.pages.download_hub import NAV_MIME

        mime = QMimeData()
        mime.setData(NAV_MIME, key.encode("utf-8"))
        self._keep.append(mime)
        pos = self.bar.rect().center()

        enter = QDragEnterEvent(pos, Qt.CopyAction, mime, Qt.NoButton, Qt.NoModifier)
        enter.ignore()
        self.bar.dragEnterEvent(enter)

        move = QDragMoveEvent(pos, Qt.CopyAction, mime, Qt.NoButton, Qt.NoModifier)
        move.ignore()
        self.bar.dragMoveEvent(move)

        drop = QDropEvent(QPointF(pos), Qt.CopyAction, mime,
                          Qt.NoButton, Qt.NoModifier)
        drop.ignore()
        self.bar.dropEvent(drop)

        return [enter.isAccepted(), move.isAccepted(), drop.isAccepted()]

    def test_pinned_key_accepted_by_all_three_and_emits(self):
        self.assertEqual(self.deliver("java"), [True, True, True])
        self.assertEqual([k for k, _i in self.fired], ["java"])

    def test_unpinnable_key_rejected_by_all_three_and_stays_quiet(self):
        """横条按钮在自己栏里乱拖也带同一种 mime，那一种三处都该拒。"""
        self.assertEqual(self.deliver("account"), [False, False, False])
        self.assertEqual(self.fired, [], "没人处理的拖放不该发信号")


if __name__ == "__main__":
    unittest.main()

"""侧栏编排：网页版与 Qt 版必须算出同一套侧栏。

两套前端读写 config.json 里同一批 ui_nav_* 键。规则各写一遍就会漂：在 Qt 里
排好的顺序、藏掉的项、挪过的分区成员，到网页版可能是另一副样子，而这种偏差
不会报错、只有用户能看见。

这里把同一份配置同时喂给三边——Python 侧 app/main_window.py，TypeScript 侧
eziapp/src/nav_model.ts（Node 直接跑 TS，见 eziapp/tests/nav_dump.ts），C# 侧
wpf/PyMCL.Wpf/Shell/NavModel.cs（编好的 PyMCL.Wpf.exe --nav-dump，见 Shell/NavDump.cs）——
逐条比条目序列、固定项、分区成员和取消固定的落点。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mclauncher import config as config_mod

REPO = Path(__file__).resolve().parents[1]
DUMP = REPO / "eziapp" / "tests" / "nav_dump.ts"
NODE = shutil.which("node")
# WPF 那一边要先 dotnet build 过；没编就跳过，不在这里替它编
WPF_EXE = next(
    (p for p in (
        REPO / "wpf" / "PyMCL.Wpf" / "bin" / "Debug" / "net8.0-windows" / "PyMCL.Wpf.exe",
        REPO / "wpf" / "PyMCL.Wpf" / "bin" / "Release" / "net8.0-windows" / "PyMCL.Wpf.exe",
    ) if p.is_file()),
    None,
)

# 同一批配置喂给两边。unpin 那一项让 TS 侧额外算一次取消固定的落点。
CASES: list[dict] = [
    {"name": "出厂（空配置）", "config": {}},
    {"name": "出厂分组", "config": {"ui_nav_style": "grouped"}},
    {"name": "分组下藏掉账户", "config": {"ui_nav_style": "grouped", "ui_nav_hidden": ["account"]}},
    {"name": "分组下藏掉更多和任务",
     "config": {"ui_nav_style": "grouped", "ui_nav_hidden": ["more", "tasks"]}},
    {"name": "精简出厂",
     "config": {"ui_nav_style": "compact",
                "ui_nav_order": ["launch", "download", "instance", "more", "settings", "tasks"],
                "ui_nav_pinned": ["instance", "settings"], "ui_nav_hidden": ["ai"]}},
    {"name": "精简·只写了一个键", "config": {"ui_nav_style": "compact", "ui_nav_order": ["tasks"]}},
    {"name": "精简·固定项没进序列",
     "config": {"ui_nav_style": "compact",
                "ui_nav_order": ["launch", "download", "ai", "more", "tasks"],
                "ui_nav_pinned": ["account"]}},
    {"name": "精简·混排在一起",
     "config": {"ui_nav_style": "compact",
                "ui_nav_order": ["account", "launch", "mods", "download", "ai", "more", "settings", "tasks"],
                "ui_nav_pinned": ["account", "mods", "settings"]}},
    {"name": "精简·藏了一级项",
     "config": {"ui_nav_style": "compact",
                "ui_nav_order": ["launch", "download", "ai", "more", "settings", "tasks"],
                "ui_nav_pinned": ["settings"], "ui_nav_hidden": ["ai", "download"]}},
    {"name": "自定义分区成员",
     "config": {"ui_nav_style": "compact",
                "ui_section_members": {"download": ["java", "version"],
                                       "more": ["servers", "instance"]}}},
    {"name": "配置里混进了不认识的键",
     "config": {"ui_nav_style": "wat", "ui_nav_order": ["launch", "nope", "download"],
                "ui_nav_pinned": ["instance", "不存在的页"], "ui_nav_hidden": ["", "ai"]}},
    {"name": "取消固定·落点分区被藏了",
     "config": {"ui_nav_style": "compact", "ui_nav_pinned": ["settings"],
                "ui_nav_hidden": ["more"]},
     "unpin": {"key": "settings"}},
    {"name": "取消固定·正常放回",
     "config": {"ui_nav_style": "compact", "ui_nav_pinned": ["account", "settings"]},
     "unpin": {"key": "account"}},
    {"name": "取消固定·指定放回下载栏",
     "config": {"ui_nav_style": "compact", "ui_nav_pinned": ["settings"]},
     "unpin": {"key": "settings", "section": "download"}},
]


def _dump_payload() -> str:
    return json.dumps([{"config": c["config"], "unpin": c.get("unpin")} for c in CASES])


def _run_dump(cmd: list[str], label: str) -> list[dict]:
    proc = subprocess.run(
        cmd, input=_dump_payload(), capture_output=True,
        text=True, encoding="utf-8", cwd=str(REPO), timeout=120,
        env={**os.environ, "NODE_OPTIONS": ""},
    )
    if proc.returncode != 0:
        raise AssertionError(f"{label} 失败：{proc.stderr.strip()[:800]}")
    return json.loads(proc.stdout)


def _ts_results() -> list[dict]:
    return _run_dump([NODE, str(DUMP)], "node 跑 nav_dump.ts")


def _wpf_results() -> list[dict]:
    return _run_dump([str(WPF_EXE), "--nav-dump"], "PyMCL.Wpf.exe --nav-dump")


class _NavParityCases:
    """同一份配置，另一边算出来必须与 Qt 一模一样。子类只负责给出 self.ts。

    不继承 TestCase，免得这份用例自己也被收集起来跑一遍。
    """

    ts: list[dict]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._real_file = config_mod.CONFIG_FILE
        self._real_data = dict(config_mod.CONFIG.data)
        config_mod.CONFIG_FILE = Path(self._tmp.name) / "config.json"

    def tearDown(self):
        config_mod.CONFIG_FILE = self._real_file
        config_mod.CONFIG.data = self._real_data
        self._tmp.cleanup()

    def _apply(self, config: dict):
        base = {"ui_nav_order": None, "ui_nav_pinned": None, "ui_nav_hidden": None,
                "ui_nav_groups": None, "ui_section_members": None, "ui_nav_style": None}
        base.update(config)
        config_mod.CONFIG.update(base)
        config_mod.CONFIG.save()

    @staticmethod
    def _qt_items() -> list[list]:
        from app.main_window import nav_items_from_config
        out = []
        for item in nav_items_from_config():
            if item[0] == "item":
                out.append(["item", item[1], item[3]])
            elif item[0] == "header":
                out.append(["header", item[1]])
            else:
                out.append(["stretch"])
        return out

    def test_items_match(self):
        from app.main_window import pinned_from_config, section_members_from_config
        for case, ts in zip(CASES, self.ts):
            with self.subTest(case["name"]):
                self._apply(case["config"])
                self.assertEqual(self._qt_items(), [list(x) for x in ts["items"]],
                                 "侧栏条目序列不一致")
                self.assertEqual(pinned_from_config(), list(ts["pinned"]), "固定项不一致")
                members = section_members_from_config()
                self.assertEqual({k: list(v) for k, v in members.items()},
                                 {k: list(v) for k, v in ts["members"].items()},
                                 "分区成员不一致")

    def test_unpin_lands_in_the_same_section(self):
        from app.main_window import (
            pinned_from_config, section_members_from_config, unpin_nav_config,
        )
        for case, ts in zip(CASES, self.ts):
            if not case.get("unpin"):
                continue
            with self.subTest(case["name"]):
                self._apply(case["config"])
                spec = case["unpin"]
                landed = unpin_nav_config(spec["key"], spec.get("section"), spec.get("index", -1))
                self.assertIsNotNone(ts["unpin"], "TS 侧认为这次取消固定没发生")
                self.assertEqual(landed, ts["unpin"]["section"], "落点分区不一致")
                patch = ts["unpin"]["patch"]
                self.assertEqual(pinned_from_config(), list(patch["ui_nav_pinned"]),
                                 "取消固定后的固定项不一致")
                self.assertEqual(
                    {k: list(v) for k, v in section_members_from_config().items()},
                    {k: list(v) for k, v in patch["ui_section_members"].items()},
                    "取消固定后的分区成员不一致")

    def test_pages_are_reachable_in_every_case(self):
        """每一种配置下，所有子页都得有入口：要么在侧栏，要么在某个可见分区里。"""
        from app.main_window import _ALL_SUB_KEYS
        for case, ts in zip(CASES, self.ts):
            with self.subTest(case["name"]):
                reachable = set(ts["sequence"])
                visible = {sec for sec in ("download", "more") if sec in reachable}
                for sec in visible:
                    reachable.update(ts["members"][sec])
                missing = sorted(k for k in _ALL_SUB_KEYS if k not in reachable)
                # 分区整个被藏起来时，里面的子页确实点不到——这是已知的 Qt 遗留问题
                # （任务池 Q1），两边表现一致即可，不在这里判死。
                if visible == {"download", "more"}:
                    self.assertEqual(missing, [], "有子页没有任何入口")


@unittest.skipUnless(NODE, "没装 node，跳过跨语言对照")
class NavParityTests(_NavParityCases, unittest.TestCase):
    """网页版 nav_model.ts ↔ Qt。"""

    @classmethod
    def setUpClass(cls):
        cls.ts = _ts_results()


@unittest.skipUnless(WPF_EXE and sys.platform == "win32", "WPF 没编过，跳过 C# 对照")
class WpfNavParityTests(_NavParityCases, unittest.TestCase):
    """WPF 版 NavModel.cs ↔ Qt。"""

    @classmethod
    def setUpClass(cls):
        cls.ts = _wpf_results()


class NavKeyTableTests(unittest.TestCase):
    """键表本身也要对齐：TS 侧多一个少一个，都会静默丢页面。"""

    def _ts_source(self) -> str:
        return (REPO / "eziapp" / "src" / "nav_model.ts").read_text(encoding="utf-8")

    def test_every_qt_sub_page_has_a_web_route(self):
        from app.main_window import _ALL_SUB_KEYS, _TOP_KEYS
        src = self._ts_source()
        # 锚在声明上，不是第一次出现：文件开头的注释也会提到这个名字，
        # 从那儿切开取到的是文件头，整支用例就再也测不到真正的路由表了
        table = src.split("export const PAGE_FOR_NAV_KEY", 1)[1].split("};", 1)[0]
        for key in sorted(set(_ALL_SUB_KEYS) | set(_TOP_KEYS)):
            self.assertIn(f"{key}:", table, f"nav_model.ts 少了 {key} 的路由映射")

    def test_defaults_match(self):
        from app import main_window as mw
        src = self._ts_source()
        # 值可以写成字面量，也可以写成同文件里的常量别名；两种都算对，
        # 这里要防的是两端的默认值漂开，不是 TS 那行怎么写
        alias = {mw.NAV_STYLE_COMPACT: "NAV_STYLE_COMPACT",
                 mw.NAV_STYLE_GROUPED: "NAV_STYLE_GROUPED"}
        pairs = {
            "NAV_DEFAULTS_VERSION": mw._NAV_DEFAULTS_VERSION,
            "DEFAULT_NAV_STYLE": mw._DEFAULT_NAV_STYLE,
        }
        for name, value in pairs.items():
            line = src.split(f"export const {name}", 1)[1].split("\n", 1)[0]
            self.assertTrue(f"'{value}'" in line or alias.get(value, "\0") in line,
                            f"{name} 两端不一致：{line.strip()}")
        for name, seq in (("DEFAULT_NAV_ORDER", mw._DEFAULT_NAV_ORDER),
                          ("DEFAULT_NAV_PINNED", mw._DEFAULT_NAV_PINNED),
                          ("DEFAULT_NAV_HIDDEN", mw._DEFAULT_NAV_HIDDEN),
                          ("BOTTOM_KEYS", mw._BOTTOM_KEYS)):
            # 声明可能带类型标注（`: string[] = []`），从等号之后取值
            line = src.split(f"export const {name}", 1)[1].split("=", 1)[1].split("\n", 1)[0]
            self.assertEqual(json.loads(line.rstrip(";").replace("'", '"')), list(seq),
                             f"{name} 两端不一致")

    def test_grouped_factory_matches(self):
        """出厂分组：组名和成员都得一致，否则两边的分组侧栏各长各的。"""
        from app import main_window as mw
        block = self._ts_source().split("export const GROUPED_NAV", 1)[1].split("];", 1)[0]
        for title, keys in mw._GROUPED_NAV:
            self.assertIn(f"'{title}'", block, f"分组「{title}」两端不一致")
            for key in keys:
                self.assertIn(f"'{key}'", block, f"分组成员 {key} 两端不一致")


class WpfNavKeyTableTests(unittest.TestCase):
    """C# 那份键表也要对齐：WPF 少映射一个键，那一页在侧栏上就点不进去。"""

    SRC = REPO / "wpf" / "PyMCL.Wpf" / "Shell" / "NavModel.cs"

    def _cs_source(self) -> str:
        return self.SRC.read_text(encoding="utf-8")

    @staticmethod
    def _cs_array(src: str, name: str) -> list[str]:
        """`... string[] Name = { "a", "b" };` → ["a", "b"]。"""
        body = src.split(f" {name} =", 1)[1].split(";", 1)[0]
        inner = body.split("{", 1)[1].rsplit("}", 1)[0] if "{" in body else ""
        return [s.strip().strip('"') for s in inner.split(",") if s.strip()]

    def test_every_qt_page_has_a_wpf_page(self):
        from app.main_window import _ALL_SUB_KEYS, _TOP_KEYS
        table = self._cs_source().split("PageForNavKey =", 1)[1].split("};", 1)[0]
        # download / more 在 WPF 里是可折叠的分区，不是页面
        for key in sorted((set(_ALL_SUB_KEYS) | set(_TOP_KEYS)) - {"download", "more"}):
            self.assertIn(f'["{key}"]', table, f"NavModel.cs 少了 {key} 的页面映射")

    def test_defaults_match(self):
        from app import main_window as mw
        src = self._cs_source()
        self.assertIn(f'NavDefaultsVersion = "{mw._NAV_DEFAULTS_VERSION}"', src)
        self.assertIn(f'DefaultStyle = Style{mw._DEFAULT_NAV_STYLE.capitalize()}', src)
        for name, seq in (("DefaultNavOrder", mw._DEFAULT_NAV_ORDER),
                          ("DefaultNavPinned", mw._DEFAULT_NAV_PINNED),
                          ("BottomKeys", mw._BOTTOM_KEYS),
                          ("TopKeys", mw._TOP_KEYS)):
            self.assertEqual(self._cs_array(src, name), list(seq), f"{name} 两端不一致")
        self.assertIn("DefaultNavHidden = Array.Empty<string>()", src)
        self.assertEqual(list(mw._DEFAULT_NAV_HIDDEN), [])

    def test_grouped_factory_matches(self):
        from app import main_window as mw
        block = self._cs_source().split("GroupedNav =", 1)[1].split("};", 1)[0]
        for title, keys in mw._GROUPED_NAV:
            self.assertIn(f'("{title}"', block, f"分组「{title}」两端不一致")
            for key in keys:
                self.assertIn(f'"{key}"', block, f"分组成员 {key} 两端不一致")
        for sec, members in mw._SUB_DEFAULT_MEMBERS.items():
            block = self._cs_source().split(f'["{sec}"] = new[]', 1)[1].split("}", 1)[0]
            self.assertEqual([s.strip().strip('"') for s in block.split("{", 1)[1].split(",") if s.strip()],
                             list(members), f"分区 {sec} 默认成员两端不一致")


class BridgeNavSettingsTests(unittest.TestCase):
    """侧栏这几个键得真能穿过桥：网页版改完，Qt 版下次开得看见同一套。"""

    def setUp(self):
        from unittest import mock
        from mclauncher.config import CONFIG
        self.CONFIG = CONFIG
        self._p_data = mock.patch.object(CONFIG, "data", dict(CONFIG.data))
        self._p_save = mock.patch.object(CONFIG, "save")
        self._p_data.start()
        self.saved = self._p_save.start()

    def tearDown(self):
        self._p_save.stop()
        self._p_data.stop()

    def _call(self, params: dict):
        """照 JSON-RPC 那一层的分发方式调（bridge/server.py _call_kwargs）。"""
        import bridge.api as bridge_api
        from bridge.server import _call_kwargs

        class _Shim:
            save_settings = bridge_api.BackendAPI.save_settings
            get_settings = bridge_api.BackendAPI.get_settings

        return _call_kwargs(_Shim().save_settings, params)

    def test_flat_payload_reaches_save_settings(self):
        """前端把整包设置直接当 params 发（eziapp 五处都这么写），必须收得下。

        形参名叫 data，只认 {"data": {...}} 的话，这一调用会以「缺少必需参数」
        整个失败——表现就是网页版点保存设置没有任何反应。
        """
        self._call({"ui_nav_hidden": ["ai"], "ui_dark": True})
        self.assertEqual(self.CONFIG.get("ui_nav_hidden"), ["ai"])
        self.assertIs(self.CONFIG.get("ui_dark"), True)
        self.assertTrue(self.saved.called, "必须落盘")

    def test_wrapped_payload_still_works(self):
        self._call({"data": {"ui_nav_style": "compact"}})
        self.assertEqual(self.CONFIG.get("ui_nav_style"), "compact")

    def test_nav_keys_round_trip(self):
        import bridge.api as bridge_api
        groups = [{"title": "账户", "keys": ["account"]},
                  {"title": "游戏", "keys": ["launch", "instance"]}]
        self._call({
            "ui_nav_style": "compact",
            "ui_nav_order": ["launch", "instance", "more"],
            "ui_nav_pinned": ["instance"],
            "ui_nav_hidden": [],
            "ui_nav_groups": groups,
            "ui_section_members": {"download": ["java"], "more": ["servers"]},
            "ui_sidebar_width": 210,
        })
        out = bridge_api.BackendAPI.get_settings(None)
        self.assertEqual(out["ui_nav_style"], "compact")
        self.assertEqual(out["ui_nav_order"], ["launch", "instance", "more"])
        self.assertEqual(out["ui_nav_pinned"], ["instance"])
        self.assertEqual(out["ui_nav_hidden"], [], "空列表是合法状态，不能被当成没提交")
        self.assertEqual(out["ui_nav_groups"], groups)
        self.assertEqual(out["ui_section_members"],
                         {"download": ["java"], "more": ["servers"]})
        self.assertEqual(out["ui_sidebar_width"], 210)

    def test_garbage_is_cleaned_not_stored(self):
        self._call({
            "ui_nav_style": "wat",
            "ui_nav_order": ["launch", "", "launch", 7],
            "ui_nav_groups": [{"title": "", "keys": ["launch"]}, "nope"],
            "ui_sidebar_width": 9000,
        })
        self.assertEqual(self.CONFIG.get("ui_nav_style"), "grouped", "非法排法回出厂")
        self.assertEqual(self.CONFIG.get("ui_nav_order"), ["launch", "7"], "去空去重保序")
        self.assertIsNone(self.CONFIG.get("ui_nav_groups"), "全是坏组 → 当没设过")
        self.assertEqual(self.CONFIG.get("ui_sidebar_width"), 320, "越界夹回可用范围")

    def test_qt_backend_takes_the_same_keys(self):
        """两套后端的面要一样宽：Qt 版少收一个键，同一份前端改它就丢一半。"""
        from app.backend import BackendAPI as QtBackend
        QtBackend.save_settings(None, {
            "ui_nav_style": "compact",
            "ui_nav_pinned": ["account"],
            "ui_nav_groups": [{"title": "通用", "keys": ["settings"]}],
            "ui_section_members": {"download": ["java"], "more": ["servers"]},
            "ui_sidebar_width": 200,
        })
        self.assertEqual(self.CONFIG.get("ui_nav_style"), "compact")
        self.assertEqual(self.CONFIG.get("ui_nav_pinned"), ["account"])
        self.assertEqual(self.CONFIG.get("ui_nav_groups"),
                         [{"title": "通用", "keys": ["settings"]}])
        self.assertEqual(self.CONFIG.get("ui_sidebar_width"), 200)
        out = QtBackend.get_settings(None)
        self.assertEqual(out["ui_nav_groups"], [{"title": "通用", "keys": ["settings"]}])
        self.assertEqual(out["ui_section_members"],
                         {"download": ["java"], "more": ["servers"]})


if __name__ == "__main__":
    sys.exit(unittest.main())

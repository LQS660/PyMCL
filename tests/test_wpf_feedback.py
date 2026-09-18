"""WPF 反馈页：常见问题 / 帮助库 + 启动后的反馈同意提示，对齐 Qt。

- 帮助库：WPF 不自己存文章，走桥上的 help_articles / help_article，两个方法都只是转给
  mclauncher/help_content.py。这里把「Qt 源码里的条数」「桥交给 WPF 的条数」「WPF 页面确实在调
  这两个 RPC」三段接起来，谁改了 Python 那边、谁把 C# 里的调用删了，这里都会红。
- 同意提示：Qt 是主窗口起来 400 ms 后弹一次（app/widgets.py prompt_feedback_consent），选过存
  config.json 的 feedback_consent，之后不再弹。WPF 的 Pages/FeedbackConsent.cs 照同一个键判；
  弹窗四句文案必须跟 Qt 一字不差地走 L()。状态机的真值表由 `PyMCL.Wpf.exe --consent-check`
  自己跑（exe 没编就跳过那一段，静态部分照常）。

跟 test_wpf_i18n.py 一样：不在这里替 WPF 编译。
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "wpf" / "PyMCL.Wpf"
HELP_PY = REPO / "mclauncher" / "help_content.py"
WIDGETS_PY = REPO / "app" / "widgets.py"
WPF_EXE = next(
    (p for p in (
        SRC / "bin" / "Debug" / "net8.0-windows" / "PyMCL.Wpf.exe",
        SRC / "bin" / "Release" / "net8.0-windows" / "PyMCL.Wpf.exe",
    ) if p.is_file()),
    None,
)


def _cs(rel: str) -> str:
    return (SRC / rel).read_text("utf-8")


def _cs_literal(py_text: str) -> str:
    """Python 字符串值 → C# 普通字面量里的写法（换行写成 \\n，引号转义）。"""
    return py_text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _qt_articles_from_source() -> list[dict]:
    """直接读 help_content.py 的 AST，把 ARTICLES 里每个 dict 的 id / title / body 取出来——不 import，跟安卓那份用例同一思路。"""
    tree = ast.parse(HELP_PY.read_text("utf-8"))
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        if target != "ARTICLES" or not isinstance(value, ast.List):
            continue
        rows = []
        for elt in value.elts:
            assert isinstance(elt, ast.Dict)
            row = {}
            for k, v in zip(elt.keys, elt.values):
                assert isinstance(k, ast.Constant) and isinstance(k.value, str)
                assert isinstance(v, ast.Constant) and isinstance(v.value, str), f"{k.value} 不是纯字符串常量"
                row[k.value] = v.value
            rows.append(row)
        return rows
    raise AssertionError("help_content.py 里找不到 ARTICLES")


def _qt_consent_strings() -> list[str]:
    """app/widgets.py prompt_feedback_consent 里 tr(...) 的四句：标题、正文、同意、暂不同意。"""
    tree = ast.parse(WIDGETS_PY.read_text("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "prompt_feedback_consent":
            out = []
            for call in ast.walk(node):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "tr" \
                        and call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                    out.append(call.args[0].value)
            return out
    raise AssertionError("app/widgets.py 里找不到 prompt_feedback_consent")


class HelpLibraryParityTests(unittest.TestCase):
    """常见问题条目：Qt 源码 = 桥交给 WPF 的 = WPF 页面在调的那两个方法。"""

    def test_qt_source_and_runtime_agree(self):
        from mclauncher import help_content as hc
        src = _qt_articles_from_source()
        self.assertGreater(len(src), 0)
        self.assertEqual([a["id"] for a in src], [a["id"] for a in hc.ARTICLES])
        self.assertEqual(len(src), len(hc.search_articles("")))
        for a in src:
            self.assertEqual({"id", "title", "body"}, set(a))
            self.assertEqual(a, hc.get_article(a["id"]))

    def test_bridge_hands_wpf_the_same_articles(self):
        """WPF 拿到的就是桥 help_articles("") 的返回；条数与 Qt 源码一致，按 id 取也一致。"""
        import bridge.api as bridge_api
        src = _qt_articles_from_source()
        rows = bridge_api.BackendAPI.help_articles(None, "")
        self.assertEqual(len(src), len(rows))
        self.assertEqual([a["id"] for a in src], [r["id"] for r in rows])
        for a in src:
            self.assertEqual(a, bridge_api.BackendAPI.help_article(None, a["id"]))
        self.assertEqual({}, bridge_api.BackendAPI.help_article(None, "no-such-article"))
        # 搜索口径同桌面：标题 + 正文子串，不分大小写
        self.assertEqual(["multiplayer"], [r["id"] for r in bridge_api.BackendAPI.help_articles(None, "陶瓦")])
        self.assertIn("java", [r["id"] for r in bridge_api.BackendAPI.help_articles(None, "JAVA")])

    def test_wpf_feedback_page_uses_both_bridge_methods(self):
        page = _cs("Pages/FeedbackPage.cs")
        self.assertIn('"help_articles"', page, "反馈页没再调 help_articles，帮助库就空了")
        self.assertIn('"help_article"', page, "反馈页没再调 help_article，点标题展开正文就没了")
        # 搜索框 + 空结果提示 + Qt 同一句说明（点击标题展开）
        for key in ("搜索帮助文章", "没有匹配的文章", "常见问题", "启动、Java、模组、账号、联机的快速说明（点击标题展开）"):
            self.assertIn(f'L("{key}")', page, f"反馈页缺 L(\"{key}\")")
        # 展开是原地展开，不再弹 Alert
        self.assertIn("ToggleArticleAsync", page)


class ConsentPromptTests(unittest.TestCase):
    """启动后的同意提示：接在首次运行向导之后，四句文案与 Qt 同源，状态存 feedback_consent。"""

    def test_wired_after_first_run_wizard_and_skipped_in_smoke(self):
        main = _cs("MainWindow.xaml.cs")
        wizard = main.index("FirstRunWizard.MaybeShowAsync()")
        consent = main.index("FeedbackConsent.MaybeAskAsync()")
        self.assertLess(wizard, consent, "同意提示得排在首次运行向导之后（Qt _boot_extras 的顺序）")
        line = next(ln for ln in main.split("\n") if "FeedbackConsent.MaybeAskAsync()" in ln)
        self.assertIn("!Smoke.Active", line, "冒烟模式下这是个等人点的框，必须跳过")

    def test_delay_and_state_key_match_qt(self):
        src = _cs("Pages/FeedbackConsent.cs")
        self.assertIn("DelayMs = 400", src)
        self.assertIn('Key = "feedback_consent"', src)
        self.assertIn("feedback_consent = ok", src, "选完得把 bool 写回 save_settings")
        self.assertIn('"save_settings"', src)
        self.assertIn('"get_settings"', src)

    def test_dialog_strings_are_qt_strings_wrapped_in_L(self):
        src = _cs("Pages/FeedbackConsent.cs")
        qt = _qt_consent_strings()
        self.assertEqual(4, len(qt), f"Qt 那边 tr() 的句子数变了：{qt}")
        for s in qt:
            self.assertIn(f'L("{_cs_literal(s)}")', src, f"WPF 同意弹窗缺这一句（或没包 L()）：{s[:30]!r}")
        # 同一批句子在两份词表里都得有，且 zh_CN 是恒等
        zh = json.loads((REPO / "mclauncher" / "locales" / "zh_CN.json").read_text("utf-8"))
        en = json.loads((REPO / "mclauncher" / "locales" / "en.json").read_text("utf-8"))
        for s in qt:
            self.assertEqual(s, zh.get(s), f"zh_CN 词表缺或改了：{s[:30]!r}")
            self.assertTrue(en.get(s), f"en 词表缺：{s[:30]!r}")

    def test_probe_is_wired(self):
        self.assertIn('"--consent-check"', _cs("App.xaml.cs"))
        self.assertIn("FeedbackConsent.SelfTest()", _cs("App.xaml.cs"))


@unittest.skipUnless(WPF_EXE and sys.platform == "win32", "WPF 没编过，跳过 exe 真值表")
class ConsentProbeTests(unittest.TestCase):
    """编好的 exe 自己把状态机真值表跑一遍：首次问、选过（同意 / 暂不同意）都不再问。"""

    @classmethod
    def setUpClass(cls):
        proc = subprocess.run(
            [str(WPF_EXE), "--consent-check"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(REPO), timeout=120,
        )
        if not proc.stdout.strip():
            raise AssertionError(f"--consent-check 没有输出：{proc.stderr[:500]}")
        cls.report = json.loads(proc.stdout)
        cls.returncode = proc.returncode

    def test_all_cases_pass(self):
        bad = [c for c in self.report["cases"] if not c["ok"]]
        self.assertEqual(0, self.report["failed"], bad)
        self.assertEqual(0, self.returncode)
        self.assertGreaterEqual(self.report["total"], 15)
        self.assertEqual(400, self.report["delay_ms"])

    def test_asks_once_then_never_again(self):
        trans = [c for c in self.report["cases"] if c["kind"] == "transition"]
        self.assertEqual({True, False}, {c["choice"] for c in trans}, "同意 / 暂不同意两条路都要覆盖")
        for c in trans:
            self.assertTrue(c["first_launch_asks"], c)
            self.assertFalse(c["second_launch_asks"], c)


if __name__ == "__main__":
    sys.exit(unittest.main())

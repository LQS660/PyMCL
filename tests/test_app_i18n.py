# -*- coding: utf-8 -*-
"""app/ 的 i18n key 覆盖门禁（把 WPF 的 Shell/I18nCheck.cs 语义移植到 Qt 侧）。

缺陷背景（审计 2026-09-28 P1-1 / P1-3 / P3-3）：
  · `app/` 有 1100+ 个 `tr()` key，但门禁只有 `tests/test_ui_text_wrapped.py`，
    且只扫 `servers_page.py` 一个文件、只查 InfoBar 两处参数；
  · 于是「`tr()` 用了词表里没有的 key」这类缺陷在 app/ 里结构上不可能被发现：
    实测曾同时有 89 个 key 不在 `zh_CN.json`、73 个不在 `en.json`（其中 68 个两边都没有）；
  · `i18n.py:91-104` 让 zh_CN 与 en 互不回退，缺哪边就在哪边露出原文/英文。

规则（与 tests/test_bridge_i18n.py 的 key 侧、tests/test_wpf_i18n.py 同口径）：
  扫 `app/**/*.py` 里所有 `tr("…")` / `_("…")` 的字面量参数（AST，不吃注释与
  f-string），含 CJK 的必须**同时**在 zh_CN.json 与 en.json 里有条目。
  动态参数（`tr(表[key])`）不是字面量，本用例不追——那是 _TOOL_TITLES 这类
  模块级表的责任，另有 test_indirect_table_keys_are_in_both_tables 覆盖已知表。
"""
from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
LOCALES = ROOT / "mclauncher" / "locales"

CJK = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]")
TR_NAMES = ("tr", "_", "translate")

# 已知的模块级「文案表」：值经 tr() 取词，等于隐式 key。这些表里的 CJK 值也要在词表里。
INDIRECT_TABLES = {
    "pages/ai_page.py": ["_TOOL_TITLES"],
    "main_window.py": ["_SUB_TITLES", "NAV_STYLE_LABELS", "_GROUPED_LABELS"],
    "file_kinds.py": ["KIND_LABELS", "KIND_ACTIONS"],
    "pages/tasks_page.py": ["_TASK_ICONS"],
}


def _load(lang: str) -> dict[str, str]:
    return json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))


def _literal_tr_keys() -> dict[str, list[str]]:
    """{key: ["app/xxx.py:12", ...]} —— 只收字面量参数，含 CJK 的。"""
    hits: dict[str, list[str]] = {}
    for p in sorted(APP.rglob("*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"), filename=str(p))
        except SyntaxError:
            continue
        rel = p.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name not in TR_NAMES:
                continue
            a0 = node.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str) and CJK.search(a0.value):
                hits.setdefault(a0.value, []).append(f"{rel}:{node.lineno}")
    return hits


class AppI18nCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hits = _literal_tr_keys()
        cls.zh = _load("zh_CN")
        cls.en = _load("en")

    def test_scanner_is_alive(self):
        """扫到的 key 太少就是扫描器坏了，不是代码干净。"""
        self.assertGreater(len(self.hits), 800, f"app/ 只扫到 {len(self.hits)} 个 tr() key")

    def test_every_app_tr_key_is_in_zh_cn(self):
        missing = sorted(k for k in self.hits if k not in self.zh)
        detail = "\n".join(f"  {k!r}  <- {self.hits[k][:2]}" for k in missing[:40])
        self.assertEqual(
            missing, [],
            f"app/ 有 {len(missing)} 个 tr() key 不在 zh_CN.json 里（中文界面回落成 key 本身）：\n{detail}")

    def test_every_app_tr_key_is_in_en(self):
        missing = sorted(k for k in self.hits if k not in self.en)
        detail = "\n".join(f"  {k!r}  <- {self.hits[k][:2]}" for k in missing[:40])
        self.assertEqual(
            missing, [],
            f"app/ 有 {len(missing)} 个 tr() key 不在 en.json 里（英文界面冒中文）：\n{detail}")

    def test_en_values_are_not_identity_for_cjk_keys(self):
        """en.json 的值不许等于含中文的 key —— 那等于没翻。"""
        bad = sorted(k for k in self.hits if k in self.en and self.en[k] == k and CJK.search(k))
        self.assertEqual(bad, [], f"en.json 里这些 key 的值就是原文，等于没翻：{bad[:20]}")

    def test_indirect_table_keys_are_in_both_tables(self):
        """模块级文案表的值也进 tr()，同样得在两边词表里。"""
        bad: list[str] = []
        seen = 0
        for rel, names in INDIRECT_TABLES.items():
            p = APP / rel
            if not p.is_file():
                continue
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"), filename=str(p))
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                for tgt in node.targets:
                    if not (isinstance(tgt, ast.Name) and tgt.id in names):
                        continue
                    for sub in ast.walk(node.value):
                        if (isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                                and CJK.search(sub.value)):
                            seen += 1
                            if sub.value not in self.zh or sub.value not in self.en:
                                bad.append(f"{rel} {tgt.id}: {sub.value!r}")
        self.assertGreater(seen, 20, f"只解析到 {seen} 个文案表条目，扫描器多半坏了")
        self.assertEqual(bad, [], f"这些文案表条目缺词表条目：{bad[:20]}")


if __name__ == "__main__":
    unittest.main()

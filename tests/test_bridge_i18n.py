# -*- coding: utf-8 -*-
"""桥端多语言护栏：bridge/api.py 里面向用户的中文必须走 tr()。

桥进程一旦切到 en（server.py `_init_language` / api.set_language），前端界面自己的词翻了，
桥吐回去的数据也得是英文——否则 WPF / eziapp / WinUI 三端英文界面上照样混着中文。

规则（改这里要连交付说明一起改）：
  · 扫 bridge/api.py 全部字符串字面量：普通字符串、隐式拼接、f-string；含 CJK（含全角标点）的才看。
  · 「已包裹」= 字面量在 `tr(` 的括号里（隐式拼接的几段都算）。
  · 自动放过的四类，不算面向用户：
      1. 文档字符串（模块 / 类 / 函数 docstring）；
      2. `log(...)` / `self._log(...)` 调用里的：任务日志按原文写，不翻；
      3. `self.start_task(...)` 的实参：任务标题按原文拼，WPF / WinUI 按原文前缀比对
         （见 BackendAPI.is_download_title 的说明），所以标题不翻；
      4. 所在行带 `# i18n:ignore` 的：协议值 / 当键比对用的原文，注释里写理由。
  · 其余含中文而没包 tr() 的 = 漏翻，本用例逐条报出位置，数量必须为 0。
另外每一个 tr("…") 的 key 在 en 词表里都得有非空译文——缺了英文界面上桥吐回来的还是中文。
"""
from __future__ import annotations

import ast
import io
import json
import re
import tokenize
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = ROOT / "bridge" / "api.py"
EN = ROOT / "mclauncher" / "locales" / "en.json"

CJK = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]")
MARK = "i18n:ignore"
SKIP_CALLS = ("log", "_log", "start_task")
INSIGNIFICANT = {tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT}
FSTRING_START = getattr(tokenize, "FSTRING_START", None)
FSTRING_MIDDLE = getattr(tokenize, "FSTRING_MIDDLE", None)
FSTRING_END = getattr(tokenize, "FSTRING_END", None)


def _docstring_lines(src: str) -> set[int]:
    """模块 / 类 / 函数 docstring 覆盖的行号。"""
    lines: set[int] = set()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def scan(src: str):
    """返回 (漏翻列表, tr 的 key 列表)。漏翻元素 = (行号, 片段)。"""
    lines = src.splitlines()
    doc_lines = _docstring_lines(src)
    toks = list(tokenize.generate_tokens(io.StringIO(src).readline))

    unwrapped: list[tuple[int, str]] = []
    tr_keys: list[str] = []

    # 括号栈：每一层记「这是谁的括号」——tr / log / start_task / 其它
    stack: list[str] = []
    pending_tr: list[str] = []  # 当前 tr(...) 里收集到的字面量片段（隐式拼接会有多段）

    def prev_name(i: int) -> str:
        j = i - 1
        while j >= 0 and toks[j].type in INSIGNIFICANT:
            j -= 1
        return toks[j].string if j >= 0 and toks[j].type == tokenize.NAME else ""

    def in_ctx(name: str) -> bool:
        return name in stack

    def note_literal(lineno: int, text: str, cjk: bool, raw: str | None):
        if in_ctx("tr"):
            if raw is not None and stack and stack[-1] == "tr":
                pending_tr.append(raw)
            return
        if not cjk:
            return
        if lineno in doc_lines:
            return
        if any(in_ctx(c) for c in SKIP_CALLS):
            return
        if MARK in lines[lineno - 1]:
            return
        unwrapped.append((lineno, lines[lineno - 1].strip()[:140]))

    i = 0
    while i < len(toks):
        t = toks[i]
        if t.type == tokenize.OP and t.string in "([{":
            owner = prev_name(i) if t.string == "(" else ""
            stack.append(owner if owner in SKIP_CALLS or owner == "tr" else "")
            if owner == "tr":
                pending_tr.clear()
        elif t.type == tokenize.OP and t.string in ")]}":
            owner = stack.pop() if stack else ""
            if owner == "tr" and pending_tr:
                try:
                    key = ast.literal_eval(" ".join(pending_tr))
                except Exception:  # noqa: BLE001
                    key = None
                if isinstance(key, str):
                    tr_keys.append(key)
                pending_tr.clear()
        elif t.type == tokenize.STRING:
            note_literal(t.start[0], t.string, bool(CJK.search(t.string)), t.string)
        elif FSTRING_START is not None and t.type == FSTRING_START:
            # 整个 f-string 当一个字面量看；{} 里嵌的表达式照常往下走
            depth = 0
            j = i
            has_cjk = False
            while j < len(toks):
                tj = toks[j]
                if tj.type == FSTRING_START:
                    depth += 1
                elif tj.type == FSTRING_END:
                    depth -= 1
                    if depth == 0:
                        break
                elif tj.type == FSTRING_MIDDLE and CJK.search(tj.string):
                    has_cjk = True
                j += 1
            note_literal(t.start[0], "f-string", has_cjk, None)
            # f-string 不能当 tr 的 key（里面有表达式），tr(f"…") 这种写法本身就是错的
            if in_ctx("tr") and stack and stack[-1] == "tr" and has_cjk:
                unwrapped.append((t.start[0], "tr(f\"…\")：f-string 不能当词表 key，应写 tr(\"…{0}\").format(...)"))
            i = j + 1
            continue
        i += 1
    return unwrapped, tr_keys


class BridgeI18nGuardTests(unittest.TestCase):
    def setUp(self):
        self.src = API.read_text("utf-8")

    def test_no_unwrapped_user_facing_chinese(self):
        unwrapped, _ = scan(self.src)
        detail = "\n".join(f"  bridge/api.py:{ln}: {snippet}" for ln, snippet in unwrapped)
        self.assertEqual(
            [], unwrapped,
            f"bridge/api.py 有 {len(unwrapped)} 处面向用户的中文没包 tr()（协议值请加 # i18n:ignore 并注明理由）：\n{detail}",
        )

    def test_every_tr_key_has_english(self):
        _, keys = scan(self.src)
        self.assertGreater(len(keys), 50, "tr() 的 key 太少，扫描器多半坏了")
        en = json.loads(EN.read_text("utf-8"))
        missing = sorted({k for k in keys if not str(en.get(k) or "").strip()})
        self.assertEqual([], missing, f"这些 bridge/api.py 的 tr() key 在 mclauncher/locales/en.json 里没有英文：{missing}")

    def test_scanner_rules_hold_on_samples(self):
        """扫描器自己的真值表：四类放过、两类必须包。"""
        sample = '\n'.join([
            '"""模块说明：中文 docstring 不算。"""',
            'from mclauncher.i18n import tr',
            'def f(log, self):',
            '    """函数 docstring 也不算。"""',
            '    log(f"安装到 {self}")',
            '    self._log("已导入账号: " + "、".join([]))',
            '    self.start_task(f"启动游戏 {self}", None)',
            '    self.start_task(',
            '        "导入官方启动器",',
            '        None)',
            '    x = "已取消"  # i18n:ignore 协议值',
            '    a = tr("已备份到 {0}").format(1)',
            '    b = tr("第一段，"',
            '           "第二段。")',
            '    bad = f"账号不存在: {self}"',
            '    bad2 = "未知动作"',
            '    return a, b, bad, bad2, x',
        ])
        unwrapped, keys = scan(sample)
        self.assertEqual([15, 16], [ln for ln, _ in unwrapped], unwrapped)
        self.assertEqual(["已备份到 {0}", "第一段，第二段。"], keys)


class BridgeLanguageBehaviourTests(unittest.TestCase):
    """切到 en 之后桥的几处「原文 / 译文都认」的比对要立得住。"""

    def test_offline_account_sentinel_accepts_both_texts(self):
        from mclauncher import i18n
        import bridge.api as bridge_api

        api = bridge_api.BackendAPI
        saved = i18n.current_language()
        try:
            i18n._current_lang = "en"
            self.assertTrue(api._is_offline_account(""))
            self.assertTrue(api._is_offline_account("离线模式"))
            self.assertTrue(api._is_offline_account(i18n.tr("离线模式")))
            self.assertNotEqual("离线模式", i18n.tr("离线模式"), "en 词表里得有「离线模式」")
            self.assertFalse(api._is_offline_account("Steve"))
            # 任务标题按原文拼；原文和译文前缀都不算下载任务
            self.assertFalse(api.is_download_title("启动游戏 1.21"))
            self.assertFalse(api.is_download_title(i18n.tr("启动游戏") + " 1.21"))
            self.assertTrue(api.is_download_title("安装游戏 1.21"))
        finally:
            i18n._current_lang = saved


if __name__ == "__main__":
    unittest.main()

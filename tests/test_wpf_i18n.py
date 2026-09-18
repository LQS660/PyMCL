"""WPF 界面多语言：硬编码中文全部走 L()，词表与 Qt 同源。

WPF 端的界面文案通过 wpf/PyMCL.Wpf/Services/I18n.cs 的 L("中文") 取词，词表就是
mclauncher/locales/<lang>.json（key 是中文原文，语义同 mclauncher.i18n 的 _()）。
这里守三件事：

1. 源码里不再有没包 L() 的中文字面量（静态扫描 .cs，规则与 Shell/I18nCheck.cs 逐条一致）；
2. L() 用到的每个 key 都在 zh_CN 词表里，en 也一个不缺，占位符两边对得上；
3. 编好的 PyMCL.Wpf.exe --i18n-check 自己也报 0（exe 没编就跳过这一段，静态部分照常跑）。

跟 test_nav_parity.py 一样：不在这里替 WPF 编译。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "wpf" / "PyMCL.Wpf"
LOCALES = REPO / "mclauncher" / "locales"
WPF_EXE = next(
    (p for p in (
        SRC / "bin" / "Debug" / "net8.0-windows" / "PyMCL.Wpf.exe",
        SRC / "bin" / "Release" / "net8.0-windows" / "PyMCL.Wpf.exe",
    ) if p.is_file()),
    None,
)

_CJK = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\uff00-\uffef]")


def has_cjk(s: str) -> bool:
    return bool(_CJK.search(s))


# ---------------------------------------------------------------------------
# 词法扫描：与 Shell/I18nCheck.cs 同一套规则（改一处要改两处）
# ---------------------------------------------------------------------------
class Literal:
    __slots__ = ("file", "line", "value", "wrapped", "ignored")

    def __init__(self, file: str, line: int, value: str, wrapped: bool, ignored: bool):
        self.file, self.line, self.value, self.wrapped, self.ignored = file, line, value, wrapped, ignored


def _is_wrapped(s: str, start: int) -> bool:
    """字面量前面（跳过空白）恰好是 `L(`，且 L 前面不是标识符字符（`.` 除外）。"""
    i = start - 1
    while i >= 0 and s[i].isspace():
        i -= 1
    if i < 0 or s[i] != "(":
        return False
    i -= 1
    while i >= 0 and s[i].isspace():
        i -= 1
    if i < 0 or s[i] != "L":
        return False
    if i == 0:
        return True
    p = s[i - 1]
    return not (p.isalnum() or p == "_") or p == "."


def _unescape(s: str, i: int, out: list[str]) -> int:
    e = s[i + 1]
    simple = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
    if e in simple:
        out.append(simple[e])
        return i + 2
    if e == "u" and i + 6 <= len(s):
        try:
            out.append(chr(int(s[i + 2:i + 6], 16)))
            return i + 6
        except ValueError:
            pass
    if e == "U" and i + 10 <= len(s):
        try:
            out.append(chr(int(s[i + 2:i + 10], 16)))
            return i + 10
        except ValueError:
            pass
    if e == "x":
        j = i + 2
        while j < len(s) and j - (i + 2) < 4 and s[j] in "0123456789abcdefABCDEF":
            j += 1
        if j > i + 2:
            out.append(chr(int(s[i + 2:j], 16)))
            return j
    out.append(e)  # \' \" \\ 以及不认识的：照抄
    return i + 2


def scan_cs(text: str) -> list[Literal]:
    """把一份 C# 源码里含中文的字符串字面量全部找出来。"""
    lines = text.split("\n")
    starts: list[int] = []
    pos = 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln) + 1

    def line_of(offset: int) -> int:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo

    result: list[Literal] = []

    def emit(start: int, value: str) -> None:
        if not has_cjk(value):
            return
        ln = line_of(start)
        result.append(Literal("", ln + 1, value, _is_wrapped(text, start), "i18n:ignore" in lines[ln]))

    def scan_code(i: int, end: int, stop_at_brace: bool) -> int:
        depth = 0
        while i < end:
            c = text[i]
            if c == "/" and i + 1 < end and text[i + 1] == "/":
                while i < end and text[i] != "\n":
                    i += 1
                continue
            if c == "/" and i + 1 < end and text[i + 1] == "*":
                close = text.find("*/", i + 2)
                i = end if close < 0 else close + 2
                continue
            if c == "'":
                i += 1
                while i < end and text[i] != "'":
                    if text[i] == "\\":
                        i += 1
                    i += 1
                i += 1
                continue
            is_str = c == '"' \
                or (c == "@" and i + 1 < end and (text[i + 1] == '"' or (text[i + 1] == "$" and i + 2 < end and text[i + 2] == '"'))) \
                or (c == "$" and i + 1 < end and (text[i + 1] == '"' or (text[i + 1] == "@" and i + 2 < end and text[i + 2] == '"')))
            if is_str:
                i = scan_string(i, end)
                continue
            if stop_at_brace:
                if c in "{([":
                    depth += 1
                elif c in ")]":
                    depth -= 1
                elif c == "}":
                    if depth == 0:
                        return i
                    depth -= 1
            i += 1
        return i

    def scan_string(start: int, end: int) -> int:
        i = start
        verbatim = interpolated = False
        while i < end and text[i] in "@$":
            if text[i] == "@":
                verbatim = True
            else:
                interpolated = True
            i += 1
        if i + 2 < end and text[i] == '"' and text[i + 1] == '"' and text[i + 2] == '"':
            q = i
            while q < end and text[q] == '"':
                q += 1
            quotes = q - i
            close = text.find('"' * quotes, q)
            if close < 0:
                close = end
            raw = text[q:close]
            if interpolated:
                raw = raw.replace("{{", "{").replace("}}", "}")
            emit(start, raw.strip("\r\n "))
            return min(end, close + quotes)
        i += 1
        out: list[str] = []
        while i < end:
            c = text[i]
            if c == '"':
                if verbatim and i + 1 < end and text[i + 1] == '"':
                    out.append('"')
                    i += 2
                    continue
                i += 1
                break
            if not verbatim and c == "\\" and i + 1 < end:
                i = _unescape(text, i, out)
                continue
            if interpolated and c == "{":
                if i + 1 < end and text[i + 1] == "{":
                    out.append("{")
                    i += 2
                    continue
                stop = scan_code(i + 1, end, True)
                out.append("{}")
                i = min(end, stop + 1)
                continue
            if interpolated and c == "}" and i + 1 < end and text[i + 1] == "}":
                out.append("}")
                i += 2
                continue
            out.append(c)
            i += 1
        emit(start, "".join(out))
        return i

    scan_code(0, len(text), False)
    return result


def _file_ignored(text: str) -> bool:
    return any("i18n:ignore-file" in ln for ln in text.split("\n")[:10])


def cs_files() -> list[Path]:
    return sorted(
        p for p in SRC.rglob("*.cs")
        if "obj" not in p.relative_to(SRC).parts and "bin" not in p.relative_to(SRC).parts
    )


def scan_tree() -> tuple[list[Literal], list[str]]:
    literals: list[Literal] = []
    ignored_files: list[str] = []
    for f in cs_files():
        rel = f.relative_to(SRC).as_posix()
        text = f.read_text("utf-8")
        if _file_ignored(text):
            ignored_files.append(rel)
            continue
        for lit in scan_cs(text):
            lit.file = rel
            literals.append(lit)
    return literals, ignored_files


def _load(lang: str) -> dict[str, str]:
    return json.loads((LOCALES / f"{lang}.json").read_text("utf-8"))


def _placeholders(s: str) -> list[str]:
    return sorted(re.findall(r"\{(\d+)[^}]*\}", s))


class WpfI18nStaticTests(unittest.TestCase):
    """不需要编译：直接扫源码与词表。"""

    @classmethod
    def setUpClass(cls):
        cls.literals, cls.ignored_files = scan_tree()
        cls.keys = sorted({l.value for l in cls.literals if l.wrapped})
        cls.zh = _load("zh_CN")
        cls.en = _load("en")

    def test_scanner_sees_the_wrapped_literals(self):
        """扫描器本身得是活的：WPF 有上千处 L()，扫出来是 0 就是扫描器坏了，不是代码干净。"""
        self.assertGreater(len(self.keys), 500, "扫到的 L() key 少得不像话，扫描器多半坏了")

    def test_no_unwrapped_chinese_literal(self):
        bad = [l for l in self.literals if not l.wrapped and not l.ignored]
        detail = "\n".join(f"  {l.file}:{l.line}  {l.value[:60]!r}" for l in bad[:40])
        self.assertEqual(len(bad), 0, f"还有 {len(bad)} 处中文字面量没包 L()：\n{detail}")

    def test_ignore_file_marker_is_only_for_dev_probes(self):
        """整文件忽略只允许给开发探针用，别被人拿去偷懒。"""
        allowed = {"Shell/Smoke.cs", "Shell/I18nCheck.cs", "Services/ImeGuard.cs"}
        self.assertTrue(set(self.ignored_files) <= allowed,
                        f"这些文件不该整文件忽略：{sorted(set(self.ignored_files) - allowed)}")

    def test_every_key_is_in_zh_cn(self):
        missing = [k for k in self.keys if k not in self.zh]
        self.assertEqual(missing, [], f"zh_CN 词表缺 {len(missing)} 个 key：{missing[:20]}")

    def test_every_key_is_in_en(self):
        missing = [k for k in self.keys if not self.en.get(k)]
        self.assertEqual(missing, [], f"en 词表缺 {len(missing)} 个 key：{missing[:20]}")

    def test_zh_cn_is_identity_for_wpf_keys(self):
        """跟 Qt 那 1037 条一样：zh_CN 里 key 就是值，中文界面永远显示原文。"""
        odd = [k for k in self.keys if k in self.zh and self.zh[k] != k]
        self.assertEqual(odd, [], f"zh_CN 里这些 key 的值不是原文：{odd[:10]}")

    def test_en_placeholders_match(self):
        """{0} {1} 两边得一样，否则 string.Format 在英文界面上直接抛。"""
        bad = [(k, self.en[k]) for k in self.keys if k in self.en and _placeholders(k) != _placeholders(self.en[k])]
        self.assertEqual(bad, [], f"占位符不一致：{bad[:10]}")

    def test_en_keeps_file_filter_shape(self):
        """Win32 文件对话框的 filter 是 `说明|通配|说明|通配`，竖线数目变了对话框直接报错。"""
        bad = [k for k in self.keys if "|" in k and k in self.en and k.count("|") != self.en[k].count("|")]
        self.assertEqual(bad, [], f"过滤器竖线数目不一致：{bad}")

    def test_xaml_has_no_hardcoded_chinese(self):
        """XAML 里写死的中文绕开了 L()，这几处已经挪进 MainWindow 构造，别再长回来。"""
        bad = []
        for f in sorted(SRC.rglob("*.xaml")):
            if "obj" in f.parts or "bin" in f.parts:
                continue
            for n, ln in enumerate(f.read_text("utf-8").split("\n"), 1):
                if has_cjk(ln) and "<!--" not in ln:
                    bad.append(f"{f.relative_to(SRC).as_posix()}:{n}")
        self.assertEqual(bad, [], f"XAML 里还有中文：{bad}")

    def test_locales_stay_in_sync_for_wpf_keys(self):
        """zh_CN 与 en 对 WPF 用到的 key 得同时有：只补一边，另一种语言就冒出中文。"""
        only_zh = [k for k in self.keys if k in self.zh and k not in self.en]
        only_en = [k for k in self.keys if k in self.en and k not in self.zh]
        self.assertEqual((only_zh, only_en), ([], []))


@unittest.skipUnless(WPF_EXE and sys.platform == "win32", "WPF 没编过，跳过 exe 自检对照")
class WpfI18nProbeTests(unittest.TestCase):
    """编好的 exe 自己也得报 0，且跟这里的 Python 扫描数出同一批东西。"""

    @classmethod
    def setUpClass(cls):
        proc = subprocess.run(
            [str(WPF_EXE), "--i18n-check", "--json"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(REPO), timeout=120,
        )
        if not proc.stdout.strip():
            raise AssertionError(f"--i18n-check 没有输出：{proc.stderr[:500]}")
        cls.report = json.loads(proc.stdout)
        cls.returncode = proc.returncode

    def test_probe_reports_zero_unwrapped(self):
        self.assertEqual(self.report["unwrapped_count"], 0, self.report["unwrapped"][:20])

    def test_probe_reports_no_missing_en(self):
        self.assertEqual(self.report["missing_en_count"], 0, self.report["missing_en"][:20])
        self.assertEqual(self.report["missing_zh_count"], 0, self.report["missing_zh"][:20])

    def test_probe_exit_code_is_zero(self):
        self.assertEqual(self.returncode, 0)

    def test_probe_and_python_scanner_agree(self):
        """两套扫描器（C# / Python）对同一棵树得数出同样的 key 数与包裹数，谁漂了都要露出来。"""
        literals, _ = scan_tree()
        wrapped = sum(1 for l in literals if l.wrapped)
        keys = len({l.value for l in literals if l.wrapped})
        self.assertEqual((wrapped, keys), (self.report["wrapped"], self.report["keys"]))


if __name__ == "__main__":
    sys.exit(unittest.main())

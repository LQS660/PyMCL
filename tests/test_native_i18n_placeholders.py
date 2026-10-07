# -*- coding: utf-8 -*-
"""C 桥 i18n 的命名占位符（`{name}`）支持与隐式契约门禁。

缺陷背景（审计 2026-09-28 P3-1）：
  · `mclauncher/locales/*.json` 里有 29 条 key 用 `{name}` 命名占位符
    （`启动 {version} @ {inst}`、`安装模组 {name} → {inst}` …），Python 侧走
    `str.format(**fields)` 没问题；
  · C 侧 `native/src/i18n.c` 的 `tr_fmt0` 只 `strstr(t, "{0}")`，`rpc_tasks2.c`
    的 `tr_fmt2` 只认 `{0}`/`{1}` —— 照抄一条命名式的 key 过去就会原样吐出
    `{name}` 给用户看；
  · 当前 C 侧 53 个 key 里 0 个用命名式，所以是**隐式契约**，没有测试守着。

本用例守三件事（前两件是纯静态，不需要编译器）：
  1. 隐式契约：`native/src/**/*.c` 里的 `tr()` key 不得含 `{name}` 式占位符
     （真要用，就得改用 tr_fmt_named 并在这里同时加白名单）；
  2. 占位符风格一致：`{0}` 式的 key 在 zh_CN 与 en 两边占位符集合必须相同
     （C 侧 tr_fmt0 按 key 取词再替换，两边不一致就会错位）；
  3. 编译 + 真跑 `tr_fmt_named`（有 gcc 才跑）：命名替换、未给的占位符原样保留、
     非占位符的 `{` 不被吃掉、缓冲区截断不切半个 UTF-8 字符。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"
LOCALES = ROOT / "mclauncher" / "locales"

CJK = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")
# native/src 里的 tr() / tr_lang() 调用（含 tr_fmt0/tr_fmt2 的 key 实参）
TR_CALL = re.compile(r"""\btr(?:_lang|_fmt0|_fmt2)?\s*\(\s*"((?:\\.|[^"\\])*)\"""", re.S)
NAMED_PH = re.compile(r"\{[a-zA-Z_]\w*\}")
NUM_PH = re.compile(r"\{\d+\}")

# tr_fmt_named 的调用点白名单：目前没有调用方（C 侧还没有命名式的 key），
# 一旦有人用起来，把它加进来并说明理由。
NAMED_CALL_ALLOWED: set[str] = set()


def _load(lang: str) -> dict[str, str]:
    return json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))


def _c_tr_keys() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for p in sorted(NATIVE.glob("src/**/*.c")) + sorted(NATIVE.glob("src/**/*.h")):
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(ROOT).as_posix()
        for m in TR_CALL.finditer(text):
            val = m.group(1)
            if CJK.search(val):
                hits.setdefault(val, []).append(f"{rel}:{text[: m.start()].count(chr(10)) + 1}")
    return hits


class NativeI18nContractTests(unittest.TestCase):
    """不需要编译器：纯静态契约。"""

    @classmethod
    def setUpClass(cls):
        cls.c_keys = _c_tr_keys()
        cls.zh = _load("zh_CN")
        cls.en = _load("en")

    def test_c_side_scanner_is_alive(self):
        self.assertGreater(len(self.c_keys), 30, f"native/ 只扫到 {len(self.c_keys)} 个 tr() key")

    def test_no_named_placeholder_in_c_tr_keys(self):
        """C 侧 tr() 的 key 不许用 `{name}` 式 —— tr_fmt0 只认 {0}，会原样吐出去。

        要用命名式就得改走 tr_fmt_named（native/src/i18n.c）并在
        NAMED_CALL_ALLOWED 里登记调用点。
        """
        bad = sorted(k for k in self.c_keys if NAMED_PH.search(k))
        detail = "\n".join(f"  {k!r}  <- {self.c_keys[k][:2]}" for k in bad)
        self.assertEqual(
            bad, [],
            f"native/ 有 {len(bad)} 个 tr() key 用 {{name}} 命名占位符，"
            f"tr_fmt0 填不了（改用 tr_fmt_named）：\n{detail}")

    def test_native_keys_are_in_both_tables(self):
        """C 桥是三端后端，key 缺哪边哪边就露原文。"""
        miss_zh = sorted(k for k in self.c_keys if k not in self.zh)
        miss_en = sorted(k for k in self.c_keys if k not in self.en)
        self.assertEqual(miss_zh, [], f"native/ 的 tr() key 不在 zh_CN.json：{miss_zh}")
        self.assertEqual(miss_en, [], f"native/ 的 tr() key 不在 en.json：{miss_en}")

    def test_numeric_placeholders_match_between_tables(self):
        """tr_fmt0 先按 key 取词再替换 {0}：两边占位符集合不一致就会错位/丢参。"""
        bad = []
        for k in sorted(self.c_keys):
            if k in self.zh and k in self.en:
                a = set(NUM_PH.findall(self.zh[k]))
                b = set(NUM_PH.findall(self.en[k]))
                if a != b:
                    bad.append((k, sorted(a), sorted(b)))
        self.assertEqual(bad, [], f"native/ 用到的 key 在两边占位符不一致：{bad[:10]}")

    def test_named_formatter_is_declared(self):
        """头文件得声明 tr_fmt_named，否则 C 侧无从调用。"""
        header = (NATIVE / "include" / "pymcl.h").read_text(encoding="utf-8")
        self.assertIn("tr_fmt_named", header)
        impl = (NATIVE / "src" / "i18n.c").read_text(encoding="utf-8")
        self.assertIn("int tr_fmt_named(", impl)


def _find_gcc() -> str | None:
    gcc = shutil.which("gcc")
    if gcc:
        return gcc
    for cand in (r"C:\msys64\mingw64\bin\gcc.exe", r"C:\msys64\ucrt64\bin\gcc.exe"):
        if Path(cand).is_file():
            return cand
    return None


HARNESS = r'''
#include "pymcl.h"
#include <stdio.h>

static int fails = 0;
static void eq(const char *what, const char *got, const char *want) {
    if (strcmp(got, want) != 0) { fails++; printf("FAIL %s\n  got  %s\n  want %s\n", what, got, want); }
    else printf("ok   %s -> %s\n", what, got);
}

int main(int argc, char **argv) {
    if (argc < 2) { printf("need root\n"); return 2; }
    pymcl_set_root(argv[1]);
    i18n_set_language("zh_CN");

    char out[512];
    const char *n1[] = {"inst"};
    const char *v1[] = {"saves-world"};

    /* 1. 单命名占位符 */
    tr_fmt_named(out, sizeof(out), "实例：{name}", (const char*[]){"name"}, (const char*[]){"MyInst"}, 1);
    eq("single {name}", out, "实例：MyInst");

    /* 2. 多个命名占位符 */
    const char *n2[] = {"version", "inst"};
    const char *v2[] = {"1.20.1", "Default"};
    tr_fmt_named(out, sizeof(out), "启动 {version} @ {inst}", n2, v2, 2);
    eq("two named", out, "启动 1.20.1 @ Default");

    /* 3. 调用方没给这个占位符：原样保留，不许吃掉或填空 */
    tr_fmt_named(out, sizeof(out), "启动 {version} @ {inst}", n1, v1, 1);
    eq("missing value kept", out, "启动 {version} @ saves-world");

    /* 4. 不是占位符的 { 原样输出（含 {0} 这种数字式） */
    tr_fmt_named(out, sizeof(out), "已备份到 {0}", n1, v1, 1);
    eq("numeric untouched", out, "已备份到 {0}");

    /* 5. 非法名字（空 / 未闭合）不当作占位符 */
    tr_fmt_named(out, sizeof(out), "a{}b", n1, v1, 1);
    eq("empty braces", out, "a{}b");
    tr_fmt_named(out, sizeof(out), "a{no close", n1, v1, 1);
    eq("unclosed brace", out, "a{no close");

    /* 6. 缓冲区截断：只写完整 UTF-8 字符，不越界、不出半个字、以 0 结尾。
          "启动 {version} @ {inst}" + 1.20.1 → "启动 1.20.1 @ Default"
          tiny[6]  放得下 5 字节 → "启"(3) 之后 "动"(3) 超了 → 只留 "启"
          tiny2[10] 放得下 9 字节 → "启动 1." 正好 9 字节 */
    char tiny[6];
    tr_fmt_named(tiny, sizeof(tiny), "启动 {version} @ {inst}", n2, v2, 2);
    eq("truncated no half char", tiny, "启");
    char tiny2[10];
    tr_fmt_named(tiny2, sizeof(tiny2), "启动 {version} @ {inst}", n2, v2, 2);
    eq("truncated full chars", tiny2, "启动 1.");

    /* 7. names/values 为 NULL 时退化成 tr(key) */
    tr_fmt_named(out, sizeof(out), "启动 {version} @ {inst}", NULL, NULL, 0);
    eq("null tables", out, "启动 {version} @ {inst}");

    /* 8. 命名替换真的走了词表（en） */
    i18n_set_language("en");
    tr_fmt_named(out, sizeof(out), "启动 {version} @ {inst}", n2, v2, 2);
    eq("en table", out, "Launch 1.20.1 @ Default");

    printf("FAILS=%d\n", fails);
    return fails == 0 ? 0 : 1;
}
'''


@unittest.skipUnless(_find_gcc(), "没有 gcc，跳过 C 侧编译真跑")
class NativeNamedFormatterTests(unittest.TestCase):
    """编译 i18n.c + util.c + config.c + cJSON，真跑 tr_fmt_named。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pymcl-i18n-"))
        src = cls.tmp / "harness.c"
        src.write_text(HARNESS, encoding="utf-8")
        exe = cls.tmp / "harness.exe"
        cmd = [
            _find_gcc(), "-O0", "-std=c11", "-DWIN32_LEAN_AND_MEAN",
            "-I", str(NATIVE / "include"), "-I", str(NATIVE / "vendor"),
            "-o", str(exe), str(src),
            str(NATIVE / "src" / "i18n.c"), str(NATIVE / "src" / "util.c"),
            str(NATIVE / "src" / "config.c"), str(NATIVE / "vendor" / "cJSON.c"),
            "-lz", "-lbcrypt", "-lcrypt32", "-lws2_32", "-lwinhttp",
            "-lpthread", "-lole32", "-lshell32",
        ]
        build = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=300)
        if build.returncode != 0:
            raise AssertionError(f"harness 编译失败：\n{build.stderr[-2000:]}")
        cls.exe = exe

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_named_placeholder_behaviour(self):
        """真实运行：命名替换 / 未给值保留 / 非法括号不动 / 截断不切半个字 / en 词表生效。"""
        proc = subprocess.run([str(self.exe), str(ROOT)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)
        out = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, f"harness 报错：\n{out}")
        self.assertIn("FAILS=0", out, f"tr_fmt_named 行为不符：\n{out}")
        self.assertIn("ok   en table -> Launch 1.20.1 @ Default", out,
                      "en 词表没生效，tr_fmt_named 走的不是 tr()：\n" + out)


if __name__ == "__main__":
    sys.exit(unittest.main())

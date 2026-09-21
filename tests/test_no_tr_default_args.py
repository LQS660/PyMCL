# -*- coding: utf-8 -*-
"""门禁：app/ 里函数默认参数不许调用 tr()。

默认参数在 import 时求值一次：模块加载是什么语言，这个默认值就永远停在
什么语言，运行期切语言/重启前改设置都对不上。已修的六处（install_game /
launch_game / build_launch_command / _install_game_impl / queue_launch_after /
_launch_installed）都改成 None 哨兵 + 函数体内 `or tr(...)` 运行期求值。
这条扫描保证同类写法不再回来。
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NoTrDefaultArgsTests(unittest.TestCase):
    def test_no_function_default_calls_tr(self):
        sites: list[str] = []
        for path in sorted((ROOT / "app").rglob("*.py")):
            try:
                tree = ast.parse(path.read_text("utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                defaults = list(node.args.defaults) + [
                    d for d in node.args.kw_defaults if d is not None]
                for d in defaults:
                    if (isinstance(d, ast.Call)
                            and isinstance(d.func, ast.Name)
                            and d.func.id == "tr"):
                        sites.append(
                            f"{path.relative_to(ROOT)}:{d.lineno} "
                            f"def {node.name}(... = tr(...))")
        self.assertEqual(sites, [], "函数默认参数里的 tr() 会在 import 时冻结语言:\n"
                         + "\n".join(sites))


if __name__ == "__main__":
    unittest.main()

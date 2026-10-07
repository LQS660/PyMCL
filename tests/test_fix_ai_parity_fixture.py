# -*- coding: utf-8 -*-
"""审计 05 P1-6 回归：`_c_ai_parity.py` 不得往仓库里写 fixture。

修前 `mock_script()`（:139）与 `main()`（:431）都写
`tests/fixtures/ai_mock_script_live.json` —— 仓库内文件，每次运行被最后一个场景覆写，
内容取决于最后一次运行、不可复现；main() 一开始还写成 `[]`，中途崩掉就留下空脚本。
修后默认写系统临时目录，或用 `PYMCL_AI_MOCK_OUT` 显式指定。

用例是纯静态 + 纯路径计算：不起桥、不联网、不写仓库。
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "_c_ai_parity.py"


def _load_parity():
    """把 _c_ai_parity.py 当模块载入（它 import 了 _c_rpc_coverage）。"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("_c_ai_parity_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LiveScriptStaysOutOfRepo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_parity()

    def setUp(self):
        # 每个用例从干净状态开始（模块级缓存 _LIVE_PATH）
        self.mod._LIVE_PATH = None
        self._old_env = os.environ.pop("PYMCL_AI_MOCK_OUT", None)

    def tearDown(self):
        self.mod._LIVE_PATH = None
        if self._old_env is not None:
            os.environ["PYMCL_AI_MOCK_OUT"] = self._old_env
        else:
            os.environ.pop("PYMCL_AI_MOCK_OUT", None)

    def test_default_path_is_outside_repo(self):
        p = self.mod._live_script_path()
        self.assertFalse(
            str(p.resolve()).lower().startswith(str(ROOT.resolve()).lower()),
            f"live 脚本默认落在仓库里：{p}")
        self.assertEqual(p.name, "ai_mock_script_live.json")

    def test_path_is_stable_within_a_process(self):
        """场景之间要复用同一份脚本文件（每次 mkdtemp 会留一堆临时目录）。"""
        self.assertEqual(self.mod._live_script_path(), self.mod._live_script_path())

    def test_env_override_is_honoured(self):
        target = Path(os.environ.get("TEMP", ".")) / "pymcl-parity-override.json"
        with mock.patch.dict(os.environ, {"PYMCL_AI_MOCK_OUT": str(target)}):
            self.mod._LIVE_PATH = None
            self.assertEqual(self.mod._live_script_path(), target)

    def test_repo_fixture_path_is_not_referenced_in_writers(self):
        """静态契约：写盘路径不能再出现 tests/fixtures/ai_mock_script_live.json。"""
        src = SCRIPT.read_text(encoding="utf-8")
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            self.assertNotIn(
                '"tests" / "fixtures" / "ai_mock_script_live.json"', stripped,
                f"还有写仓库 fixture 的路径：{stripped}")


if __name__ == "__main__":
    unittest.main()

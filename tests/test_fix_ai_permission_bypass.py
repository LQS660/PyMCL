# -*- coding: utf-8 -*-
"""审计 05 P0-1 / P1-1 回归：权限 DENY 规则不能被「等价路径拼写」绕过。

修前 `permission._norm_content` 只做「去首尾空白 + 压连续空白 + casefold」的字符串
相等比较，不做任何路径规范化；`rule_content_from_input` 取的是模型原样给出的
`path` / `filename`。于是同一批文件换几种 Windows 会归一成同一个名字的写法
（`./jei.toml`、`jei.toml.`、`sub\\jei2.toml`）就绕过了用户的 DENY 规则，落到
acceptEdits/edit/build/yolo 档的默认 ALLOW，执行层真的把文件写了/删了。

同根因的另一面是 `mods._mod_file_at`（P1-1）：护栏用 `.resolve()` 后的父目录比较，
`a.jar.` 被 Windows 归一成 `a.jar`，而权限层看到的还是 `a.jar.` —— 两侧看到的名字
不一致。修后两侧共用 `utils.norm_path_spelling`。

全部离线：临时目录，不碰真实 .minecraft / 用户数据。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from mclauncher import mods as mods_mod
from mclauncher import utils
from mclauncher.ai import modconfig
from mclauncher.ai import permission as perm
from mclauncher.ai.permission import Behavior, Decision, Rule
from mclauncher.ai.tools import TOOL_META

BS = chr(92)   # 反斜杠：源码里写 "\\" 会被 W605 盯上，这里显式构造


def _fresh_instance(root: Path):
    """全新临时实例：config/jei.toml、config/sub/jei2.toml、mods/a.jar 都是 ORIGINAL。"""
    (root / "config" / "sub").mkdir(parents=True, exist_ok=True)
    (root / "mods").mkdir(parents=True, exist_ok=True)
    (root / "config" / "jei.toml").write_text("ORIGINAL", encoding="utf-8")
    (root / "config" / "sub" / "jei2.toml").write_text("ORIGINAL", encoding="utf-8")
    (root / "mods" / "a.jar").write_bytes(b"JAR")
    return SimpleNamespace(name="t", path=root)


# 同一批「Windows 会归一到同一个文件」的拼写
_JEI_SPELLINGS = [
    "jei.toml",
    "./jei.toml",
    "." + BS + "jei.toml",
    "jei.toml.",
    "jei.toml ",
    "JEI.TOML",
    "././jei.toml",
    "sub/../jei.toml",
]


class DenyRuleSurvivesEquivalentSpellings(unittest.TestCase):
    """用户设了 DENY 规则 → 任何等价拼写都必须判 DENY，且磁盘一个字节都不许动。"""

    def _run_variant(self, spelling: str) -> tuple[Decision, str]:
        with tempfile.TemporaryDirectory() as d:
            inst = _fresh_instance(Path(d))
            deny = Rule("write_mod_config", "jei.toml", Behavior.DENY)
            dec = perm.decide(TOOL_META["write_mod_config"],
                              {"path": spelling, "content": "PWNED"},
                              "acceptEdits", [deny])
            if dec.decision == Decision.ALLOW:
                try:
                    modconfig.write_config(inst, spelling, "PWNED")
                except Exception:  # noqa: BLE001
                    pass
            body = (inst.path / "config" / "jei.toml").read_text(encoding="utf-8")
            return dec.decision, body

    def test_deny_rule_survives_every_spelling(self):
        for spelling in _JEI_SPELLINGS:
            with self.subTest(path=spelling):
                decision, body = self._run_variant(spelling)
                self.assertEqual(decision, Decision.DENY,
                                 f"DENY 规则被 {spelling!r} 绕过（判成 {decision.value}）")
                self.assertEqual(body, "ORIGINAL",
                                 f"{spelling!r} 真的改写了被守护的文件")

    def test_deny_rule_with_subdir_survives_backslash(self):
        variants = ["sub/jei2.toml", "sub" + BS + "jei2.toml", "./sub/jei2.toml",
                    "sub/jei2.toml.", "sub/./jei2.toml", "sub" + BS + "." + BS + "jei2.toml"]
        for spelling in variants:
            with self.subTest(path=spelling):
                with tempfile.TemporaryDirectory() as d:
                    inst = _fresh_instance(Path(d))
                    deny = Rule("write_mod_config", "sub/jei2.toml", Behavior.DENY)
                    dec = perm.decide(TOOL_META["write_mod_config"],
                                      {"path": spelling, "content": "PWNED"},
                                      "acceptEdits", [deny])
                    if dec.decision == Decision.ALLOW:
                        try:
                            modconfig.write_config(inst, spelling, "PWNED")
                        except Exception:  # noqa: BLE001
                            pass
                    body = (inst.path / "config" / "sub" / "jei2.toml").read_text("utf-8")
                    self.assertEqual(dec.decision, Decision.DENY,
                                     f"DENY 规则被 {spelling!r} 绕过")
                    self.assertEqual(body, "ORIGINAL", f"{spelling!r} 改写了被守护的文件")

    def test_delete_mod_deny_survives_spelling(self):
        """yolo 档 + DENY delete_mod filename='a.jar'：等价拼写必须仍然 DENY。"""
        for spelling in ["a.jar", "a.jar.", "./a.jar", "." + BS + "a.jar", "A.JAR"]:
            with self.subTest(filename=spelling):
                deny = Rule("delete_mod", "a.jar", Behavior.DENY)
                dec = perm.decide(TOOL_META["delete_mod"], {"filename": spelling},
                                  "yolo", [deny])
                self.assertEqual(dec.decision, Decision.DENY,
                                 f"DENY 规则被 filename={spelling!r} 绕过")

    def test_allow_rule_matches_same_spellings(self):
        """一致性同样适用于 ALLOW：同一个文件的等价拼写命中同一条规则。"""
        allow = Rule("write_mod_config", "jei.toml", Behavior.ALLOW)
        for spelling in _JEI_SPELLINGS:
            with self.subTest(path=spelling):
                dec = perm.decide(TOOL_META["write_mod_config"],
                                  {"path": spelling, "content": "x"}, "default", [allow])
                self.assertEqual(dec.decision, Decision.ALLOW,
                                 f"ALLOW 规则没认出 {spelling!r}")


class NonPathContentIsNotMangled(unittest.TestCase):
    """不能因为做路径规范化把模组 slug / 版本号的匹配弄坏。"""

    def test_distinct_identifiers_stay_distinct(self):
        cases = [
            ("install_mod", "name", "sodium", "sodium-extra"),
            ("install_mod", "name", "sodium", "jei"),
            ("install_game", "version", "1.20.1", "1.20.10"),
            ("inspect_mod", "filename", "jei.jar", "jei.jar.disabled"),
        ]
        for tool, key, a, b in cases:
            with self.subTest(tool=tool, rule=a, arg=b):
                rule = Rule(tool, a, Behavior.DENY)
                same = perm.decide(TOOL_META[tool], {key: a}, "default", [rule])
                other = perm.decide(TOOL_META[tool], {key: b}, "default", [rule])
                self.assertEqual(same.decision, Decision.DENY)
                self.assertNotEqual(other.decision, Decision.DENY,
                                    f"{a!r} 的规则误伤了 {b!r}")

    def test_version_with_dots_is_stable(self):
        rule = Rule("install_game", "1.20.1", Behavior.DENY)
        dec = perm.decide(TOOL_META["install_game"], {"version": "1.20.1"}, "yolo", [rule])
        self.assertEqual(dec.decision, Decision.DENY)


class ModGuardUsesSameNormalization(unittest.TestCase):
    """P1-1：护栏与权限层必须看到同一个名字。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.mods_dir = Path(self._tmp.name) / "mods"
        self.mods_dir.mkdir(parents=True)
        (self.mods_dir / "a.jar").write_bytes(b"JAR")

    def tearDown(self):
        self._tmp.cleanup()

    def test_guard_normalizes_to_same_name_as_permission_layer(self):
        """护栏归一后必须落到同一个文件（Windows 上等价拼写同文件）。"""
        target = self.mods_dir / "a.jar"
        for spelling in ["a.jar", "./a.jar", "a.jar.", "A.JAR", "." + BS + "a.jar"]:
            with self.subTest(filename=spelling):
                p = mods_mod._mod_file_at(self.mods_dir, spelling)
                # 返回值是未 resolve 的（既有契约）：比「指向同一个文件」而不是字面串
                self.assertTrue(p.is_file(), f"{spelling!r} 没指到 a.jar")
                self.assertEqual(p.resolve(), target.resolve(),
                                 f"{spelling!r} 解析到了别的文件")
                self.assertEqual(p.name.rstrip(" .").casefold(), "a.jar",
                                 f"{spelling!r} 的解析结果带着非规范名字 {p.name!r}")

    def test_guard_rejects_escapes(self):
        for spelling in [".." + BS + "outside.jar", "../outside.jar",
                         "sub/a.jar", "C:/Windows/notepad.exe", "", ".."]:
            with self.subTest(filename=spelling):
                with self.assertRaises(mods_mod.ModError):
                    mods_mod._mod_file_at(self.mods_dir, spelling)

    def test_delete_mod_reports_original_name_on_miss(self):
        with self.assertRaises(mods_mod.ModError):
            mods_mod.delete_mod(SimpleNamespace(name="t", path=self.mods_dir.parent),
                                "nope.jar.")


class NormHelperContract(unittest.TestCase):
    """utils.norm_path_spelling 的行为契约（两侧共用，钉死在这里）。"""

    def test_equivalent_spellings_collapse(self):
        for spelling in _JEI_SPELLINGS:
            with self.subTest(path=spelling):
                self.assertEqual(utils.norm_path_spelling(spelling), "jei.toml")

    def test_non_path_content_is_untouched(self):
        """slug / 版本号只做空白+大小写归一（casefold 是既有口径），不被路径规则改写。"""
        for text in ["sodium", "1.20.1", "jei", "sodium-0.5.8.jar", "RLCraft"]:
            with self.subTest(text=text):
                self.assertEqual(utils.norm_path_spelling(text), text.casefold())
        # 带「路径特征」的写法才走 normpath：分隔符统一 / 尾部点空格去掉
        self.assertEqual(utils.norm_path_spelling("a" + BS + "b"), "a/b")
        self.assertEqual(utils.norm_path_spelling("x."), "x")
        self.assertEqual(utils.norm_path_spelling("x "), "x")

    def test_empty_inputs(self):
        self.assertEqual(utils.norm_path_spelling(""), "")
        self.assertEqual(utils.norm_path_spelling(None), "")
        self.assertEqual(utils.norm_path_spelling("."), "")
        self.assertEqual(utils.norm_path_spelling("  "), "")


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""servers_page 的 InfoBar 文案不许裸中文（i18n 运行期门禁的页面级样本）。

历史缺陷：添加/更新/导入/导出的提示正文是裸 f-string（`f"服务器已更新"`），
英文界面下标题翻了、正文还是中文，而且 `f"服务器已更新"` 连占位符都没有，
纯属忘了删 f。规则：InfoBar.success/error/info/warning 的标题与正文参数里
凡含 CJK 的字符串字面量必须出自 tr(...)（tr("…{0}…").format(...) 也算）；
str(e) 这类动态文本不拦。
顺带守住本轮补进 en.json 的 5 个词条不回退。

第二轮缺陷（2026-09-28）：这 5 个 key 当初只补进 en.json，zh_CN.json 里没有，
而 `test_new_locale_keys_present_in_en()` 只读 EN —— 测试全绿却漏检。
`i18n.py:91-104` 明确 zh_CN 与 en 互不回退，所以两边缺哪个都会露馅：
  · en 缺 → 英文界面上冒出中文；
  · zh_CN 缺 → 中文界面回落成 key 本身（key 就是中文原文，**视觉上看不出来**），
    但词表已不完整，将来接第三方语言（回退 en）时这 5 条会以英文形态出现。
所以断言改成两边都查，并加一条全局「两份词表 key 集合必须相等」。
"""
from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "app" / "pages" / "servers_page.py"
LOCALES = ROOT / "mclauncher" / "locales"
ZH = LOCALES / "zh_CN.json"
EN = LOCALES / "en.json"

CJK = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]")
INFOBAR_KINDS = {"success", "error", "info", "warning"}

NEW_KEYS = [
    "服务器 {0} 已添加",
    "服务器已更新",
    "已导入 {0} 个服务器",
    "已保存到 {0}",
    "启动器主目录: {0}",
]


def _arg_ok(arg) -> bool:
    """一个 InfoBar 实参是否合规：无 CJK，或 CJK 字面量在 tr() 里。"""
    # tr(...) / tr(...).format(...) / str(e) 等调用：展开找 CJK 常量，
    # 每个含 CJK 的常量都必须挂在某个 tr( 调用的参数位上
    tr_calls = [n for n in ast.walk(arg)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "tr"]
    protected: set[int] = set()
    for call in tr_calls:
        for sub in ast.walk(call):
            if isinstance(sub, ast.Constant):
                protected.add(id(sub))
    for node in ast.walk(arg):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and CJK.search(node.value) and id(node) not in protected):
            return False
    return True


class ServersInfoBarI18nTests(unittest.TestCase):
    def test_infobar_texts_are_wrapped_in_tr(self):
        tree = ast.parse(PAGE.read_text("utf-8"))
        bad: list[str] = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in INFOBAR_KINDS
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "InfoBar"):
                continue
            check_args = list(node.args[:2])
            check_args += [kw.value for kw in (node.keywords or [])
                           if kw.arg in ("title", "content")]
            for arg in check_args:
                if not _arg_ok(arg):
                    bad.append(f"servers_page.py:{node.lineno} {ast.dump(arg)[:80]}")
        self.assertEqual(bad, [], "InfoBar 标题/正文里的裸中文必须包 tr():\n" + "\n".join(bad))

    def test_new_locale_keys_present_in_both(self):
        """这 5 条两边都得有：只补 en 时中文界面回落成 key 本身，肉眼看不出来。"""
        zh = json.loads(ZH.read_text("utf-8"))
        en = json.loads(EN.read_text("utf-8"))
        missing_zh = [k for k in NEW_KEYS if not str(zh.get(k, "")).strip()]
        missing_en = [k for k in NEW_KEYS if not str(en.get(k, "")).strip()]
        self.assertEqual(missing_zh, [], f"zh_CN.json 缺本轮新增词条: {missing_zh}")
        self.assertEqual(missing_en, [], f"en.json 缺本轮新增词条: {missing_en}")

    def test_locale_key_sets_are_identical(self):
        """两份词表的 key 集合必须完全相等。

        `i18n.py:91-104` 让 zh_CN 与 en 互不回退（只有第三方语言才回退 en），
        所以任一边少一条都是缺陷：en 少 → 英文界面冒中文；zh_CN 少 → 中文界面
        回落成 key 本身（key 就是中文原文，视觉上正常，因此只能靠这条断言发现）。
        原先的 `test_new_locale_keys_present_in_en()` 只读 EN，正是被这个盲区漏过去的。
        """
        zh = json.loads(ZH.read_text("utf-8"))
        en = json.loads(EN.read_text("utf-8"))
        only_zh = sorted(set(zh) - set(en))
        only_en = sorted(set(en) - set(zh))
        self.assertEqual(
            (only_zh, only_en), ([], []),
            f"两份词表 key 集合不一致：zh_CN 独有 {len(only_zh)} 条 {only_zh[:10]}；"
            f"en 独有 {len(only_en)} 条 {only_en[:10]}")

    def test_zh_cn_is_identity(self):
        """zh_CN 里 key 就是值：中文界面永远显示原文，不许有别的值。"""
        zh = json.loads(ZH.read_text("utf-8"))
        odd = [k for k, v in zh.items() if v != k]
        self.assertEqual(odd, [], f"zh_CN 里这些 key 的值不是原文: {odd[:10]}")

    def test_settings_root_label_uses_tr(self):
        src = (ROOT / "app" / "pages" / "settings_page.py").read_text("utf-8")
        self.assertIn('tr("启动器主目录: {0}")', src,
                      "设置页主目录标签必须走 tr()，不许裸 f-string")


if __name__ == "__main__":
    unittest.main()

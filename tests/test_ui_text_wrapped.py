# -*- coding: utf-8 -*-
"""servers_page 的 InfoBar 文案不许裸中文（i18n 运行期门禁的页面级样本）。

历史缺陷：添加/更新/导入/导出的提示正文是裸 f-string（`f"服务器已更新"`），
英文界面下标题翻了、正文还是中文，而且 `f"服务器已更新"` 连占位符都没有，
纯属忘了删 f。规则：InfoBar.success/error/info/warning 的标题与正文参数里
凡含 CJK 的字符串字面量必须出自 tr(...)（tr("…{0}…").format(...) 也算）；
str(e) 这类动态文本不拦。
顺带守住本轮补进 en.json 的 5 个词条不回退。
"""
from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "app" / "pages" / "servers_page.py"
EN = ROOT / "mclauncher" / "locales" / "en.json"

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

    def test_new_locale_keys_present_in_en(self):
        data = json.loads(EN.read_text("utf-8"))
        missing = [k for k in NEW_KEYS if not str(data.get(k, "")).strip()]
        self.assertEqual(missing, [], f"en.json 缺本轮新增词条: {missing}")

    def test_settings_root_label_uses_tr(self):
        src = (ROOT / "app" / "pages" / "settings_page.py").read_text("utf-8")
        self.assertIn('tr("启动器主目录: {0}")', src,
                      "设置页主目录标签必须走 tr()，不许裸 f-string")


if __name__ == "__main__":
    unittest.main()

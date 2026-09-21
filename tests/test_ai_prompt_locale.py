# -*- coding: utf-8 -*-
"""AI 系统提示词的回复语言要跟界面语言走（审计 AI-P3-9）。"""
from __future__ import annotations

import unittest

from mclauncher import i18n
from mclauncher.ai import prompt


class PromptLocaleTests(unittest.TestCase):
    def setUp(self):
        self._saved = i18n.current_language()

    def tearDown(self):
        i18n._current_lang = self._saved

    def test_zh_prompt_asks_for_chinese(self):
        text = prompt.system_prompt("zh_CN")
        self.assertIn("用简体中文", text)
        self.assertNotIn(prompt._LANG_RULE_TOKEN, text)

    def test_en_prompt_asks_for_english(self):
        text = prompt.system_prompt("en")
        self.assertIn("Reply in English", text)
        self.assertNotIn("用简体中文", text)
        self.assertNotIn(prompt._LANG_RULE_TOKEN, text)

    def test_default_follows_current_language(self):
        i18n._current_lang = "en"
        self.assertIn("Reply in English", prompt.system_prompt())
        i18n._current_lang = "zh_CN"
        self.assertIn("用简体中文", prompt.system_prompt())

    def test_unknown_locale_falls_back_to_generic_rule(self):
        text = prompt.system_prompt("ja")
        self.assertIn("locale: ja", text)
        self.assertNotIn(prompt._LANG_RULE_TOKEN, text)

    def test_rest_of_prompt_untouched(self):
        # 只换语言那一行，其余规矩（工具规矩 / 排错流程）一字不动
        for lang in ("zh_CN", "en"):
            text = prompt.system_prompt(lang)
            self.assertIn("# 工具规矩", text)
            self.assertIn("先 get_launcher_state", text)


if __name__ == "__main__":
    unittest.main()

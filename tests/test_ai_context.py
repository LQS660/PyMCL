# -*- coding: utf-8 -*-
"""批次 2（上下文成本）回归：窗口可配置且诚实 / 工具按需加载 / 用量采集 / 模型降级。

- 2.1 ai_context_window：settings → AutoConfig（非法值回退保守默认 128k）；
  桥的 get/save_settings 带夹取；代码里不再有当结论用的「未实测」注释。
- 2.2 工具按需加载：固定 10 条 prompt 全部选对工具，且单轮声明 token 降幅 ≥40%。
- 2.3 用量采集：自定义直连拿到真实 usage → 写 trace 与会话事件日志（Usage）。
- 2.4 模型降级：主模型连续 429/5xx → 切备用模型完成本回合且可见提示；
  未配置备用模型时行为与改造前一致。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from mclauncher.ai import agent as agent_mod
from mclauncher.ai import compact as compact_mod
from mclauncher.ai import trace as trace_mod
from mclauncher.ai.client import AIClientError
from mclauncher.ai.tokens import estimate_text
from mclauncher.ai.tools import TOOL_SCHEMAS, select_tool_schemas


def _tc(name):
    return {"id": f"c-{name}", "type": "function",
            "function": {"name": name, "arguments": "{}"}}


class ContextWindowTests(unittest.TestCase):
    def test_settings_passthrough(self):
        cfg = compact_mod.auto_config_from_settings({"ai_context_window": 65536})
        self.assertEqual(cfg.context_window, 65536)

    def test_invalid_falls_back_to_conservative_default(self):
        for bad in ("", None, "abc", [], 0, -5):
            cfg = compact_mod.auto_config_from_settings({"ai_context_window": bad})
            self.assertEqual(cfg.context_window, 131072, bad)

    def test_clamped_to_minimum(self):
        cfg = compact_mod.auto_config_from_settings({"ai_context_window": 100})
        self.assertEqual(cfg.context_window, 8192)

    def test_no_untested_note_left_as_conclusion(self):
        # 「未实测」只能以【待实测】标记 + 依据出现，不能当结论用
        tokens_src = Path(agent_mod.__file__).parent.joinpath("tokens.py").read_text("utf-8")
        self.assertIn("【待实测】", tokens_src)
        self.assertNotIn("窗口未实测，context_window 由 settings 传入", tokens_src)

    def test_bridge_settings_roundtrip(self):
        import bridge.api as bridge_api
        api = bridge_api.BackendAPI(mock.MagicMock())
        with mock.patch.object(bridge_api.CONFIG, "update") as upd, \
             mock.patch.object(bridge_api.CONFIG, "save"):
            api.save_settings({"ai_context_window": 99})
            patch = upd.call_args[0][0]
            self.assertEqual(patch["ai_context_window"], 8192)   # 夹到下限
            api.save_settings({"ai_context_window": 65536})
            patch = upd.call_args[0][0]
            self.assertEqual(patch["ai_context_window"], 65536)


class ToolSelectionTests(unittest.TestCase):
    FULL = estimate_text(json.dumps(TOOL_SCHEMAS, ensure_ascii=False))

    PROMPTS = [
        ("你好", ["get_launcher_state"], ["delete_instance", "install_world"]),
        ("帮我装个钠", ["search_mods", "install_mod", "ask_user"], ["install_world"]),
        ("装一下 BSL 光影", ["search_content", "install_shader"], ["install_datapack"]),
        ("启动闪退了帮我看", ["get_latest_log", "get_crash_report", "diagnose_launch"], ["install_world"]),
        ("读一下崩溃日志", ["get_latest_log", "get_crash_report"], ["download_java"]),
        ("建个实例叫测试", ["create_instance"], ["delete_instance"]),
        ("删掉 JEI 这个模组", ["delete_mod"], ["install_world"]),
        ("下载 Java 17", ["download_java", "get_java_list"], ["install_world"]),
        ("把渲染距离配置改成 8", ["write_mod_config", "list_mod_configs"], ["delete_instance"]),
        ("扫描下模组冲突", ["scan_mod_conflicts", "inspect_mod"], ["install_world"]),
    ]

    def test_ten_prompts_all_select_right_tools(self):
        total = 0
        for text, must, banned in self.PROMPTS:
            sel = select_tool_schemas([{"role": "user", "content": text}])
            names = {s["function"]["name"] for s in sel}
            for m in must:
                self.assertIn(m, names, f"{text!r} 缺 {m}")
            for b in banned:
                self.assertNotIn(b, names, f"{text!r} 不该声明 {b}")
            total += estimate_text(json.dumps(sel, ensure_ascii=False))
        avg = total / len(self.PROMPTS)
        self.assertLessEqual(avg / self.FULL, 0.60,
                             f"平均声明 token 降幅不足 40%: {avg}/{self.FULL}")

    def test_each_prompt_at_least_40_percent(self):
        for text, _must, _banned in self.PROMPTS:
            sel = select_tool_schemas([{"role": "user", "content": text}])
            t = estimate_text(json.dumps(sel, ensure_ascii=False))
            self.assertLessEqual(t / self.FULL, 0.60, text)

    def test_artifact_result_pulls_read_artifact(self):
        msgs = [{"role": "user", "content": "继续"},
                {"role": "tool", "content": "[结果过长，已存文件] cache/ai_results/x.txt"}]
        names = {s["function"]["name"] for s in select_tool_schemas(msgs)}
        self.assertIn("read_artifact", names)

    def test_never_returns_empty(self):
        # 无消息时也至少声明核心集；选择器永远不返回空集
        sel = select_tool_schemas([])
        self.assertTrue(sel)
        self.assertGreaterEqual(len(sel), 13)


class UsageLoggingTests(unittest.TestCase):
    def test_stream_usage_logged(self):
        def stream(settings, messages, tools, http_cancel=None):
            yield {"type": "delta", "text": "你好"}
            yield {"type": "usage", "usage": {"prompt_tokens": 100,
                                              "completion_tokens": 5,
                                              "prompt_tokens_details": {"cached_tokens": 40}}}
            yield {"type": "done"}

        with mock.patch.object(agent_mod, "chat_stream", side_effect=stream), \
             mock.patch.object(agent_mod.chat_store, "log_event") as le, \
             mock.patch.object(agent_mod.trace, "record") as tr:
            agent_mod.run_agent(SimpleNamespace(), {}, [], "你好")
        usage_events = [c for c in le.call_args_list
                        if len(c.args) > 1 and c.args[1] == "Usage"]
        self.assertTrue(usage_events, "真实 usage 必须进会话事件日志")
        kw = usage_events[0].kwargs
        self.assertEqual(kw["prompt_tokens"], 100)
        self.assertEqual(kw["completion_tokens"], 5)
        self.assertEqual(kw["cached_tokens"], 40)
        self.assertTrue(any(c.kwargs.get("prompt_tokens") == 100
                            for c in tr.call_args_list), "usage 必须进 trace")


class ModelFallbackTests(unittest.TestCase):
    def _run(self, settings, stream_fn, once_fn=None):
        statuses = []
        with mock.patch.object(agent_mod, "chat_stream", side_effect=stream_fn), \
             mock.patch.object(agent_mod, "chat_once", side_effect=once_fn), \
             mock.patch.object(agent_mod.time, "sleep"), \
             mock.patch.object(agent_mod.chat_store, "log_event"):
            res = agent_mod.run_agent(SimpleNamespace(), settings, [], "干活",
                                      on_status=lambda k, p: statuses.append((k, p)))
        return res, statuses

    def test_fallback_after_persistent_429(self):
        models_used = []

        def stream(settings, messages, tools, http_cancel=None):
            models_used.append(settings.get("ai_model"))
            if settings.get("ai_model") == "main":
                raise AIClientError("rate limited", 429)
            yield {"type": "delta", "text": "备用模型接手"}
            yield {"type": "done"}

        res, statuses = self._run({"ai_model": "main", "ai_fallback_model": "backup"}, stream)
        self.assertEqual(models_used[0], "main")
        self.assertEqual(models_used[-1], "backup")
        self.assertIn("备用模型接手", str(res))
        kinds = [k for k, _ in statuses]
        self.assertIn("model_fallback", kinds, "切换必须用户可见")

    def test_no_fallback_configured_behaves_unchanged(self):
        events = []

        def stream(settings, messages, tools, http_cancel=None):
            raise AIClientError("rate limited", 429)

        def once(settings, messages, tools, http_cancel=None):
            raise AIClientError("rate limited", 429)

        with mock.patch.object(agent_mod, "chat_stream", side_effect=stream), \
             mock.patch.object(agent_mod, "chat_once", side_effect=once), \
             mock.patch.object(agent_mod.time, "sleep"), \
             mock.patch.object(agent_mod.chat_store, "log_event",
                               side_effect=lambda *a, **k: events.append(a)):
            with self.assertRaises(AIClientError):
                agent_mod.run_agent(SimpleNamespace(), {"ai_model": "main"}, [], "干活")
        self.assertFalse(any(len(a) > 1 and a[1] == "ModelFallback" for a in events),
                         "未配置备用模型时不得切换")

    def test_5xx_also_triggers_fallback(self):
        models_used = []

        def stream(settings, messages, tools, http_cancel=None):
            models_used.append(settings.get("ai_model"))
            if settings.get("ai_model") == "main":
                raise AIClientError("bad gateway", 502)
            yield {"type": "delta", "text": "ok"}
            yield {"type": "done"}

        self._run({"ai_model": "main", "ai_fallback_model": "backup"}, stream)
        self.assertEqual(models_used[-1], "backup")


if __name__ == "__main__":
    unittest.main()

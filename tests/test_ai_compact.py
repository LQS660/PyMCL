# -*- coding: utf-8 -*-
"""批次 3：token 计量 + 两级压缩 + 熔断 + 结果落盘。全部离线，临时目录。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mclauncher.ai import artifacts
from mclauncher.ai import compact
from mclauncher.ai import tokens as tokens_mod
from mclauncher.ai import tools as ai_tools
from mclauncher.ai.compact import (
    AutoConfig, AutoDecision, CompactState, MicroConfig, RapidRefillBlocked,
    auto_threshold, check_rapid_refill, compact_conversation, microcompact,
    note_compact_failure, note_compact_success, should_autocompact,
)
from mclauncher.ai.tools import TOOL_META


def _conv(n_tool_results=8, content="字" * 2000, keep_note=""):
    """system + user + n 组 (assistant tool_calls + tool result)。"""
    msgs = [
        {"role": "system", "content": "系统提示"},
        {"role": "system", "content": "状态"},
        {"role": "user", "content": "帮我装钠"},
    ]
    for i in range(n_tool_results):
        msgs.append({"role": "assistant", "content": None,
                     "tool_calls": [{"id": f"c{i}", "type": "function",
                                     "function": {"name": "list_mods", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "name": "list_mods",
                     "content": content + str(i)})
    msgs.append({"role": "user", "content": "然后呢" + keep_note})
    return msgs


class TokenTests(unittest.TestCase):
    def test_estimate_text(self):
        self.assertGreater(tokens_mod.estimate_text("一二三四五六七"), 5)
        self.assertLess(tokens_mod.estimate_text("abcdefgh"), 4)
        self.assertEqual(tokens_mod.estimate_text(""), 0)

    def test_estimate_stable(self):
        msgs = _conv(3)
        vals = {tokens_mod.estimate_messages(msgs) for _ in range(3)}
        self.assertEqual(len(vals), 1, "同一输入连算三次必须稳定")

    def test_provider_usage_baseline(self):
        st = tokens_mod.TokenState()
        self.assertEqual(st.source, "estimate")
        tokens_mod.update_from_usage(st, {"prompt_tokens": 1000,
                                          "completion_tokens": 50}, 6)
        self.assertEqual(st.source, "provider_usage")
        self.assertEqual(st.base_tokens, 1000)
        msgs = _conv(3)  # 9 条
        cur = tokens_mod.current_input_tokens(msgs, st)
        expect = 1000 + tokens_mod.estimate_messages(msgs[6:])
        self.assertEqual(cur, expect, "基线之后的新增消息才参与估算")


class MicrocompactTests(unittest.TestCase):
    def test_disabled(self):
        res = microcompact(_conv(8), MicroConfig(enabled=False), 0.0, 0.0)
        self.assertEqual(res.decision_reason, "disabled")
        self.assertFalse(res.changed)

    def test_no_candidates(self):
        msgs = [{"role": "user", "content": "嗨"}]
        res = microcompact(msgs, MicroConfig(threshold_tokens=1), 0.0, 0.0)
        self.assertEqual(res.decision_reason, "no_candidates")

    def test_nothing_to_clear(self):
        res = microcompact(_conv(3), MicroConfig(threshold_tokens=1), 0.0, 0.0)
        self.assertEqual(res.decision_reason, "nothing_to_clear")

    def test_not_triggered(self):
        res = microcompact(_conv(8), MicroConfig(threshold_tokens=10 ** 9), 0.0, 0.0)
        self.assertEqual(res.decision_reason, "not_triggered")

    def test_below_min_savings_reverts(self):
        """门禁 2.3：省不够时 changed=False 且 messages 原样返回。"""
        msgs = _conv(8, content="小结果")
        snapshot = [dict(m) for m in msgs]
        cfg = MicroConfig(threshold_tokens=1, keep_recent_tool_results=5,
                          min_token_savings=2000)
        res = microcompact(msgs, cfg, 0.0, 0.0)
        self.assertEqual(res.decision_reason, "below_min_savings")
        self.assertFalse(res.changed)
        self.assertEqual([dict(m) for m in res.messages], snapshot,
                         "below_min_savings 必须整体回退")

    def test_applied_clears_old_keeps_recent(self):
        msgs = _conv(8, content="字" * 2000)
        original = [dict(m) for m in msgs]
        cfg = MicroConfig(threshold_tokens=1, keep_recent_tool_results=5,
                          min_token_savings=2000)
        res = microcompact(msgs, cfg, 0.0, 0.0)
        self.assertEqual(res.decision_reason, "applied")
        self.assertTrue(res.changed)
        self.assertEqual(res.cleared_count, 3)
        self.assertEqual(res.cleared_ids, ["c0", "c1", "c2"])
        self.assertEqual(res.kept_ids, [f"c{i}" for i in range(3, 8)])
        self.assertGreaterEqual(res.tokens_saved, 2000)
        cleared = [m for m in res.messages if m.get("role") == "tool"][:3]
        self.assertTrue(all(m["content"].startswith("[工具结果已清理") for m in cleared))
        self.assertEqual([dict(m) for m in msgs], original, "入参列表不得被原地改掉")


class AutocompactTests(unittest.TestCase):
    def test_threshold(self):
        self.assertEqual(auto_threshold(AutoConfig()), 187000)

    def test_reasons(self):
        cfg = AutoConfig(context_window=2000, buffer_tokens=500)  # 阈值 1500
        cstate = CompactState()
        st = tokens_mod.TokenState()
        self.assertEqual(should_autocompact(_conv(8), cfg, cstate, st).reason,
                         "above_threshold")
        self.assertEqual(should_autocompact(_conv(8), cfg, cstate, st).should, True)
        small = [{"role": "user", "content": "hi"}]
        self.assertEqual(should_autocompact(small, cfg, cstate, st).reason,
                         "not_enough_messages")
        # 默认阈值 187000 很高，正常体量的对话在阈值之下
        self.assertEqual(should_autocompact(_conv(8), AutoConfig(), cstate, st).reason,
                         "below_threshold")
        self.assertEqual(should_autocompact(_conv(8), AutoConfig(enabled=False),
                                            cstate, st).reason, "disabled")

    def test_circuit_breaker_after_three_failures(self):
        """门禁 2.3：连续失败 3 次进熔断，第 4 次尝试被拦住。"""
        cfg = AutoConfig()
        cstate = CompactState()
        self.assertFalse(note_compact_failure(cstate, cfg))
        self.assertFalse(note_compact_failure(cstate, cfg))
        self.assertTrue(note_compact_failure(cstate, cfg))   # 3 次 → 到线
        decision = should_autocompact(_conv(8), cfg, cstate, tokens_mod.TokenState())
        self.assertEqual(decision.reason, "circuit_breaker")
        self.assertFalse(decision.should)

    def test_rapid_refill_breaker(self):
        """压缩后不足 3 个工具轮又要压：连续 3 次抛 RapidRefillBlocked。"""
        cfg = AutoConfig()
        cstate = CompactState()
        note_compact_success(cstate)   # 刚压缩完：tool_turns_since_compact = 0
        check_rapid_refill(cstate, cfg)   # 第 1 次：计数不抛
        check_rapid_refill(cstate, cfg)   # 第 2 次：计数不抛
        self.assertEqual(cstate.rapid_refills, 2)
        with self.assertRaises(RapidRefillBlocked):
            check_rapid_refill(cstate, cfg)   # 第 3 次：熔断
        # 工具轮数攒够之后不再累计
        cstate2 = CompactState()
        cstate2.tool_turns_since_compact = 5
        check_rapid_refill(cstate2, cfg)
        self.assertEqual(cstate2.rapid_refills, 0)

    def test_compact_conversation(self):
        cfg = AutoConfig(keep_recent_messages=4)
        msgs = _conv(8)
        pre = tokens_mod.estimate_messages(msgs)

        def summarize(slice_msgs):
            return "用户想装钠；已列出模组；尚未安装。"

        res = compact_conversation(msgs, cfg, summarize)
        # 倒数第 4 条恰好是 tool 回执：边界要往前挪到它的 assistant(tool_calls)，
        # 所以实际保留 5 条、摘要 13 条，而不是机械的 4 / 14。
        self.assertEqual(res.summarized_message_count, len(msgs) - 2 - 5)
        self.assertEqual(res.kept_message_count, 5)
        self.assertIn("[历史摘要]", res.messages[2]["content"])
        self.assertIn("尚未安装", res.messages[2]["content"])
        self.assertLess(res.post_token_count, pre)
        self.assertEqual(res.messages[-1]["content"], msgs[-1]["content"])
        self.assertEqual(res.messages[:2], msgs[:2], "system 头必须原样保留")
        self.assertEqual(res.messages[3]["role"], "assistant")
        self.assertTrue(res.messages[3].get("tool_calls"))

    def test_compact_never_leaves_orphan_tool(self):
        """保留边界落在 tool 回执上时必须往前带上它的 assistant，否则下一轮 API 400。"""
        def summarize(_):
            return "摘要"
        for keep in range(2, 12):
            res = compact_conversation(_conv(8), AutoConfig(keep_recent_messages=keep),
                                       summarize)
            first_kept = res.messages[3]
            self.assertNotEqual(first_kept.get("role"), "tool",
                                f"keep={keep} 时摘要后紧跟孤儿 tool 消息")
            # 保留区里每条 tool 都能在前面找到带同 id 的 tool_calls
            seen = set()
            for m in res.messages[3:]:
                for tc in m.get("tool_calls") or []:
                    seen.add(tc["id"])
                if m.get("role") == "tool":
                    self.assertIn(m["tool_call_id"], seen)

    def test_compact_placeholder_does_not_promise_lookup(self):
        self.assertNotIn("tool_call_id", compact._PLACEHOLDER)

    def test_compact_rejects_empty_summary(self):
        with self.assertRaises(ValueError):
            compact_conversation(_conv(8), AutoConfig(), lambda m: "  ")


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = artifacts.ARTIFACTS_DIR
        artifacts.ARTIFACTS_DIR = Path(self._tmp.name)

    def tearDown(self):
        artifacts.ARTIFACTS_DIR = self._old
        self._tmp.cleanup()

    def test_store_writes_file_and_summary(self):
        text = "\n".join(f"第{i}行内容" for i in range(500))
        summary = artifacts.store(text, "scan_mod_conflicts")
        self.assertIn("cache/ai_results/", summary)
        self.assertIn("总行数 500", summary)
        rel = summary.split("] ", 1)[1].split("\n", 1)[0]
        path = Path(self._tmp.name) / rel.split("ai_results/", 1)[1]
        self.assertTrue(path.is_file())

    def test_read_artifact_offset(self):
        text = "\n".join(f"L{i}" for i in range(300))
        rel = artifacts.save(text, "t")
        name = rel.split("/")[-1]
        out = artifacts.read_artifact(name, offset=100, limit=5)
        self.assertIn("L100", out)
        self.assertIn("L104", out)
        self.assertNotIn("L99\n", out)
        self.assertIn("第 101-105/300 行", out)
        self.assertIn("找不到", artifacts.read_artifact("nope.txt"))

    def test_clip_routes_to_artifact(self):
        out = ai_tools._clip("字" * 9000, "scan_mod_conflicts")
        self.assertIn("已存文件", out)
        self.assertNotIn("…(已截断)", out)
        small = ai_tools._clip("短结果")
        self.assertEqual(small, "短结果")

    def test_read_artifact_tool_registered(self):
        self.assertIn("read_artifact", TOOL_META)
        self.assertTrue(TOOL_META["read_artifact"].readonly)
        self.assertEqual(TOOL_META["read_artifact"].side_effect, "read")
        # 批次 3 新增 read_artifact 后，工具总数 33 → 34
        self.assertEqual(len(TOOL_META), 34)


if __name__ == "__main__":
    unittest.main()

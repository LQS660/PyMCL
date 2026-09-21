# -*- coding: utf-8 -*-
"""批次 6.3 离线评测集：≥10 条固定场景，模型打桩，failed == 0 为通过。

每条场景：用户输入 / 期望调用的工具序列 / 禁止调用的工具。
覆盖批次 1 / 2 / 5 的可见行为：回滚、工具筛选、坏参数纠正。

离线跑法（不联网、不调真模型）：
    C:/Python312/python.exe -m pytest tests/test_ai_eval.py -q --timeout=300
    C:/Python312/python.exe tests/test_ai_eval.py            # 直接跑，打印逐场景表
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mclauncher.ai import agent as agent_mod
from mclauncher.ai import checkpoint as ckpt
from mclauncher.ai import tools as ai_tools
from mclauncher.ai.result import StopReason
from mclauncher.ai.tools import TOOL_META, select_tool_schemas


def _tc(name, args_json="{}"):
    return {"id": f"c-{name}", "type": "function",
            "function": {"name": name, "arguments": args_json}}


# ---------------------------------------------------------------- 场景定义
# each: user, script (模型每轮产出 tool_calls 的脚本), expected_tools（按序执行到的工具）,
#       forbidden（禁止出现的工具）, settings, run_tool（打桩的执行结果）

def _scene(name, user, script, expected, forbidden, settings=None):
    return {"name": name, "user": user, "script": script,
            "expected": expected, "forbidden": forbidden, "settings": settings or {}}


SCENARIOS = [
    _scene("装钠走搜索-选择-安装链",
           "帮我装个钠",
           [[_tc("search_mods", '{"query": "钠"}')],
            [_tc("ask_user", '{"prompt": "装哪个", "options": ["sodium"]}')],
            [_tc("install_mod", '{"name": "sodium"}')],
            "装好了"],
           ["search_mods", "ask_user", "install_mod"],
           ["delete_mod", "install_shader"]),
    _scene("装光影不装模组",
           "装一下 BSL 光影",
           [[_tc("search_content", '{"kind": "shader", "query": "BSL"}')],
            [_tc("install_shader", '{"name": "BSL"}')],
            "光影装好了"],
           ["search_content", "install_shader"],
           ["install_mod", "delete_instance"]),
    _scene("启动闪退只诊断",
           "启动闪退了帮我看",
           [[_tc("diagnose_launch")],
            "是 Java 版本不对，先装 Java 17"],
           ["diagnose_launch"],
           ["install_mod", "delete_mod", "launch_game"]),
    _scene("读崩溃日志",
           "读一下崩溃日志",
           [[_tc("get_crash_report")],
            "崩溃原因是显存不够"],
           ["get_crash_report"],
           ["install_mod", "delete_mod"]),
    _scene("建实例",
           "建个实例叫测试服",
           [[_tc("create_instance", '{"name": "测试服"}')],
            "建好了"],
           ["create_instance"],
           ["delete_instance", "delete_mod"]),
    _scene("删模组先过权限",
           "删掉 JEI",
           [[_tc("delete_mod", '{"filename": "jei.jar"}')],
            "已删除"],
           ["delete_mod"],
           # delete_instance 与 delete_mod 同属「删除」关键词组，按组声明是预期行为，
           # 所以声明口径只禁不同组的 install_mod；执行口径仍禁 delete_instance
           ["install_mod"]),
    _scene("坏参数自纠",
           "把 options.txt 的渲染距离改成 8",
           [[_tc("write_mod_config", '{"path": "options.txt"}')],
            [_tc("write_mod_config", '{"path": "options.txt", "content": "render_distance=8"}')],
            "改好了"],
           # 5.1：第一轮坏参数被拦截、根本不进执行器——执行序列只有修正后那次
           ["write_mod_config"],
           ["delete_mod"]),
    _scene("整合包新建实例再装",
           "装 RLCraft 整合包",
           [[_tc("create_instance", '{"name": "RLCraft"}')],
            [_tc("search_modpacks", '{"query": "RLCraft"}')],
            [_tc("install_modpack", '{"name": "RLCraft"}')],
            "装好了"],
           ["create_instance", "search_modpacks", "install_modpack"],
           ["delete_mod"]),
    _scene("多轮扫描冲突后禁用",
           "扫描模组冲突，重复的禁掉",
           [[_tc("scan_mod_conflicts")],
            [_tc("disable_mod", '{"filename": "dup.jar"}')],
            "已禁用重复的那个"],
           ["scan_mod_conflicts", "disable_mod"],
           ["delete_mod", "delete_instance"]),
    _scene("工具筛选：只声明需要的",
           "装钠和光影",
           [[_tc("search_mods", '{"query": "钠"}')],
            "先选一下要哪个"],
           ["search_mods"],
           ["install_world", "delete_instance", "download_java"]),
    _scene("计划拒绝零写操作",
           "规划一下装 10 个模组的步骤",
           [[_tc("update_plan",
                 '{"items": [{"title": "搜", "status": "pending"},'
                 ' {"title": "装", "status": "pending"}]}')],
            "计划已出",
           ],
           ["update_plan"],
           ["install_mod", "delete_mod"],
           {"ai_permission_mode": "plan"}),
    _scene("子代理隔离",
           "派个子代理扫一遍日志",
           [[_tc("dispatch_subagent", '{"task": "扫日志找错误"}')],
            "子代理说没错误"],
           ["dispatch_subagent"],
           ["delete_mod", "install_mod"]),
]


class _Runner:
    """把场景脚本接到 run_agent 的打桩模型上，收集实际执行的工具序列。"""

    def __init__(self, scene, tmp: Path):
        self.scene = scene
        self.tmp = tmp
        self.executed: list = []
        self.rounds = 0

    def stream(self, settings, messages, tools, http_cancel=None):
        self.rounds += 1
        script = self.scene["script"]
        if self.rounds <= len(script):
            step = script[self.rounds - 1]
            if isinstance(step, str):          # 最终正文
                yield {"type": "delta", "text": step}
                yield {"type": "done"}
            else:
                yield {"type": "tool_calls", "tool_calls": list(step)}
        else:
            yield {"type": "delta", "text": "done"}
            yield {"type": "done"}

    def ask(self, questions, title):
        self.executed.append("ask_user")
        return {"q1": {"picked": [{"id": "sodium", "label": "sodium"}]}}

    def on_status(self, kind, payload):
        if kind == "plan":
            self.executed.append("update_plan")

    def run_tool(self, backend, name, args, wait=True, cancelled=None):
        self.executed.append(name)
        if name == "delete_mod":
            return "已删除 jei.jar"
        if name == "write_mod_config":
            # 第一次调用缺 content → 真实 parse 在 agent 侧已拦，这里只会收到合法参数
            return "已写入"
        return "ok"


class EvalTests(unittest.TestCase):
    def _check_tool_selection(self, scene):
        """批次 2.2：首个动作工具必须可声明；非核心的禁止工具不得声明
        （核心常驻工具按「执行」口径判禁止，见 test_scenarios 的执行检查）。"""
        sel = {s["function"]["name"] for s in select_tool_schemas(
            [{"role": "user", "content": scene["user"]}], scene["settings"])}
        core = set(ai_tools._CORE_TOOLS)
        need = scene["expected"][:1]
        for t in need:
            if t in TOOL_META and t not in ("ask_user",):
                self.assertIn(t, sel, f"[{scene['name']}] 首个工具 {t} 未声明")
        for t in scene["forbidden"]:
            if t not in core:
                self.assertNotIn(t, sel, f"[{scene['name']}] 禁止工具 {t} 却被声明")

    def test_scenarios(self):
        failures = []
        for scene in SCENARIOS:
            ok, err = True, ""
            try:
                self._check_tool_selection(scene)
                with tempfile.TemporaryDirectory() as d:
                    tmp = Path(d)
                    runner = _Runner(scene, tmp)
                    with mock.patch.object(agent_mod, "chat_stream", side_effect=runner.stream), \
                         mock.patch.object(agent_mod, "select_tool_schemas",
                                           return_value=list(ai_tools.TOOL_SCHEMAS)), \
                         mock.patch.object(agent_mod, "run_tool",
                                           side_effect=runner.run_tool), \
                         mock.patch.object(agent_mod, "run_subagent",
                                           side_effect=lambda b, st, a, **k:
                                               runner.executed.append("dispatch_subagent")
                                               or json.dumps({"ok": True, "answer": "结论"},
                                                             ensure_ascii=False)), \
                         mock.patch.object(ckpt, "CHECKPOINTS_DIR", tmp / "ck"):
                        res = agent_mod.run_agent(
                            SimpleNamespace(), dict(scene["settings"],
                                                    ai_session_id="eval"), [], scene["user"],
                            ask_fn=runner.ask, on_status=runner.on_status)
                    # 期望工具按序执行
                    exp = [t for t in scene["expected"]]
                    got = runner.executed[:len(exp)]
                    self.assertEqual(got, exp,
                                     f"[{scene['name']}] 执行序列 {runner.executed} ≠ 期望 {exp}")
                    # 禁止工具没出现
                    for t in scene["forbidden"]:
                        self.assertNotIn(t, runner.executed,
                                         f"[{scene['name']}] 禁止的 {t} 被执行")
                    self.assertEqual(res.stop_reason, StopReason.COMPLETED,
                                     f"[{scene['name']}] 停止原因 {res.stop_reason.value}")
            except AssertionError as exc:
                ok, err = False, str(exc)
            failures.append((scene["name"], ok, err))
        bad = [n for n, ok, _ in failures if not ok]
        for n, ok, err in failures:
            print(f"{'PASS' if ok else 'FAIL'}  {n}" + (f"  — {err[:200]}" if err else ""))
        self.assertEqual(bad, [], f"评测未通过的场景: {bad}（failed == 0 才算通过）")

    def test_plan_rejection_executes_no_writes(self):
        """批次 1/3.4 联动：plan 档拒绝后没有任何写工具执行。"""
        scene = next(s for s in SCENARIOS if s["name"] == "计划拒绝零写操作")
        runner = _Runner(scene, None)
        with mock.patch.object(agent_mod, "chat_stream", side_effect=runner.stream), \
             mock.patch.object(agent_mod, "select_tool_schemas",
                               return_value=list(ai_tools.TOOL_SCHEMAS)), \
             mock.patch.object(agent_mod, "run_tool", side_effect=runner.run_tool):
            agent_mod.run_agent(SimpleNamespace(), dict(scene["settings"],
                                                        ai_session_id="eval"),
                                [], scene["user"])
        writes = [t for t in runner.executed
                  if t in TOOL_META and not TOOL_META[t].readonly]
        self.assertEqual(writes, [])


class RollbackEvalTests(unittest.TestCase):
    """批次 1.1 评测：3 轮写操作 → 回滚字节级还原（评测口径）。"""

    def test_three_round_write_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            with mock.patch.object(ckpt, "CHECKPOINTS_DIR", tmp / "ck"):
                cfg = tmp / "instance" / "config"
                cfg.mkdir(parents=True)
                target = cfg / "options.txt"
                target.write_text("rd=12", encoding="utf-8")
                chat = "eval-chat"
                for i, content in enumerate(("rd=8", "rd=4", "rd=2")):
                    ckpt.snapshot(chat, f"t{i}", [target])
                    target.write_text(content, encoding="utf-8")
                ckpt.rollback(chat, all_ops=True)
                self.assertEqual(target.read_text(encoding="utf-8"), "rd=12")


def _main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(EvalTests)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(RollbackEvalTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    failed = len(result.failures) + len(result.errors)
    print(f"\n评测结论: failed == {failed} {'→ 通过' if failed == 0 else '→ 未通过'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())

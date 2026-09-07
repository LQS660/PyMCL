# -*- coding: utf-8 -*-
"""AI 权限管理冒烟：设置持久化 → agent 确认分流 → AI 页 UI 联动。

全程用独立 PYMCL_HOME，不碰真实 config.json / ai_chats.json。
"""
import os
import sys
import tempfile

_home = tempfile.mkdtemp(prefix="pymcl_perm_smoke_")
os.environ["PYMCL_HOME"] = _home
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAIL = []


def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name, ("" if cond else str(extra)))
    if not cond:
        FAIL.append(name)


# ---------- 1) 设置读写（真实 BackendAPI 方法，self=None 契约） ----------
from app.backend import BackendAPI  # noqa: E402
from mclauncher.config import CONFIG  # noqa: E402

s = BackendAPI.get_settings(None)
check("默认开确认", s.get("ai_confirm_writes") is True, s.get("ai_confirm_writes"))
check("默认标准模式", s.get("ai_permission_mode") == "standard", s.get("ai_permission_mode"))

BackendAPI.save_settings(None, {"ai_confirm_writes": False, "ai_permission_mode": "full"})
s = BackendAPI.get_settings(None)
check("落盘 confirm off", s.get("ai_confirm_writes") is False, s.get("ai_confirm_writes"))
check("落盘 full", s.get("ai_permission_mode") == "full", s.get("ai_permission_mode"))

BackendAPI.save_settings(None, {"ai_confirm_writes": True})
s = BackendAPI.get_settings(None)
check("局部更新保住 full", s.get("ai_permission_mode") == "full", s.get("ai_permission_mode"))

BackendAPI.save_settings(None, {"ai_permission_mode": "bogus"})
check("非法模式归一 standard",
      BackendAPI.get_settings(None).get("ai_permission_mode") == "standard",
      BackendAPI.get_settings(None).get("ai_permission_mode"))

CONFIG.set("ai_confirm_writes", True)
CONFIG.set("ai_permission_mode", "standard")
CONFIG.save()

# ---------- 2) agent 写操作确认分流 ----------
import mclauncher.ai.agent as agent_mod  # noqa: E402

TOOL_CALLS = [
    {"id": "c1", "type": "function",
     "function": {"name": "install_game", "arguments": '{"version":"1.20.1"}'}},
    {"id": "c2", "type": "function",
     "function": {"name": "delete_instance", "arguments": '{"instance":"x"}'}},
    {"id": "c3", "type": "function",
     "function": {"name": "enable_mod", "arguments": '{"name":"n"}'}},
]


def run_agent_once(settings):
    calls, ran = [], []
    holder = {"n": 0, "messages": None}

    def fake_chat_stream(_st, messages, _tools, http_cancel=None):
        if holder["messages"] is None:
            holder["messages"] = messages
        holder["n"] += 1
        if holder["n"] == 1:
            yield {"type": "tool_calls",
                   "tool_calls": [dict(tc, function=dict(tc["function"])) for tc in TOOL_CALLS]}
        yield {"type": "delta", "text": "搞定"}
        yield {"type": "done", "finish_reason": "stop"}

    def fake_chat_once(_st, _messages, _tools, http_cancel=None):
        return {"content": "搞定", "tool_calls": [], "finish_reason": "stop"}

    def fake_run_tool(_backend, name, _args, wait=True, cancelled=None):
        ran.append(name)
        return '{"ok": true}'

    def confirm(name, _args, _label):
        calls.append(name)
        return True

    orig = (agent_mod.chat_stream, agent_mod.chat_once,
            agent_mod.run_tool, agent_mod.runtime_context)
    agent_mod.chat_stream = fake_chat_stream
    agent_mod.chat_once = fake_chat_once
    agent_mod.run_tool = fake_run_tool
    agent_mod.runtime_context = lambda _b: "stub-state"
    try:
        text = agent_mod.run_agent(object(), settings, [], "装一下", confirm_fn=confirm)
    finally:
        (agent_mod.chat_stream, agent_mod.chat_once,
         agent_mod.run_tool, agent_mod.runtime_context) = orig
    return calls, ran, text, holder["messages"]


# 标准模式：三个写工具全要确认
calls, ran, text, msgs = run_agent_once(BackendAPI.get_settings(None))
check("标准=全确认", calls == ["install_game", "delete_instance", "enable_mod"], calls)
check("标准模式提示词不带权限注记",
      not any("[权限设置]" in (m.get("content") or "") for m in msgs if m.get("role") == "system"))

# 完全访问：只有 delete_instance 要确认，其余直接执行
CONFIG.set("ai_permission_mode", "full")
CONFIG.save()
calls, ran, text, msgs = run_agent_once(BackendAPI.get_settings(None))
check("完全访问只确认破坏性", calls == ["delete_instance"], calls)
check("完全访问三个都执行（delete 是确认后执行）",
      set(ran) == {"install_game", "delete_instance", "enable_mod"}, ran)
check("完全访问注入权限注记",
      any("[权限设置]" in (m.get("content") or "") for m in msgs if m.get("role") == "system"))

# 关掉变更前确认：全都不确认
CONFIG.set("ai_confirm_writes", False)
CONFIG.save()
calls, ran, text, msgs = run_agent_once(BackendAPI.get_settings(None))
check("免确认零弹窗", calls == [], calls)
check("免确认全部直接执行", set(ran) == {"install_game", "delete_instance", "enable_mod"}, ran)
check("免确认注入权限注记",
      any("[权限设置]" in (m.get("content") or "") for m in msgs if m.get("role") == "system"))

CONFIG.set("ai_confirm_writes", True)
CONFIG.set("ai_permission_mode", "standard")
CONFIG.save()

# ---------- 3) AI 页 UI：快捷下拉 / 状态标签 / 面板 / 欢迎语 ----------
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

from app.pages import ai_page as ai_page_mod  # noqa: E402
from app.pages.ai_page import AiPage, PermissionDialog  # noqa: E402


class StubBackend(QObject):
    progress = Signal(str, int, int, str)
    finished = Signal(str, bool, str)

    def get_settings(self):
        return BackendAPI.get_settings(None)

    def save_settings(self, data):
        BackendAPI.save_settings(None, data)


backend = StubBackend()
page = AiPage(backend)
check("初始下拉=标准", page.perm_combo.currentIndex() == 0, page.perm_combo.currentIndex())
check("初始标签", page.perm_label.text() == "变更前确认：开", page.perm_label.text())

page.perm_combo.setCurrentIndex(1)
s = BackendAPI.get_settings(None)
check("下拉切完全访问", s.get("ai_permission_mode") == "full", s.get("ai_permission_mode"))
check("标签跟到完全访问", page.perm_label.text() == "完全访问中", page.perm_label.text())

page.perm_combo.setCurrentIndex(2)
s = BackendAPI.get_settings(None)
check("下拉切免确认", s.get("ai_confirm_writes") is False, s.get("ai_confirm_writes"))
check("标签跟到免确认", page.perm_label.text() == "免确认", page.perm_label.text())

page.perm_combo.setCurrentIndex(0)
s = BackendAPI.get_settings(None)
check("下拉切回标准", s.get("ai_confirm_writes") is True
      and s.get("ai_permission_mode") == "standard", s)

# 面板：开关和下拉立即落盘并回调刷新
fired = {"n": 0}
dlg = PermissionDialog(backend, on_changed=lambda: fired.__setitem__("n", fired["n"] + 1),
                       parent=page)
dlg.mode_box.setCurrentIndex(1)
check("面板下拉落盘 full", BackendAPI.get_settings(None).get("ai_permission_mode") == "full")
dlg.confirm_sw.setChecked(False)
check("面板开关落盘 confirm off",
      BackendAPI.get_settings(None).get("ai_confirm_writes") is False)
check("面板改动触发回调", fired["n"] == 2, fired["n"])
check("面板控件初值来自设置", dlg.confirm_sw.isChecked() is False)

# 欢迎语跟随确认开关
page2 = AiPage(backend)
bubbles = page2._host.findChildren(ai_page_mod.Bubble)
first = bubbles[0]._plain if bubbles else ""
check("免确认欢迎语", "不逐条询问" in first, first[:60])

BackendAPI.save_settings(None, {"ai_confirm_writes": True, "ai_permission_mode": "standard"})
page3 = AiPage(backend)
bubbles = page3._host.findChildren(ai_page_mod.Bubble)
first = bubbles[0]._plain if bubbles else ""
check("开确认欢迎语", "先让你确认" in first, first[:60])

print()
if FAIL:
    print("FAILED:", len(FAIL), FAIL)
    sys.exit(1)
print("ALL PASS")

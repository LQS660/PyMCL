# -*- coding: utf-8 -*-
"""run_agent 的返回对象：文本本体 + 停止原因。

AgentResult 是 str 的子类而不是纯 dataclass：run_agent 的返回值除了
app/pages/ai_page.py 还被 bridge/api.py 当纯文本消费（做 ``in`` / ``+`` /
JSON 序列化），桥接端不在本次改造范围内，str 兼容保证它一行都不用改。
"""

from __future__ import annotations

from enum import Enum


class StopReason(str, Enum):
    COMPLETED      = "completed"        # 模型主动收尾，没有待办
    NO_TOOL_CALL   = "no_tool_call"     # 用户要它动手（下载/安装/改配置）它却只说话；问答闲聊回文字算 COMPLETED
    MAX_ROUNDS     = "max_rounds"       # 撞到 MAX_TOOL_ROUNDS
    TRUNCATED      = "truncated"        # 输出撞 max_tokens
    PENDING_TASK   = "pending_task"     # 有后台任务还在跑
    STREAM_FAILED  = "stream_failed"    # 流式异常，走了非流式兜底
    EMPTY_RESPONSE = "empty_response"   # 上游返空
    RATE_LIMITED   = "rate_limited"     # 429
    CANCELLED      = "cancelled"        # 用户主动停止
    ERROR          = "error"


class AgentResult(str):
    """str 的子类：任何把 run_agent 返回值当文本用的旧代码都不受影响。"""

    def __new__(cls, text="", *, stop_reason=StopReason.COMPLETED, detail="",
                pending_tasks=None, rounds_used=0):
        obj = super().__new__(cls, text or "")
        obj.stop_reason = StopReason(stop_reason)
        obj.detail = str(detail or "")
        obj.pending_tasks = list(pending_tasks or [])
        obj.rounds_used = int(rounds_used)
        # run_agent 填：messages = 模型侧完整历史（不含 system）；
        # turn_messages = 只属于本回合的那一段（用户这句 + 工具轨迹 + 最终正文），
        # UI 往聊天记录里追加时用后者，别把旧历史再抄一遍。
        obj.messages = []
        obj.turn_messages = []
        # 3.4 本回合模型出的待办计划（run_agent 填实际内容；UI 持久化用）
        obj.plan = []
        return obj

    @property
    def text(self) -> str:
        return str(self)

    def __repr__(self) -> str:
        return (
            f"AgentResult(text={str(self)!r}, stop_reason={self.stop_reason.value!r}, "
            f"detail={self.detail!r}, rounds_used={self.rounds_used})"
        )

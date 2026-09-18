# -*- coding: utf-8 -*-
"""turn 状态机 + 工具调用状态（对齐 ZCode 的 turn 生命周期）。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class TurnPhase(str, Enum):
    IDLE = "idle"
    PROCESSING_INPUT = "processing_input"
    AWAITING_MODEL = "awaiting_model"
    STREAMING = "streaming"
    SCHEDULING_TOOLS = "scheduling_tools"
    EXECUTING_TOOLS = "executing_tools"
    AWAITING_PERMISSION = "awaiting_permission"
    COMPLETING = "completing"
    ERROR = "error"


ALLOWED = {
    TurnPhase.IDLE: {TurnPhase.PROCESSING_INPUT},
    TurnPhase.PROCESSING_INPUT: {TurnPhase.AWAITING_MODEL, TurnPhase.COMPLETING},
    TurnPhase.AWAITING_MODEL: {TurnPhase.STREAMING, TurnPhase.COMPLETING, TurnPhase.ERROR},
    TurnPhase.STREAMING: {TurnPhase.SCHEDULING_TOOLS, TurnPhase.COMPLETING, TurnPhase.ERROR},
    TurnPhase.SCHEDULING_TOOLS: {TurnPhase.EXECUTING_TOOLS, TurnPhase.AWAITING_PERMISSION,
                                 TurnPhase.COMPLETING},
    TurnPhase.EXECUTING_TOOLS: {TurnPhase.AWAITING_MODEL, TurnPhase.COMPLETING, TurnPhase.ERROR},
    TurnPhase.AWAITING_PERMISSION: {TurnPhase.EXECUTING_TOOLS, TurnPhase.COMPLETING,
                                    TurnPhase.ERROR},
    TurnPhase.COMPLETING: set(),
    TurnPhase.ERROR: set(),
}


class IllegalTransition(Exception):
    pass


class ToolCallStatus(str, Enum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    WAITING_PERMISSION = "waiting_permission"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    status: ToolCallStatus = ToolCallStatus.SCHEDULED
    result: str = ""
    error: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0

    def mark(self, status: ToolCallStatus, result: str = "", error: str = "") -> None:
        """所有状态变更都走这里，保证时间戳成对出现。"""
        if status == ToolCallStatus.RUNNING and not self.started_at:
            self.started_at = time.monotonic()
        if status in (ToolCallStatus.COMPLETED, ToolCallStatus.FAILED,
                      ToolCallStatus.DENIED):
            self.ended_at = time.monotonic()
        self.status = status
        if result:
            self.result = result
        if error:
            self.error = error


@dataclass
class TurnState:
    id: str
    session_id: str
    turn_number: int
    phase: TurnPhase = TurnPhase.IDLE
    tool_calls: list = field(default_factory=list)
    tool_results: list = field(default_factory=list)
    parallel_groups: list = field(default_factory=list)
    pending_inputs: list = field(default_factory=list)
    rounds_used: int = 0

    def transition(self, to: TurnPhase) -> None:
        if to not in ALLOWED[self.phase]:
            raise IllegalTransition(f"{self.phase.value} → {to.value}")
        self.phase = to

    def add_tool_call(self, tc: ToolCall) -> ToolCall:
        self.tool_calls.append(tc)
        return tc

    def set_tool_status(self, tc_id: str, status: ToolCallStatus,
                        result: str = "", error: str = "") -> ToolCall | None:
        tc = self.find_tool_call(tc_id)
        if tc is None:
            return None
        tc.mark(status, result=result, error=error)
        if status in (ToolCallStatus.COMPLETED, ToolCallStatus.FAILED,
                      ToolCallStatus.DENIED):
            self.tool_results.append({
                "tool_call_id": tc.id, "name": tc.name, "status": status.value,
                "result": tc.result, "error": tc.error,
                "duration": round(tc.ended_at - tc.started_at, 3) if tc.started_at else 0,
            })
        return tc

    def find_tool_call(self, tc_id: str) -> ToolCall | None:
        for tc in self.tool_calls:
            if tc.id == tc_id:
                return tc
        return None

    def status_trace(self) -> list:
        """每个 ToolCall 的完整状态轨迹（验收用）。"""
        return [{
            "id": tc.id, "name": tc.name, "status": tc.status.value,
            "result_len": len(tc.result), "error": tc.error,
            "started_at": tc.started_at, "ended_at": tc.ended_at,
        } for tc in self.tool_calls]


class StepOutcome(str, Enum):
    CONTINUE = "continue"                          # 还有工具要跑
    OUTPUT_CONTINUATION = "output_continuation"    # 输出被截断，要续写
    TURN_COMPLETED = "turn_completed"              # 真的结束

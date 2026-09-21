# -*- coding: utf-8 -*-
"""长期记忆接口（批次 3.5）：可插拔插槽，默认空实现。

插槽位置：``agent._system_messages`` 在系统提示词后追加 ``load(chat_id)`` 的
返回内容（非空时作为一段「长期记忆」system 消息）；回合结束不自动写——
``save`` 由具体实现自行决定何时调用（例如挂到 hooks 的 after 上）。

实现契约：
- ``load(chat_id) -> str``：取该对话的长期记忆文本，空串 = 无记忆；
- ``save(chat_id, text) -> None``：整体覆盖式保存；
- ``search(chat_id, query, k=3) -> list[str]``：按相关性取前 k 条，默认实现返回 []；
- 任何实现都必须不抛异常、不做网络 IO 阻塞主循环（由实现者保证）；
- 默认实现 NoopMemory 三方法全空：启用与否，模型请求 messages 逐字一致
  （tests/test_ai_plan_memory.py 钉死）。

换实现：``memory.set_memory(MyMemory())``（进程内一次性注入；future: config 挂载点）。
"""

from __future__ import annotations

import threading


class NoopMemory:
    """默认空实现：读空串、存丢弃、检索空列表——行为与没有记忆机制一致。"""

    def load(self, chat_id: str) -> str:
        return ""

    def save(self, chat_id: str, text: str) -> None:
        return None

    def search(self, chat_id: str, query: str, k: int = 3) -> list:
        return []


_memory = NoopMemory()
_LOCK = threading.Lock()


def get_memory() -> NoopMemory:
    """取当前记忆实现（默认 NoopMemory）。"""
    with _LOCK:
        return _memory


def set_memory(impl) -> None:
    """注入自定义实现；传 None 回到空实现。"""
    global _memory
    with _LOCK:
        _memory = impl if impl is not None else NoopMemory()

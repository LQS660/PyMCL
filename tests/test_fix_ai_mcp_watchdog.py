# -*- coding: utf-8 -*-
"""审计 05 P1-3 回归：MCP 看门狗不得在成功应答之后杀掉健康 server。

修前 `McpClient._recv` 的看门狗无条件 `kill()`：它只按 deadline 睡够就杀进程，
从不检查这次请求是否已经收到应答，也没有取消机制。于是一次成功调用之后整个回合
只要超过 CONNECT_TIMEOUT（10s），server 就被杀；`self._proc` 仍非 None，下一次
`_send` 写已关闭的管道 → OSError [Errno 22]，该 server 的所有工具在本回合永久失效。

修后看门狗可取消（threading.Event），`_recv` 拿到应答立刻置位；kill 只留给真正
的超时无响应。

全部离线：只用仓库自带 fixtures/mcp_echo_server.py，不起外部进程、不联网。
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

from mclauncher.ai import mcp as mcp_mod

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ECHO_SERVER = [sys.executable, str(FIXTURES / "mcp_echo_server.py")]


class WatchdogDoesNotKillHealthyServer(unittest.TestCase):
    def setUp(self):
        self.client = mcp_mod.McpClient("echo", ECHO_SERVER[0], ECHO_SERVER[1:])
        self.client.connect()
        self.addCleanup(self.client.close)

    def test_server_survives_a_successful_call(self):
        out = self.client.call_tool("echo", {"text": "hi"})
        self.assertEqual(out, "echo: hi")
        # 修前：成功返回后看门狗线程还在 sleep，10s 后无条件 kill
        time.sleep(mcp_mod.CONNECT_TIMEOUT + 1.5)
        self.assertIsNotNone(self.client._proc)
        self.assertIsNone(self.client._proc.poll(),
                          "成功调用之后健康 server 被看门狗杀了")
        # 之后再调必须还能用（修前这里是 OSError [Errno 22]）
        out2 = self.client.call_tool("echo", {"text": "again"})
        self.assertEqual(out2, "echo: again")

    def test_idle_between_calls_does_not_kill(self):
        self.client.list_tools()
        time.sleep(mcp_mod.CONNECT_TIMEOUT + 1.5)
        self.client.list_tools()
        self.assertIsNone(self.client._proc.poll())

    def test_watchdog_still_kills_a_silent_server(self):
        """真正的超时必须仍然生效：server 活着但不回话 → 看门狗杀它并报超时。"""
        client = mcp_mod.McpClient("silent", ECHO_SERVER[0], ECHO_SERVER[1:])
        client.connect()
        try:
            with self.assertRaises(mcp_mod.McpError) as cm:
                client._recv(999999, 0.5)
            self.assertIn("超时", str(cm.exception))
            # Windows 上 TerminateProcess 到 poll() 看到退出码有极短延迟
            deadline = time.time() + 5
            while time.time() < deadline and client._proc.poll() is None:
                time.sleep(0.05)
            self.assertIsNotNone(client._proc.poll(),
                                 "超时场景下看门狗没有杀掉 server")
        finally:
            client.close()

    def test_close_is_clean(self):
        self.client.call_tool("echo", {"text": "x"})
        self.client.close()
        self.assertIsNone(self.client._proc)


class WatchdogInternalsAreCancellable(unittest.TestCase):
    """结构契约：_recv 用 Event 通知看门狗「应答已到」，不再裸 sleep 到底。"""

    def test_recv_sets_cancel_event(self):
        src = Path(mcp_mod.__file__).read_text(encoding="utf-8")
        self.assertIn("threading.Event", src,
                      "_recv 的看门狗没有可取消机制")
        self.assertIn("set()", src)


if __name__ == "__main__":
    unittest.main()

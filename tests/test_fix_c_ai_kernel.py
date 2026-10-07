# -*- coding: utf-8 -*-
"""审计 05 P1-4 / P1-5 回归（C 内核）：起真 C 桥 + 脚本化 mock 模型，走真 HTTP/SSE。

P1-4：`diagnose_launch` / `scan_mod_conflicts` 在 tools.py 的 _CORE_TOOLS 里每轮常驻
声明，C 版 `ai_run_tool` 却没有分支 → 一定返回「未知工具」。修后两者有原生实现，
返回结构化 JSON（has_latest / findings / issues / issue_count …）。
断言口径：模型调用这两个工具后，tool 回执里不许出现「未知工具」，且必须带真实内容。

P1-5：C 版 `read_artifact` 把 artifact_id 直接拼进路径，`../../config.json` 可读到
root 下任意文件。修后照 Python 版 artifacts.py:96-106 的护栏拒绝。

全部离线：mock 模型与桥都在 127.0.0.1 上，不联网。
"""
from __future__ import annotations

import json
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "native" / "build" / "pymcl-bridge-nopy.exe"
MOCK_SERVER = ROOT / "tests" / "fixtures" / "ai_mock_openai.py"
MOCK_PORT = 18873
MOCK_URL = f"http://127.0.0.1:{MOCK_PORT}"


def _have_exe() -> bool:
    return EXE.is_file()


class _Bridge:
    """起一个真 C 桥（nopy 构建）+ SSE 订阅。"""

    def __init__(self, root: Path):
        self.root = root
        self.token = secrets.token_urlsafe(32)
        self.proc = subprocess.Popen(
            [str(EXE), "--root", str(root), "--host", "127.0.0.1", "--port", "0",
             "--token", self.token],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", cwd=str(root))
        self.port = None
        for _ in range(300):
            line = self.proc.stdout.readline()
            if not line:
                break
            for part in line.split():
                if part.startswith("port="):
                    self.port = int(part.split("=", 1)[1])
            if self.port:
                break
        if not self.port:
            self.close()
            raise RuntimeError("C 桥没起来")
        self.events: list[dict] = []
        self._lock = threading.Lock()
        self._sse = threading.Thread(target=self._read_sse, daemon=True)
        self._sse.start()

    def _read_sse(self):
        url = f"http://127.0.0.1:{self.port}/events?token={self.token}"
        try:
            with urllib.request.urlopen(url, timeout=None) as resp:
                event, data = None, None
                for raw in resp:
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    if line.startswith("event:"):
                        event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        try:
                            data = json.loads(line.split(":", 1)[1])
                        except ValueError:
                            data = None
                    elif line == "" and event:
                        with self._lock:
                            self.events.append({"event": event, "data": data})
                        event, data = None, None
        except Exception:  # noqa: BLE001
            pass

    def wait_events(self, timeout: float = 90) -> list[dict]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if any(e["event"] in ("ai.done", "ai.fail") for e in self.events):
                    return list(self.events)
            time.sleep(0.15)
        with self._lock:
            return list(self.events)

    def call(self, method, params=None, timeout=60):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                           "params": params or {}}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/rpc", data=body,
            headers={"Content-Type": "application/json",
                     "X-PyMCL-Bridge-Token": self.token})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def close(self):
        try:
            if self.proc.poll() is None:
                self.proc.kill()
                self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            pass


class _MockModel:
    """脚本化 OpenAI mock：按脚本逐轮回 tool_calls / 正文。"""

    def __init__(self, root: Path, rows: list[dict]):
        self.script = root / "mock_script.json"
        self.script.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-u", str(MOCK_SERVER), "--port", str(MOCK_PORT),
             "--script", str(self.script)],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        for _ in range(80):
            try:
                urllib.request.urlopen(f"{MOCK_URL}/served", timeout=1).read()
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass


def _write_mod(path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("fabric.mod.json", json.dumps(meta))


def _tool_rows(events: list[dict]) -> list[str]:
    """取工具回执正文：优先 ai.status 的 tool_done.result（内核直接产出），
    退回 ai.done 的 store 里的 tool 消息。"""
    rows = []
    for e in events:
        if e["event"] != "ai.status":
            continue
        data = e.get("data") or {}
        if data.get("kind") == "tool_done" and data.get("result"):
            rows.append(str(data["result"]))
    if rows:
        return rows
    for e in events:
        if e["event"] == "ai.done" and isinstance(e.get("data"), dict):
            store = e["data"].get("store") or {}
            for chat in store.get("chats") or []:
                for m in chat.get("messages") or []:
                    if isinstance(m, dict) and m.get("role") == "tool":
                        rows.append(str(m.get("content") or ""))
    return rows


def _setup_single_root(root: Path) -> Path:
    """按单目录模式布置 root（与 tests/fixtures/build_parity_root.py 同口径）：
    `instances_dir` 指向 `.minecraft`，游戏目录本身就是实例，`.instance.json`
    是单目录模式的判据（native/src/instances.c:100 instance_single_root_mode）。"""
    inst = root / ".minecraft"
    (inst / "logs").mkdir(parents=True)
    (inst / ".instance.json").write_text(
        json.dumps({"name": ".minecraft", "mc_version": None, "modpack": None,
                    "java": "自动选择"}, ensure_ascii=False), encoding="utf-8")
    (root / "config.json").write_text(json.dumps({
        "instances_dir": ".minecraft",
        "default_instance": "",
    }), encoding="utf-8")
    return inst


class _CToolCase(unittest.TestCase):
    """共用：临时 root + mock 模型 + C 桥。"""

    TOOL_NAME = ""
    TOOL_ARGS = "{}"
    MOCK_FIRST = ""

    def _setup_root(self, root: Path) -> None:
        raise NotImplementedError

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.inst = _setup_single_root(self.root)
        self._setup_root(self.root)
        cfgp = self.root / "config.json"
        cfg = json.loads(cfgp.read_text(encoding="utf-8"))
        cfg.update({
            "ai_mode": "custom",
            "ai_base_url": f"{MOCK_URL}/v1",
            "ai_api_key": "mock-key",
            "ai_permission_mode": "yolo",
            "ai_confirm_writes": True,
        })
        cfgp.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        self.mock = _MockModel(self.root, [
            {"tool_calls": [{"id": "call_1", "name": self.TOOL_NAME,
                             "arguments": self.TOOL_ARGS}]},
            {"deltas": ["工具跑完了"]},
            {"deltas": ["（这条不该被请求）"]},
        ])
        self.bridge = _Bridge(self.root)

    def tearDown(self):
        self.bridge.close()
        self.mock.close()
        self._tmp.cleanup()

    def _run_turn(self, user_text: str) -> list[str]:
        # 上一轮的 busy 释放与下一次 ai_send 之间可能有极短窗口，重试几次
        last = None
        for _ in range(60):
            r = self.bridge.call("ai_send", {"text": user_text})
            last = r
            res = r.get("result") or {}
            if res.get("ok"):
                break
            if "还在处理" not in str(res.get("message") or ""):
                break
            time.sleep(0.5)
        res = (last or {}).get("result") or {}
        self.assertTrue(res.get("ok"),
                        f"ai_send 没起来：{json.dumps(last, ensure_ascii=False)[:300]}")
        events = self.bridge.wait_events(90)
        names = [e["event"] for e in events]
        self.assertIn("ai.done", names, f"没等到 ai.done：{names}")
        rows = _tool_rows(events)
        self.assertTrue(rows, f"没拿到工具回执：{json.dumps(events, ensure_ascii=False)[:600]}")
        return rows


@unittest.skipUnless(_have_exe(), "没编过 native/build/pymcl-bridge-nopy.exe，跳过 C 侧真跑")
class DiagnoseLaunchInC(_CToolCase):
    TOOL_NAME = "diagnose_launch"
    TOOL_ARGS = '{"instance": "default"}'

    def _setup_root(self, root: Path) -> None:
        inst = self.inst
        (inst / "crash-reports").mkdir(parents=True, exist_ok=True)
        (inst / "logs" / "latest.log").write_text(
            "[12:00:00] [main/INFO]: Loading Minecraft 1.20.1\n"
            "[12:00:01] [main/ERROR]: java.lang.OutOfMemoryError: Java heap space\n",
            encoding="utf-8")
        (inst / "crash-reports" / "crash-2026-01-01_00.00.00-client.txt").write_text(
            "---- Minecraft Crash Report ----\n"
            "java.lang.OutOfMemoryError: Java heap space\n", encoding="utf-8")

    def test_diagnose_launch_has_real_implementation(self):
        rows = self._run_turn("启动闪退了帮我看")
        body = "\n".join(rows)
        self.assertNotIn("未知工具", body,
                         f"C 版 diagnose_launch 落到「未知工具」：{body[:400]}")
        self.assertIn("has_latest", body, f"没有结构化回执：{body[:400]}")
        self.assertIn("oom", body, f"OOM 规则没命中：{body[:600]}")
        self.assertIn("true", body.lower(), f"has_latest 不为真：{body[:400]}")


@unittest.skipUnless(_have_exe(), "没编过 native/build/pymcl-bridge-nopy.exe，跳过 C 侧真跑")
class ScanModConflictsInC(_CToolCase):
    TOOL_NAME = "scan_mod_conflicts"
    TOOL_ARGS = '{"instance": "default"}'

    def _setup_root(self, root: Path) -> None:
        inst = self.inst
        (inst / "mods").mkdir(parents=True, exist_ok=True)
        _write_mod(inst / "mods" / "sodium.jar",
                   {"id": "sodium", "name": "Sodium", "version": "0.5.8",
                    "depends": {"minecraft": "1.20.1", "fabric-api": "*"}})
        _write_mod(inst / "mods" / "sodium-copy.jar",
                   {"id": "sodium", "name": "Sodium Copy", "version": "0.5.8"})

    def test_scan_mod_conflicts_has_real_implementation(self):
        rows = self._run_turn("帮我扫一下模组冲突")
        body = "\n".join(rows)
        self.assertNotIn("未知工具", body,
                         f"C 版 scan_mod_conflicts 落到「未知工具」：{body[:400]}")
        self.assertIn("issue_count", body, f"没有结构化回执：{body[:400]}")
        self.assertIn("duplicate_id", body, f"重复 id 没报：{body[:600]}")
        self.assertIn("missing_dep", body, f"缺依赖没报：{body[:600]}")


@unittest.skipUnless(_have_exe(), "没编过 native/build/pymcl-bridge-nopy.exe，跳过 C 侧真跑")
class ReadArtifactGuardInC(_CToolCase):
    """P1-5：artifact_id 不许逃出 cache/ai_results/。"""

    def _setup_root(self, root: Path) -> None:
        (root / "cache" / "ai_results").mkdir(parents=True, exist_ok=True)
        (root / "cache" / "ai_results" / "ok-20260101-000000-abcdef.txt").write_text(
            "ARTIFACT-BODY-MARKER\nline2\n", encoding="utf-8")

    def _run_with_id(self, artifact_id: str) -> list[str]:
        # 每个用例重建 mock 脚本（工具名不同）
        self.TOOL_NAME = "read_artifact"
        self.mock.close()
        self.mock = _MockModel(self.root, [
            {"tool_calls": [{"id": "call_1", "name": "read_artifact",
                             "arguments": json.dumps({"artifact_id": artifact_id})}]},
            {"deltas": ["读完了"]},
            {"deltas": ["（不该到这）"]},
        ])
        return self._run_turn("回读一下那个 artifact")

    def test_normal_artifact_still_reads(self):
        body = "\n".join(self._run_with_id("ok-20260101-000000-abcdef.txt"))
        self.assertIn("ARTIFACT-BODY-MARKER", body, f"正常 artifact 读不到：{body[:300]}")

    def test_escape_ids_are_rejected(self):
        for bad in ["../../config.json", "..\\..\\config.json", "sub/x.txt", "..",
                    "a:b.txt"]:
            with self.subTest(artifact_id=bad):
                body = "\n".join(self._run_with_id(bad))
                self.assertNotIn("ai_api_key", body,
                                 f"{bad!r} 读到了 root 下的敏感文件：{body[:300]}")
                self.assertIn("无效的 artifact 名", body,
                              f"{bad!r} 没被护栏拒绝：{body[:300]}")


if __name__ == "__main__":
    unittest.main()

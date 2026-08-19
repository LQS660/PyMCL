# -*- coding: utf-8 -*-
"""桥接自测：真实调用 get_instances / fetch_version_list / search_mods / 安装任务。"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["PYMCL_HOME"] = str(ROOT)
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def rpc(port: int, method: str, params=None, timeout=120):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/rpc",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("error"):
        raise RuntimeError(data["error"].get("message") or data["error"])
    return data.get("result")


def main():
    from bridge.api import BackendAPI, EventBus

    bus = EventBus()
    events = []
    q = bus.subscribe()
    api = BackendAPI(bus)

    insts = api.get_instances()
    print("INSTANCES", json.dumps(insts, ensure_ascii=False)[:500])
    assert insts, "get_instances empty"

    vers = api.get_version_list()
    print("VERSION_CACHE", len(vers))
    fetched = api.fetch_version_list()
    print("VERSION_FETCH", len(fetched))
    assert fetched, "fetch_version_list empty"

    mods = api.search_mods("sodium", "Modrinth")
    print("MODS", len(mods), (mods[0].get("name") if mods else None))
    assert mods, "search_mods empty"

    # 已缓存/已装版本走真实 Installer，不假装成功
    target = None
    for row in fetched:
        if row.get("version") in ("25w36a", "1.19.2", "1.21.1", "1.20.1"):
            target = row["version"]
            break
    if target is None and fetched:
        target = fetched[0]["version"]
    tid = api.install_game(target, instance=insts[0]["name"])
    print("TASK", tid, "install", target)
    deadline = time.time() + 90
    saw_progress = False
    finished = None
    cancelled = False
    while time.time() < deadline:
        try:
            ev = q.get(timeout=1)
        except Exception:
            continue
        events.append(ev)
        name = ev.get("event")
        data = ev.get("data") or {}
        print("EVENT", name, json.dumps(data, ensure_ascii=False)[:200])
        if name == "progress":
            saw_progress = True
            if not cancelled:
                api.cancel_task(tid)
                cancelled = True
                print("CANCELLED", tid)
        if name == "finished" and data.get("task_id") == tid:
            finished = data
            break
    print("SAW_PROGRESS", saw_progress, "FINISHED", finished)
    assert saw_progress or finished, "install task produced no events"
    print("SELFTEST_OK")


if __name__ == "__main__":
    main()

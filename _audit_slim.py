# -*- coding: utf-8 -*-
"""End-to-end audit for slim C bridge + www launch path."""
from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\Downloads\新建文件夹 (5)")
EXE = ROOT / "native" / "build" / "pymcl-bridge.exe"
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = ""):
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def main():
    td = Path(tempfile.mkdtemp(prefix="pymcl-audit-"))
    try:
        shutil.copytree(ROOT / "eziapp" / "dist", td / "www")
        cfg = td / "www" / "bridge-config.json"
        if cfg.exists():
            cfg.unlink()
        (td / "native" / "data").mkdir(parents=True)
        shutil.copy2(ROOT / "native" / "data" / "catalog.json", td / "native" / "data" / "catalog.json")
        # mimic packaged DLL layout next to bridge for PATH test (optional)
        build = ROOT / "native" / "build"
        token = secrets.token_urlsafe(32)
        p = subprocess.Popen(
            [str(EXE), "--root", str(td), "--host", "127.0.0.1", "--port", "0", "--token", token],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(build),
        )
        line = p.stdout.readline().strip()
        check("banner", "PYMCL_BRIDGE port=" in line, line)
        port = int([x.split("=", 1)[1] for x in line.split() if x.startswith("port=")][0])

        # /health must work WITHOUT token (stub health check)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
                body = json.loads(r.read().decode())
                check("health_no_auth", r.status == 200 and body.get("ok") is True, str(body))
        except Exception as e:
            check("health_no_auth", False, str(e))

        # www index
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as r:
                html = r.read()
                check("www_index", b"<!doctype html>" in html.lower() or b"<html" in html.lower(), f"len={len(html)}")
        except Exception as e:
            check("www_index", False, str(e))

        # dynamic bridge-config
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/bridge-config.json", timeout=3) as r:
                cfgj = json.loads(r.read().decode())
                check(
                    "bridge_config",
                    cfgj.get("token") == token and f":{port}" in cfgj.get("rpc_url", ""),
                    str(cfgj)[:120],
                )
        except Exception as e:
            check("bridge_config", False, str(e))

        # rpc without token must 401
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/rpc",
                data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "get_instances", "params": {}}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
            check("rpc_requires_auth", False, "expected 401")
        except urllib.error.HTTPError as e:
            check("rpc_requires_auth", e.code == 401, f"code={e.code}")
        except Exception as e:
            check("rpc_requires_auth", False, str(e))

        # rpc with token
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/rpc",
                data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "get_instances", "params": {}}).encode(),
                headers={"Content-Type": "application/json", "X-PyMCL-Bridge-Token": token},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                js = json.loads(r.read().decode())
                check("rpc_with_token", "result" in js and "error" not in js, str(js)[:100])
        except Exception as e:
            check("rpc_with_token", False, str(e))

        p.terminate()
        try:
            p.wait(timeout=3)
        except Exception:
            p.kill()
    finally:
        shutil.rmtree(td, ignore_errors=True)

    # packaged exe size
    exe = ROOT / "dist" / "PyMCL.exe"
    if exe.exists():
        mb = exe.stat().st_size / 1024 / 1024
        check("exe_under_5mb", exe.stat().st_size <= 5 * 1024 * 1024, f"{mb:.2f}MB")
    else:
        check("exe_under_5mb", False, "missing")

    print("SUMMARY", "PASS" if not FAILS else f"FAIL {FAILS}")
    raise SystemExit(0 if not FAILS else 1)


if __name__ == "__main__":
    main()

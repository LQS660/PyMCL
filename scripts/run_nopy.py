# -*- coding: utf-8 -*-
"""无 Python 环境运行器（GOAL 第 4 节 E 的四个条件，可重复执行，一键恢复）。

    python scripts/run_nopy.py                 # 起 nopy 桥 + 冒烟 + 恢复原状
    python scripts/run_nopy.py --shell         # 附加：进一个"无 Python"的 cmd 子壳（手动调试用）

四条件对应实现：
  1. where python 无结果      —— 子进程 PATH 清洗：剔除含 python 的目录
  2. PYMCL_PYTHON 未设        —— 子进程环境删除该变量
  3. .workbuddy python 不可达 —— 临时改名（后缀 .run-nopy-hidden），finally 恢复；
                                  启动时若发现上次残留的改名目录会先自动还原
  4. root 无 bridge/mclauncher —— 临时目录 %TEMP%\\pymcl-nopy-root 天然满足

被测对象是 native\\build\\pymcl-bridge-nopy.exe（缺失时自动 native\\build.bat nopy）。
本脚本自身依赖 Python 没有关系——它只是环境搭建器，被测的桥进程才是"无 Python"的。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKBUDDY = Path(r"C:\Users\Administrator\.workbuddy\binaries\python")
HIDE_SUFFIX = ".run-nopy-hidden"
NOPY_EXE = ROOT / "native" / "build" / "pymcl-bridge-nopy.exe"
BUILD_BAT = ROOT / "native" / "build.bat"
PORT = 18799
TOKEN = "run-nopy-smoke-0123456789abcdef0123456789"


def clean_env() -> dict:
    """条件 1+2：PATH 去 python、删 PYMCL_PYTHON。"""
    env = dict(os.environ)
    env.pop("PYMCL_PYTHON", None)
    keep = []
    for p in env.get("PATH", "").split(os.pathsep):
        pl = p.lower()
        if "python" in pl or "pymcl" in pl:
            continue
        d = Path(p) if p.strip() else None
        if d and d.is_dir():
            hit = any(x.name.lower() in ("python.exe", "python3.exe", "python.bat", "pythonw.exe")
                      for x in d.iterdir() if x.is_file())
            if hit:
                continue
        keep.append(p)
    env["PATH"] = os.pathsep.join(keep)
    return env


def verify_no_python(env: dict) -> list:
    problems = []
    r = subprocess.run(["where", "python"], env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    if r.returncode == 0 and r.stdout.strip():
        problems.append(f"where python 仍可见: {r.stdout.strip()}")
    if env.get("PYMCL_PYTHON"):
        problems.append("PYMCL_PYTHON 仍设置")
    if WORKBUDDY.exists():
        problems.append(f"{WORKBUDDY} 仍可访问")
    return problems


def hide_workbuddy() -> Path | None:
    """条件 3：改名隐藏，返回备份路径（None=本来就不存在）。"""
    if not WORKBUDDY.exists():
        return None
    hidden = WORKBUDDY.with_name(WORKBUDDY.name + HIDE_SUFFIX)
    if hidden.exists():  # 上次异常退出的残留
        shutil.rmtree(hidden, ignore_errors=True)
    os.rename(WORKBUDDY, hidden)
    return hidden


def restore_workbuddy(hidden: Path | None) -> None:
    if hidden is None:
        return
    if WORKBUDDY.exists():
        return  # 期间有人重建了目录，不动
    os.rename(hidden, WORKBUDDY)


def ensure_nopy() -> None:
    if NOPY_EXE.exists():
        return
    subprocess.run(["cmd", "/c", str(BUILD_BAT), "nopy"], cwd=BUILD_BAT.parent,
                   check=True, capture_output=True)


def rpc(env: dict, root: Path, method: str, params: dict):
    body = json.dumps({"method": method, "params": params}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/rpc", data=body,
                                 headers={"Content-Type": "application/json",
                                          "X-PyMCL-Bridge-Token": TOKEN})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


SMOKE = [("get_language", {}), ("available_languages", {}), ("list_themes", {})]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shell", action="store_true", help="起一个无 Python 的 cmd 子壳供手动调试")
    args = ap.parse_args()

    ensure_nopy()
    env = clean_env()
    root = Path(tempfile.gettempdir()) / "pymcl-nopy-root"
    root.mkdir(parents=True, exist_ok=True)  # 临时 root：无 bridge/ 无 mclauncher（条件 4）

    hidden = None
    proc = None
    failed = False
    try:
        hidden = hide_workbuddy()
        problems = verify_no_python(env)
        if problems:
            for p in problems:
                print(f"[run_nopy] FAIL 环境条件不满足: {p}")
            failed = True

        if not failed:
            exe = str(NOPY_EXE)
            proc = subprocess.Popen(
                [exe, "--root", str(root), "--host", "127.0.0.1",
                 "--port", str(PORT), "--token", TOKEN],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[run_nopy] nopy 桥已启动 pid={proc.pid} root={root}")

            ok = False
            for _ in range(50):
                try:
                    rpc(env, root, "get_language", {})
                    ok = True
                    break
                except Exception:
                    time.sleep(0.2)
            if not ok:
                print("[run_nopy] FAIL 桥 10s 内未就绪")
                failed = True

            if not failed:
                for method, params in SMOKE:
                    try:
                        out = rpc(env, root, method, params)
                        result = out.get("result")
                        print(f"[run_nopy] 冒烟 {method}: PASS -> {json.dumps(result, ensure_ascii=False)[:80]}")
                    except Exception as e:
                        print(f"[run_nopy] 冒烟 {method}: FAIL {e}")
                        failed = True

        if args.shell and not failed:
            print("[run_nopy] 进入无 Python 子壳（exit 退出后自动恢复环境）")
            subprocess.run(["cmd", "/k", f"title run-nopy shell & echo PATH已去python, PYMCL_PYTHON已删, workbuddy已改名"], env=env)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        restore_workbuddy(hidden)
        shutil.rmtree(root, ignore_errors=True)
        print("[run_nopy] 已恢复原状（桥进程结束、workbuddy 还名、临时 root 清理）")

    print(f"[run_nopy] 结果: {'FAIL' if failed else 'ALL PASS'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

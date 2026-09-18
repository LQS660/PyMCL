# -*- coding: utf-8 -*-
"""把仓库根那几支离屏门禁脚本纳入 pytest。

`_bg_probe.py` / `_sidebar_check.py` / `_export_check.py` …… 各自是一份能重复跑的
回归（壁纸、C 方案侧栏、单目录迁移、内容导出、版本页、整合包拖放、打包 excludes），
但一直散在仓库根、靠人手一支一支敲。这里**不搬代码、不改脚本**，只做三件事：

1. 子进程跑它，**看判定行、不看退出码**——离屏 Qt 在解释器收场时偶尔踩
   0xC0000005 把退出码盖掉（HEAD 上就有），只有脚本自己打印的那行结论可信。
2. 每支脚本跑前跑后对仓库根 ``config.json`` 取 SHA256，一个字节都不许变——
   冒烟脚本一旦直写真配置就会把用户设置写坏，这一条把「不许碰真配置」变成机器判的。
3. 加超时并强杀整棵进程树——离屏下任何能弹出模态框的路径都是死锁，别让
   pytest 跟着一起挂；判定行已经打出来、只是退出那一步卡住的，照样算过。

慢的 ``_layout_smoke.py``（47 项、两分钟起步）默认跳过，``PYMCL_SLOW_CHECKS=1`` 才跑；
跑时按 ``PYMCL_LAYOUT_SMOKE_MAX_FAIL``（默认 0：全绿是基线）做棘轮，红项只许少不许多。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REAL_CONFIG = ROOT / "config.json"

# 脚本自己不隔离配置时，由这段引导把 CONFIG_FILE 改绑到临时目录再跑它：
# 起点仍是用户真实设置（first_run 天然为 False，不会撞上首启向导），之后
# 每一次 save() 只落临时那份。写法与 tests/test_nav_unpin.py、_bg_probe.py 一致。
_REBIND_BOOTSTRAP = (
    "import runpy, sys; from pathlib import Path;"
    "sys.path.insert(0, {root!r});"
    "from mclauncher import config as _c;"
    "_c.CONFIG_FILE = Path({cfg_dir!r}) / 'config.json';"
    "_c.CONFIG.save();"
    "runpy.run_path({script!r}, run_name='__main__')"
)


@dataclass(frozen=True)
class Gate:
    script: str
    verdict: str                 # 必须出现在输出里的判定行（正则，多行模式）
    timeout: int = 180           # 秒；到点强杀整棵进程树
    rebind_config: bool = False  # 脚本自己没隔离配置 → 用 _REBIND_BOOTSTRAP 包一层
    slow: bool = False           # 默认跳过，PYMCL_SLOW_CHECKS=1 才跑


GATES = [
    Gate("_bg_probe.py", r"^BG PROBE OK \(0 failures\)"),
    Gate("_bg_visual.py", r"^VISUAL OK"),
    # 只判它跑得通（数字随机器浮动，不做阈值），免得改壁纸那条链时探针先烂掉
    Gate("_bg_perf.py", r"^PERF OK"),
    Gate("_sidebar_check.py", r"^全部通过"),
    Gate("_single_root_check.py", r"^全部通过"),
    Gate("_export_check.py", r"^全部通过"),
    Gate("_version_page_smoke.py", r"^SMOKE_OK"),
    Gate("_refactor_audit.py", r"^共 \d+ 个检查点，全部在盘上"),
    Gate("_excludes_check.py", r"^全部通过"),
    # 它直接建 MainWindow，拿用户真配置跑会把配置迁掉；这里包一层改绑。
    Gate("_modpack_drop_smoke.py", r"^ALL PASS", rebind_config=True),
    # 47 项、两分钟起步：只在显式要求时跑，且按棘轮判。
    Gate("_layout_smoke.py", r"^(ALL PASS|TOTAL \d+\s+PASS \d+\s+FAIL \d+)", timeout=900, slow=True),
]


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                       capture_output=True, check=False)
    else:  # pragma: no cover - 这个仓库只在 Windows 上跑门禁
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def _run_gate(gate: Gate) -> tuple[str, int | None, float, bool]:
    """跑一支脚本，返回 (输出, 退出码或 None, 用时秒, 是否被超时强杀)。

    输出直接落临时文件而不是走管道：不用起线程读，也不会因为管道塞满把
    子进程憋住；判定行打印之后进程卡在退出那一步时，文件里的内容照样在。
    """
    script = ROOT / gate.script
    cfg_dir: str | None = None
    if gate.rebind_config:
        cfg_dir = tempfile.mkdtemp(prefix="pymcl-gate-cfg-")
        cmd = [sys.executable, "-u", "-c",
               _REBIND_BOOTSTRAP.format(root=str(ROOT), script=str(script), cfg_dir=cfg_dir)]
    else:
        cmd = [sys.executable, "-u", str(script)]

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")

    started = time.monotonic()
    killed = False
    with tempfile.NamedTemporaryFile(prefix="pymcl-gate-out-", suffix=".txt",
                                     delete=False) as out:
        out_path = Path(out.name)
    try:
        with open(out_path, "wb") as fh:
            proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env,
                                    stdout=fh, stderr=subprocess.STDOUT)
            try:
                code: int | None = proc.wait(timeout=gate.timeout)
            except subprocess.TimeoutExpired:
                killed = True
                _kill_tree(proc.pid)
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    pass  # 卡死在 ExitProcess 的那种，连 taskkill 都收不掉；不等它
                code = None
        text = out_path.read_text(encoding="utf-8", errors="replace")
    finally:
        try:
            out_path.unlink()
        except OSError:
            pass
        if cfg_dir:
            shutil.rmtree(cfg_dir, ignore_errors=True)
    return text, code, time.monotonic() - started, killed


def _tail(text: str, n: int = 25) -> str:
    lines = text.rstrip().splitlines()
    return "\n".join(lines[-n:])


@pytest.mark.parametrize("gate", GATES, ids=[g.script for g in GATES])
def test_root_check(gate: Gate):
    if gate.slow and not os.environ.get("PYMCL_SLOW_CHECKS"):
        pytest.skip(f"{gate.script} 慢（两分钟起步），PYMCL_SLOW_CHECKS=1 才跑")
    assert (ROOT / gate.script).is_file(), (
        f"{gate.script} 不在仓库根了——它是保留的门禁脚本之一，清理目录时不能删")

    before = _sha256(REAL_CONFIG)
    text, code, secs, killed = _run_gate(gate)
    after = _sha256(REAL_CONFIG)

    # 1) 真配置一个字节都不许动。放在判定行之前：就算脚本自己报 OK，写了用户配置也算挂。
    assert before == after, (
        f"{gate.script} 改了仓库根的真 config.json（跑前 {before} → 跑后 {after}）。"
        f"脚本必须把 CONFIG_FILE 改绑到临时目录或整个 PYMCL_HOME 重定向。")

    # 2) 判定行。
    m = re.search(gate.verdict, text, re.M)
    assert m, (
        f"{gate.script} 没打出判定行 /{gate.verdict}/"
        f"（{'超时 %ds 被强杀' % gate.timeout if killed else 'exit=%s' % code}，用时 {secs:.1f}s）。\n"
        f"输出末尾：\n{_tail(text)}")

    # 3) _layout_smoke 的棘轮：红项只许少不许多。
    if gate.script == "_layout_smoke.py" and not m.group(0).startswith("ALL PASS"):
        fails = int(re.search(r"FAIL (\d+)", m.group(0)).group(1))
        allowed = int(os.environ.get("PYMCL_LAYOUT_SMOKE_MAX_FAIL", "0"))
        failed_line = next((ln for ln in text.splitlines() if ln.startswith("FAILED:")), "")
        assert fails <= allowed, (
            f"_layout_smoke.py 红了 {fails} 项，超过基线 {allowed}。{failed_line}")

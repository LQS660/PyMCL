# -*- coding: utf-8 -*-
"""审计 #1 P1-5 回归：`run_hook` 用 `shell=True` 执行版本设置里的 pre/post_launch。

修前 `subprocess.run(cmd, shell=True)` 把版本设置里的字符串整条交给 cmd.exe：
`&`、`|`、`>` 都是 shell 语法，任何能写到版本设置（或经 P0-2 穿越写到游戏目录外
pymcl.json）的人都能拿到启动器权限下的任意命令执行。

修后改成 `shell=False` + argv 拆分：命令仍然是「用户自己配的那条」，但 shell
元字符不再有特殊含义。

全部离线：只在临时目录里跑，不联网、不碰真实 .minecraft。
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

import pytest

from mclauncher import launch_flow


class TestHookNoShell:
    def test_ampersand_payload_does_not_execute(self, tmp_path: Path):
        """修前：`echo A & echo PWNED>PWNED.txt` 在 cwd 生成 PWNED.txt。"""
        cwd = tmp_path / "game"
        cwd.mkdir()

        launch_flow.run_hook("echo A & echo PWNED>PWNED.txt", cwd, wait=True)

        assert not (cwd / "PWNED.txt").exists(), "shell 元字符被 cmd.exe 执行了"

    def test_pipe_payload_does_not_execute(self, tmp_path: Path):
        cwd = tmp_path / "game"
        cwd.mkdir()

        launch_flow.run_hook("echo A | echo PWNED>PWNED2.txt", cwd, wait=True)

        assert not (cwd / "PWNED2.txt").exists()

    def test_async_hook_does_not_execute_payload(self, tmp_path: Path):
        """`wait=False` 走 Popen，同一条 payload 也不能执行。"""
        cwd = tmp_path / "game"
        cwd.mkdir()

        launch_flow.run_hook("echo A & echo PWNED>PWNED3.txt", cwd, wait=False)

        assert not (cwd / "PWNED3.txt").exists()

    def test_source_has_no_shell_true(self):
        """源码级门禁：run_hook 里不许再出现 shell=True。"""
        import ast
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(launch_flow.run_hook)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    assert not (kw.arg == "shell"
                                and getattr(kw.value, "value", None) is True), \
                        "run_hook 又把命令交给 shell 了"


class TestCmdBuiltinChannel:
    """cmd 内建命令的兼容通道：放行「零元字符」的内建，拒绝一切带元字符的写法。

    老实现把整条字符串交给 shell，`cd` / `copy` / `dir` 是可用的；改成 shell=False
    后这些内建不再是磁盘上的可执行文件。这里保留兼容，但**不恢复**注入面：
    原文含 `& | < > ^ ( ) % !` 或换行就一律拒绝，绝不回到 cmd.exe 二次解析。
    """

    def test_builtin_without_metachars_is_allowed(self):
        argv = launch_flow._cmd_builtin_argv("dir")
        assert argv == ["cmd", "/c", "dir"]

    def test_builtin_with_args_is_allowed(self, tmp_path: Path):
        logs: list[str] = []
        rc = launch_flow.run_hook("cd /d .", tmp_path, log=logs.append, wait=True)
        assert rc == 0, logs

    @pytest.mark.parametrize("payload", [
        "echo A & echo PWNED>PWNED.txt",
        "echo A | echo PWNED>PWNED2.txt",
        "dir > PWNED3.txt",
        "echo %USERNAME%",
        "echo ^& whoami",
        "echo (x) & whoami",
        "echo !x! & whoami",
        "echo a\r\nwhoami",
        "echo a\nwhoami",
    ])
    def test_builtin_with_metachars_is_rejected(self, payload: str):
        assert launch_flow._cmd_builtin_argv(payload) is None, payload

    def test_rejected_builtin_returns_error_and_runs_nothing(self, tmp_path: Path):
        cwd = tmp_path / "game"
        cwd.mkdir()
        logs: list[str] = []

        rc = launch_flow.run_hook("echo A & echo PWNED>PWNED.txt", cwd, log=logs.append, wait=True)

        assert rc != 0, logs
        assert not (cwd / "PWNED.txt").exists()
        assert any("拒绝执行" in line for line in logs), logs

    def test_non_builtin_with_metachars_never_reaches_cmd(self, tmp_path: Path):
        """非内建命令带元字符时走 argv 直跑：`&` 只是参数，不是分隔符。"""
        cwd = tmp_path / "game"
        cwd.mkdir()
        script = tmp_path / "s.bat"
        script.write_text("@echo off\r\necho A1=[%1]\r\n", encoding="utf-8")
        logs: list[str] = []

        rc = launch_flow.run_hook(f'"{script}" "x&echo INJ>PWNED.txt"', cwd, log=logs.append, wait=True)

        assert rc == 0, logs
        assert not (cwd / "PWNED.txt").exists()
        assert any("x&echo INJ>PWNED.txt" in line for line in logs), logs


class TestHookStillRunsRealCommands:
    def test_runs_python_interpreter(self, tmp_path: Path):
        """正常命令（含盘符与反斜杠的 Windows 绝对路径）必须照旧能跑起来。"""
        marker = tmp_path / "ran.txt"
        code = f"open(r'{marker}', 'w').write('ok')"
        rc = launch_flow.run_hook(
            f'"{sys.executable}" -c "{code}"', tmp_path, wait=True)

        assert rc == 0, f"退出码 {rc}"
        assert marker.read_text(encoding="utf-8") == "ok"

    def test_missing_command_is_not_fatal(self, tmp_path: Path):
        """命令不存在时返回非零而不是抛异常（启动链不该被一条脚本打断）。"""
        rc = launch_flow.run_hook("pymcl-no-such-command-xyz --flag", tmp_path, wait=True)

        assert rc != 0

    def test_empty_command_is_noop(self, tmp_path: Path):
        assert launch_flow.run_hook("", tmp_path) == 0
        assert launch_flow.run_hook("   ", tmp_path) == 0

    def test_argv_split_is_windows_aware(self, tmp_path: Path):
        """Windows 上反斜杠是路径分隔符，不能被 POSIX 规则当转义符吃掉。"""
        script = tmp_path / "sub dir" / "run.bat"
        script.parent.mkdir()
        script.write_text("@echo off\r\necho BATCH_OK\r\n", encoding="utf-8")
        log_lines: list[str] = []

        rc = launch_flow.run_hook(f'"{script}"', tmp_path, log=log_lines.append, wait=True)

        assert rc == 0, f"退出码 {rc}，日志 {log_lines}"
        assert any("BATCH_OK" in line for line in log_lines), log_lines

    @pytest.mark.skipif(os.name != "nt", reason="Windows 路径分隔符专有")
    def test_backslash_path_survives_split(self, tmp_path: Path):
        parts = launch_flow._split_hook(r'"C:\Program Files\a.exe" --flag "C:\a b\c.txt"')
        assert parts == [r"C:\Program Files\a.exe", "--flag", r"C:\a b\c.txt"]

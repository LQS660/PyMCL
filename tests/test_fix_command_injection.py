# -*- coding: utf-8 -*-
"""审计 #1 P0-4 回归：`cmd /c mklink` 的参数拼接命令注入。

修前 `_junction()` 走 `subprocess.run(["cmd", "/c", "mklink", "/J", link, target])`。
`subprocess.list2cmdline` 只在参数含空格/引号时才加引号，而 `&` 是 Windows 目录名
的合法字符、不在 `sanitize_id` 的黑名单里 —— 版本 ID 为 `v1&ver>PWNED.txt` 且不含
空格时，`&` 被 cmd.exe 当命令分隔符，`ver>PWNED.txt` 作为独立命令执行并在 cwd 落文件。

修后 `_junction` 不再经过 cmd.exe（os.symlink → ctypes CreateSymbolicLinkW →
ctypes junction），`&` 只是目录名里的一个普通字符。

全部离线：临时目录，不联网、不碰真实 .minecraft。
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from mclauncher import version_settings as vs


def _inst(root: Path):
    inst = SimpleNamespace(name="t", path=root)
    inst.versions_dir = lambda: root / "versions"
    return inst


@pytest.mark.skipif(os.name != "nt", reason="命令注入路径是 Windows 专有（cmd.exe 二次解析）")
class TestMklinkInjection:
    def test_junction_payload_does_not_execute(self, tmp_path: Path):
        """审计复现的那一条：`_junction` 的 link 名含 `&ver>PWNED.txt`。

        `>` 在 Windows 目录名里非法，所以这一条只能直接打 `_junction`
        （link 名由版本 ID 拼成，P0-2 证明版本 ID 本身可以任意）。
        修前 cmd.exe 把 `&` 当分隔符，`ver>PWNED.txt` 作为独立命令执行并在 cwd 落文件。
        """
        from mclauncher import version_settings

        work = tmp_path / "mk"
        work.mkdir()
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        target = work / "t"
        target.mkdir()
        link = work / "v1&ver>PWNED.txt"

        old_cwd = os.getcwd()
        os.chdir(cwd)
        try:
            version_settings._junction(link, target)
        finally:
            os.chdir(old_cwd)

        assert not (cwd / "PWNED.txt").exists(), "命令注入生效了：cwd 里出现了 PWNED.txt"

    def test_legal_ampersand_version_id_does_not_execute(self, tmp_path: Path):
        """`&` 是 Windows 目录名的合法字符，版本 ID 真能叫 `v1&ver`。

        走完整链路 `apply_isolation`：修前 `&ver` 会被当成第二条命令执行。
        """
        root = tmp_path / "root"
        gdir = root / "versions" / "v1&ver"
        gdir.mkdir(parents=True)
        (root / "mods").mkdir()
        cwd = tmp_path / "cwd"
        cwd.mkdir()

        old_cwd = os.getcwd()
        os.chdir(cwd)
        try:
            vs.apply_isolation(_inst(root), "v1&ver", {"isolation": vs.ISOLATION_SAVES})
        finally:
            os.chdir(old_cwd)

        assert not (cwd / "PWNED.txt").exists()
        # 版本目录名原样保留，没有被当成命令拆开
        assert gdir.is_dir()

    def test_no_cmd_exe_is_spawned(self, tmp_path: Path, monkeypatch):
        """修后 _junction 不再调用 subprocess（不经过 cmd.exe）。"""
        import subprocess as subprocess_mod

        from mclauncher import version_settings

        def _boom(*_a, **_k):
            raise AssertionError("_junction 仍然调用了 subprocess / cmd.exe")

        monkeypatch.setattr(subprocess_mod, "run", _boom)
        monkeypatch.setattr(subprocess_mod, "Popen", _boom)
        root = tmp_path / "root"
        gdir = root / "versions" / "v1"
        gdir.mkdir(parents=True)
        (root / "mods").mkdir()

        version_settings._junction(gdir / "mods", root / "mods")

    def test_junction_still_links_when_supported(self, tmp_path: Path):
        """正常名字必须仍然真的建出可用的目录联接（隔离功能不能退化）。"""
        root = tmp_path / "root"
        gdir = root / "versions" / "1.20.1"
        gdir.mkdir(parents=True)
        shared = root / "mods"
        shared.mkdir()
        (shared / "a.jar").write_text("x", encoding="utf-8")

        vs.apply_isolation(_inst(root), "1.20.1", {"isolation": vs.ISOLATION_SAVES})

        link = gdir / "mods"
        assert link.is_dir(), "隔离没有建出 mods 目录"
        assert (link / "a.jar").is_file(), "联接没有指到共享池"
        from mclauncher.single_root import is_link
        assert is_link(link), "建出来的不是链接/联接，隔离会退化成普通空目录"


class TestJunctionApiSafety:
    """跨平台：_junction 不得把路径当 shell 文本用（Windows 专有注入路径的通用保险）。"""

    def test_junction_uses_no_shell(self):
        import ast
        import inspect
        import textwrap

        from mclauncher import version_settings

        tree = ast.parse(textwrap.dedent(inspect.getsource(version_settings)))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                assert not (kw.arg == "shell" and getattr(kw.value, "value", None) is True), \
                    "源码里仍有 shell=True 的调用"
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            assert name != "run" or not any(
                getattr(a, "value", None) == "cmd" for a in node.args), \
                "源码里仍在调用 cmd.exe"

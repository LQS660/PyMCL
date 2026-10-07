# -*- coding: utf-8 -*-
"""Offline CLI regressions: argument positions and missing nested commands.

Import only the real entry point, with config/guard dependencies stubbed, so
collection never loads or rewrites the user's config and never starts the GUI.
"""
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


MAIN = Path(__file__).resolve().parents[1] / "main.py"
COMMANDS = [
    ["gui"],
    ["versions", "1.21"],
    ["install", "1.21.4"],
    ["install-fabric", "1.20.1"],
    ["install-quilt", "1.20.1"],
    ["install-forge", "1.20.1"],
    ["install-neoforge", "1.21.1"],
    ["uninstall", "1.21.4"],
    ["launch", "1.21.4", "-u", "Steve"],
    ["list"],
    ["java", "list"],
    ["java", "install", "17"],
    ["login"],
    ["search", "optimization"],
    ["modpack", "local-pack.zip"],
    ["mods", "search", "sodium"],
    ["mods", "install", "sodium"],
    ["mods", "list"],
    ["instance", "list"],
    ["sysinfo"],
    ["feedback", "--title", "test"],
]


@pytest.fixture
def cli(monkeypatch, tmp_path):
    package = ModuleType("mclauncher")
    package.APP_DISPLAY_NAME = "PyMCL"
    package.APP_VERSION = "test"
    package.utils = ModuleType("mclauncher.utils")
    package.utils.ROOT = tmp_path
    guard = ModuleType("mclauncher.guard")
    guard.install = lambda: None
    config = ModuleType("mclauncher.config")
    config.CONFIG = {}
    with monkeypatch.context() as imports:
        imports.setitem(sys.modules, "mclauncher", package)
        imports.setitem(sys.modules, "mclauncher.guard", guard)
        imports.setitem(sys.modules, "mclauncher.config", config)
        spec = importlib.util.spec_from_file_location("_agent01_cli_under_test", MAIN)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("option", ["-i", "--instance"])
def test_instance_option_before_and_after_command(cli, command, option):
    parser = cli.build_parser()
    for argv in ([option, "named instance", *command],
                 [*command, option, "named instance"]):
        parsed = parser.parse_args(argv)
        assert parsed.instance == "named instance"
        assert callable(parsed.func)


@pytest.mark.parametrize("command", COMMANDS)
def test_existing_commands_without_instance_keep_default(cli, command):
    parsed = cli.build_parser().parse_args(command)
    assert parsed.instance is None
    assert callable(parsed.func)


@pytest.mark.parametrize("argv, expected", [
    (["-i", "outer", "install", "1.21.4"], "outer"),
    (["-i", "outer", "install", "1.21.4", "--instance", "inner"], "inner"),
    (["-i", "outer", "mods", "list"], "outer"),
    (["mods", "-i", "middle", "list"], "middle"),
    (["-i", "outer", "mods", "--instance", "middle", "list"], "middle"),
    (["mods", "-i", "middle", "list", "--instance", "inner"], "inner"),
    (["-i", "outer", "mods", "-i", "middle", "list", "-i", "inner"], "inner"),
    (["--instance=outer", "mods", "--instance=middle", "list", "--instance=inner"], "inner"),
])
def test_deepest_explicit_instance_wins_without_defaults_erasing_parent(cli, argv, expected):
    assert cli.build_parser().parse_args(argv).instance == expected


@pytest.mark.parametrize("argv", [["mods"], ["-i", "outer", "mods"], ["mods", "-i", "inner"]])
def test_mods_without_subcommand_is_usage_error(cli, capsys, argv):
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2
    stderr = capsys.readouterr().err
    assert "mods_cmd" in stderr
    assert "Traceback" not in stderr


def test_no_command_still_opens_gui(cli, monkeypatch):
    opened = []
    monkeypatch.setattr(cli, "gui_main", lambda: opened.append(True))
    cli.main([])
    assert opened == [True]


def test_nested_command_dispatch_preserves_instance(cli, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "cmd_mods", lambda args: calls.append((args.mods_cmd, args.instance)))
    cli.main(["-i", "outer", "mods", "--instance", "middle", "list", "-i", "inner"])
    assert calls == [("list", "inner")]

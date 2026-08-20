# -*- coding: utf-8 -*-
"""PCL 品质落地回归：隔离、参数拆分、皮肤站、启动链。"""
from __future__ import annotations

import tempfile
from pathlib import Path

from mclauncher.argsplit import split_args
from mclauncher.authlib import normalize_api
from mclauncher.launch_flow import prepare
from mclauncher.optifine import _profile
from mclauncher.skin import avatar_url, body_url
from mclauncher.updater import newer
from mclauncher.version_settings import apply_isolation, load, save


class _Inst:
    def __init__(self, path: Path):
        self.path = path

    def versions_dir(self):
        return self.path / "versions"


def main():
    failed = []

    def check(name, cond):
        if not cond:
            failed.append(name)

    check("split_args 空", split_args("") == [])
    bits = split_args('-Xmx4G -Dfoo="a b"')
    check("split_args 保留值", any("a b" in a or a.endswith("a b") for a in bits))
    check("authlib 去斜杠", normalize_api("https://littleskin.cn/api/yggdrasil/") == "https://littleskin.cn/api/yggdrasil")
    check("updater newer", newer("1.2.0", "1.0.1") and not newer("1.0.0", "1.0.1"))
    of = _profile("1.20.1", "HD_U", "I6", "net.minecraft:launchwrapper:2.3")
    check("optifine inheritsFrom", of["inheritsFrom"] == "1.20.1" and of["jar"] == "1.20.1")
    check("optifine tweak", "--tweakClass" in str(of.get("arguments")))

    acc = {"type": "authlib", "name": "Steve", "api": "https://littleskin.cn/api/yggdrasil", "uuid": "a" * 32}
    check("皮肤站头像不是 profile JSON", "/avatar/" in avatar_url(acc) and "sessionserver" not in avatar_url(acc))
    check("皮肤站预览走站点", "littleskin.cn/preview/" in body_url(acc))

    td = Path(tempfile.mkdtemp(prefix="pymcl_iso_"))
    inst = _Inst(td)
    vdir = inst.versions_dir() / "1.20.1"
    vdir.mkdir(parents=True)
    save(inst, "1.20.1", {"isolation": "all", "memory_mb": 2048, "jvm_args": "-XX:+UseG1GC", "server": "play.example.com"})
    data = load(inst, "1.20.1")
    check("版本设置读写", data["isolation"] == "all" and data["memory_mb"] == 2048)
    gdir = apply_isolation(inst, "1.20.1", data)
    check("隔离全部目录", gdir == vdir)
    check("隔离创建 mods", (gdir / "mods").is_dir() and (gdir / "saves").is_dir())
    prep = prepare(inst, "1.20.1", extra_game_args=["--demo"], memory_mb=4096)
    check("prepare 用版本内存", prep["memory_mb"] == 2048)
    check("prepare 直连服务器", "--server" in prep["extra_game_args"] and "play.example.com" in prep["extra_game_args"])
    check("prepare 保留额外参数", "--demo" in prep["extra_game_args"])
    check("prepare game_dir 隔离", Path(prep["game_dir"]) == vdir)

    save(inst, "1.20.1", {"isolation": "none"})
    prep2 = prepare(inst, "1.20.1", memory_mb=1024)
    check("关闭隔离用实例目录", Path(prep2["game_dir"]) == td)

    if failed:
        raise SystemExit("FAIL " + " | ".join(failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

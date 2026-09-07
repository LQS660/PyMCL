# -*- coding: utf-8 -*-
"""PCL 品质落地回归：隔离、参数拆分、皮肤站、启动链。"""
from __future__ import annotations

import tempfile
from pathlib import Path

from mclauncher import saves as saves_mod
from mclauncher import shortcut
from mclauncher.argsplit import split_args
from mclauncher.authlib import normalize_api
from mclauncher.launch_flow import prepare, resolve_resolution
from mclauncher.optifine import _profile
from mclauncher.skin import avatar_url, body_url
from mclauncher.updater import newer
from mclauncher.catalog_files import split_cf_game_versions
from mclauncher.game_install import parse_optifine_token
from mclauncher.gc import apply as gc_apply
from mclauncher.nide8 import normalize_server_id
from mclauncher.version_ops import sanitize_id
from mclauncher.version_settings import ISOLATION_LABELS, apply_isolation, load, save


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

    save(inst, "1.20.1", {"isolation": "mods"})
    data_m = load(inst, "1.20.1")
    check("隔离 mods 档位", data_m["isolation"] == "mods" and "mods" in ISOLATION_LABELS)
    gdir_m = apply_isolation(inst, "1.20.1", data_m)
    check("隔离 mods 目录", gdir_m == vdir)

    # 全屏：UI 一直写 "maximize"，启动链早期只认 "fullscreen"，两边对不上导致静默失效
    save(inst, "1.20.1", {"window_mode": "maximize"})
    prep_fs = prepare(inst, "1.20.1")
    check("全屏 maximize 生效", "--fullscreen" in prep_fs["extra_game_args"])
    w, h = resolve_resolution(prep_fs, 854, 480)
    check("全屏兜底分辨率", w >= 1280 and h >= 720)
    save(inst, "1.20.1", {"window_mode": "fullscreen"})
    check("全屏别名兼容", "--fullscreen" in prepare(inst, "1.20.1")["extra_game_args"])
    save(inst, "1.20.1", {"window_mode": "window"})
    check("窗口模式不加全屏", "--fullscreen" not in prepare(inst, "1.20.1")["extra_game_args"])

    # 版本级窗口大小优先于全局分辨率
    save(inst, "1.20.1", {"window_width": 1600, "window_height": 900})
    prep_win = prepare(inst, "1.20.1")
    check("版本窗口大小覆盖全局", resolve_resolution(prep_win, 854, 480) == (1600, 900))
    save(inst, "1.20.1", {"window_width": "abc", "window_height": -5})
    check("窗口大小非法值忽略", prepare(inst, "1.20.1")["window_width"] is None
          and prepare(inst, "1.20.1")["window_height"] is None)
    save(inst, "1.20.1", {"window_width": None, "window_height": None})
    check("窗口大小留空回落全局", resolve_resolution(prepare(inst, "1.20.1"), 854, 480) == (854, 480))

    # 窗口标题以前写进 pymcl.json 就没人读了
    save(inst, "1.20.1", {"window_title": "我的世界"})
    check("窗口标题透出到启动链", prepare(inst, "1.20.1")["window_title"] == "我的世界")

    # 存档备份 / 还原 往返
    saves_root = td / "saves"
    world = saves_root / "测试世界"
    (world / "region").mkdir(parents=True)
    (world / "level.dat").write_bytes(b"level-data")
    (world / "region" / "r.0.0.mca").write_bytes(b"chunk")
    info = saves_mod.backup_save(_Inst(td), "测试世界")
    check("备份产出 zip", Path(info["path"]).is_file() and info["save"] == "测试世界")
    backups = saves_mod.list_backups(_Inst(td), "测试世界")
    check("备份可列出", len(backups) == 1 and backups[0]["name"] == info["name"])
    check("备份不混进存档列表",
          [r["name"] for r in saves_mod.list_saves(_Inst(td))] == ["测试世界"])
    (world / "level.dat").write_bytes(b"broken")
    restored = saves_mod.restore_backup(_Inst(td), info["name"])
    check("还原不覆盖同名", restored["name"] != "测试世界")
    rpath = Path(restored["path"])
    check("还原内容一致", (rpath / "level.dat").read_bytes() == b"level-data"
          and (rpath / "region" / "r.0.0.mca").read_bytes() == b"chunk")
    over = saves_mod.restore_backup(_Inst(td), info["name"], overwrite=True)
    check("覆盖还原回原名", over["name"] == "测试世界"
          and (world / "level.dat").read_bytes() == b"level-data")
    exported = saves_mod.export_save(_Inst(td), "测试世界", str(td / "out"))
    check("导出 zip", Path(exported).is_file() and Path(exported).suffix == ".zip")
    saves_mod.delete_backup(_Inst(td), info["name"])
    check("删除备份", saves_mod.list_backups(_Inst(td)) == [])
    for bad in ("../逃逸", "sub/dir"):
        try:
            saves_mod.delete_save(_Inst(td), bad)
            check(f"路径穿越拦截 {bad}", False)
        except saves_mod.SaveError:
            pass

    # 桌面快捷方式
    check("快捷方式文件名清洗", shortcut.safe_filename('a/b:c*?"<>|') == "a_b_c______")
    check("快捷方式参数顺序",
          shortcut.launch_args("我的实例", "1.20.1", "Steve")
          == ["-i", "我的实例", "launch", "1.20.1", "--username", "Steve"])
    check("快捷方式正版账号优先",
          "--account" in shortcut.launch_args("i", "v", "Steve", account="正版名"))
    label = "PyMCL自检快捷方式"
    try:
        made = shortcut.create_launch_shortcut("default", "1.20.1", "Steve", name=label)
        check("快捷方式落盘", Path(made).is_file())
    finally:
        shortcut.remove_launch_shortcut(label)
    check("快捷方式已清理", not shortcut.remove_launch_shortcut(label))

    # i18n 契约：中文恒等、不许回退英文、UI 只准用 tr、词条表跟得上源码
    import ast
    import json

    from mclauncher import i18n

    keys = set()
    bad_alias = []
    for src in sorted(Path("app").rglob("*.py")):
        tree = ast.parse(src.read_bytes())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == "_":
                bad_alias.append(f"{src}:{node.lineno}")
            if node.func.id == "tr" and node.args and isinstance(node.args[0], ast.Constant):
                if isinstance(node.args[0].value, str):
                    keys.add(node.args[0].value)

    # `_` 在 app/ 里有 40 处被当丢弃变量（path, _ = ... / lambda _: ...），
    # 一旦拿它当 i18n 函数就会被局部赋值遮蔽，之后调用直接 TypeError
    check("UI 不得用 _() 作翻译函数", not bad_alias)
    check("已抽出词条", len(keys) > 500)

    locales = Path("mclauncher/locales")
    zh = json.loads((locales / "zh_CN.json").read_text("utf-8"))
    en = json.loads((locales / "en.json").read_text("utf-8"))
    check("zh_CN 覆盖全部源码词条", not (keys - set(zh)))
    check("zh_CN 是恒等映射", all(k == v for k, v in zh.items()))

    original = i18n.current_language()
    try:
        i18n._ensure()
        i18n._current_lang = "zh_CN"
        # 中文下 tr 必须原样返回，否则这 1125 处包装就会改掉现有行为
        check("中文 tr 恒等", all(i18n.tr(k) == k for k in keys))
        # 修好之前：zh_CN 缺的键会回退到 en，中文界面上冒英文
        i18n.add_translations("en", {"__probe__": "PROBE"})
        check("中文不回退英文", i18n.tr("__probe__") == "__probe__")
        i18n._current_lang = "en"
        check("英文取到译文", i18n.tr("启动游戏") == en.get("启动游戏"))
        check("英文缺译回退中文原文", i18n.tr("__never_translated__") == "__never_translated__")
    finally:
        i18n._strings.get("en", {}).pop("__probe__", None)
        i18n._current_lang = original

    check("gc 已有旗标不重复", "UseZGC" not in gc_apply("zgc", "-XX:+UseG1GC") and "UseG1GC" in gc_apply("zgc", "-XX:+UseG1GC"))
    check("gc 前置写入", gc_apply("g1", "-Xmx4G").startswith("-XX:+UseG1GC"))
    sid = "a" * 32
    check("nide8 规范化", normalize_server_id(f"https://auth.mc-user.com:233/{sid}") == sid)
    games, loaders = split_cf_game_versions(["1.20.1", "Forge", "Fabric", "snapshot"])
    check("cf 版本拆分", "1.20.1" in games and "forge" in loaders and "fabric" in loaders)
    t, patch = parse_optifine_token("HD_U_I6")
    check("optifine token", t == "HD" and "I6" in patch)
    check("sanitize_id", sanitize_id("a/b:c") == "a-b-c")

    from app.pcl_chrome import Theme
    Theme.apply(True)
    check("深色色板", Theme.dark and Theme.bg == "#1B1B1B" and Theme.btn_bg != "#FFFFFF")
    Theme.apply(False)
    check("浅色色板", (not Theme.dark) and Theme.bg == "#FFFFFF")
    more_row = lambda shown, cols: (shown + cols - 1) // cols
    check("加载更多行 整除", more_row(80, 4) == 20)
    check("加载更多行 余数", more_row(81, 4) == 21)
    from app.ui_alive import widget_alive
    class Dummy:
        _dismissed = True
        def objectName(self):
            return ""
    check("dismissed 守卫", widget_alive(Dummy()) is False)
    check("None 守卫", widget_alive(None) is False)

    # ---- 启动前预检（库 / 资源 / mods）----
    from mclauncher.preflight import check_launch

    pf_td = Path(tempfile.mkdtemp(prefix="pymcl_pf_"))
    class _PfInst:
        def __init__(self, path: Path):
            self.path = path
            self.name = path.name
        def versions_dir(self):
            return self.path / "versions"
        def libraries_dir(self):
            return self.path / "libraries"
        def assets_dir(self):
            return self.path / "assets"
        def natives_dir(self, version_id, version_json=None):
            return self.versions_dir() / version_id / f"{version_id}-natives"
        def version_json(self, version_id):
            p = self.versions_dir() / version_id / f"{version_id}.json"
            if not p.is_file():
                return None
            return __import__("json").loads(p.read_text(encoding="utf-8"))
        def installed_ids(self):
            vd = self.versions_dir()
            if not vd.is_dir():
                return []
            return [p.name for p in vd.iterdir() if p.is_dir()]

    pf_inst = _PfInst(pf_td)
    pf0 = check_launch(pf_inst, "")
    check("预检无版本报错", pf0["ok"] is False and any(i["code"] == "no_version" for i in pf0["items"]))

    vjson = {
        "id": "pf-test",
        "libraries": [
            {
                "name": "com.example:missinglib:1.0",
                "downloads": {
                    "artifact": {
                        "path": "com/example/missinglib/1.0/missinglib-1.0.jar",
                        "sha1": "a" * 40,
                        "size": 12,
                        "url": "https://example.invalid/missinglib-1.0.jar",
                    }
                },
            }
        ],
        "assetIndex": {"id": "pf-assets", "sha1": "b" * 40, "size": 1, "url": "https://example.invalid/a.json"},
    }
    vdir = pf_td / "versions" / "pf-test"
    vdir.mkdir(parents=True)
    (vdir / "pf-test.json").write_text(__import__("json").dumps(vjson), encoding="utf-8")
    (vdir / "pf-test.jar").write_bytes(b"fake")
    mods = pf_td / "mods"
    mods.mkdir()
    import io, zipfile, json as _json
    for name in ("dup-a.jar", "dup-b.jar"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("fabric.mod.json", _json.dumps({
                "id": "dupmod", "version": "1.0", "name": name,
                "depends": {"fabric-api": "*"},
            }))
        (mods / name).write_bytes(buf.getvalue())
    pf1 = check_launch(pf_inst, "pf-test", memory_mb=0)
    codes = {i["code"] for i in pf1["items"]}
    check("预检缺库", "libs_missing" in codes)
    check("预检缺资源索引", "assets_index_missing" in codes)
    check("预检重复模组", "mod_duplicate" in codes)
    check("预检缺 Fabric API", "mod_missing_fabric_api" in codes)

    # ---- 设置保存必须是局部更新，不能把没提交的键打回默认值 ----
    # 这类 bug 的共同点是用户完全无法自己发现：界面上什么都没变，
    # 配置文件里的值已经被悄悄改掉了。所以每一条都用断言钉住。
    import app.backend as app_backend
    import bridge.api as bridge_api
    from mclauncher.config import CONFIG, DEFAULT_CONFIG

    # `save()` 落的是整份 data，`load()` 只按 DEFAULT_CONFIG 的键名回读。
    # 任何写进去却没在表里声明的键 = 本次有效、重开就没。
    written = {"ui_fly_animation", "ui_fly_duration_ms", "default_java"}
    check("配置键都能跨重启保留", not (written - set(DEFAULT_CONFIG)))

    snapshot = dict(CONFIG.data)
    try:
        CONFIG.update({
            "ui_fly_duration_ms": 999,
            "ai_base_url": "https://probe.example/v1",
            "curseforge_api_key": "PROBE-CF-KEY",
            "download_limit_kbps": 512,
        })
        # 设置页 collect() 不含 ui_fly_duration_ms，以前每次保存都把它打回 620。
        # save_settings 只用模块级 CONFIG，不碰 self，所以可以不构造真 backend。
        app_backend.BackendAPI.save_settings(None, {"theme_color": "#123456"})
        check("save_settings 不重置飞入时长", int(CONFIG.get("ui_fly_duration_ms")) == 999)
        check("save_settings 不清空 CF Key", CONFIG.get("curseforge_api_key") == "PROBE-CF-KEY")
        check("save_settings 不重置限速", int(CONFIG.get("download_limit_kbps")) == 512)
        # 但用户主动清空必须生效，不能被「保持现值」吃掉
        app_backend.BackendAPI.save_settings(None, {"curseforge_api_key": ""})
        check("save_settings 允许清空", CONFIG.get("curseforge_api_key") == "")

        # bridge：提交 ai_mode 时不得连带把没提交的 AI 地址覆写成空串
        CONFIG.set("ai_base_url", "https://probe.example/v1")
        bridge_api.BackendAPI.save_settings(None, {"ai_mode": "custom"})
        check("bridge 保存不清空 AI 地址",
              CONFIG.get("ai_base_url") == "https://probe.example/v1")
    finally:
        CONFIG.data.clear()
        CONFIG.data.update(snapshot)
        CONFIG.save()

    if failed:
        raise SystemExit("FAIL " + " | ".join(failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

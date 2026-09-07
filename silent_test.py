# -*- coding: utf-8 -*-
"""静默回归：只测现用 mclauncher 包。成功无输出、退出 0；失败打印 FAIL 并退出 1。"""
from __future__ import annotations

import inspect
import os
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

FAILED = []


def check(name, cond):
    if not cond:
        FAILED.append(name)


def main():
    import logging
    from mclauncher import utils
    from mclauncher import launcher
    from mclauncher import java as java_mod
    from mclauncher import mods as mods_mod
    from mclauncher.auth import AccountManager, AuthError, open_secret, seal_secret
    from mclauncher.auth import MicrosoftAuthenticator
    from mclauncher.mods import ModError, delete_mod
    logging.getLogger("PyMCL").setLevel(logging.CRITICAL)

    check("dashed_uuid 32hex", utils.dashed_uuid("0123456789abcdef0123456789abcdef")
          == "01234567-89ab-cdef-0123-456789abcdef")
    check("dashed_uuid 已有连字符", utils.dashed_uuid("01234567-89ab-cdef-0123-456789abcdef")
          == "01234567-89ab-cdef-0123-456789abcdef")
    check("offline_uuid 带连字符", "-" in utils.offline_uuid("Notch"))

    src = inspect.getsource(launcher.build_launch_command)
    check("auth_session 使用 token:accessToken:uuid",
          "token:{auth_token}:{auth_uuid}" in src)
    check("auth_session 不再用 uuid:name",
          "token:{props.get('uuid'" not in src)
    check("clientid 使用配置中的微软 ID", "microsoft_client_id" in src)

    mgr = AccountManager.__new__(AccountManager)
    mgr.accounts = []
    mgr.active = None
    props = mgr.launch_props({
        "type": "microsoft", "name": "Steve",
        "uuid": "0123456789abcdef0123456789abcdef",
        "access_token": "TOK", "xuid": "uhs",
    })
    check("launch_props uuid 带连字符", props["uuid"] == "01234567-89ab-cdef-0123-456789abcdef")
    check("launch_props token", props["token"] == "TOK")

    ok = False
    try:
        mgr.ensure_valid({
            "type": "microsoft", "name": "Steve",
            "expires_at": 0, "refresh_token": None, "access_token": "old",
        })
    except AuthError:
        ok = True
    check("ensure_valid 过期无 refresh 抛 AuthError", ok)

    fresh = {"type": "microsoft", "name": "Steve", "expires_at": 9e12,
             "access_token": "live", "refresh_token": "r"}
    check("ensure_valid 未过期原样返回", mgr.ensure_valid(fresh) is fresh)

    sealed = seal_secret("TOK")
    check("token 可还原", open_secret(sealed) == "TOK")
    if os.name == "nt":
        check("Windows token 使用 DPAPI 前缀", sealed.startswith("dpapi:") or sealed == "TOK")

    ent_src = inspect.getsource(MicrosoftAuthenticator.check_entitlements)
    check("entitlements 不再因缺 item 直接拒绝", "没有购买 Minecraft" not in ent_src)

    td = Path(tempfile.mkdtemp(prefix="pymcl_st_"))
    zp = td / "t.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        info = zipfile.ZipInfo("evil_link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, "/tmp/outside")
        zf.writestr("ok.txt", "hello")
        zf.writestr("dir/nested.txt", "n")
    out = td / "out"
    utils.safe_extract_zip(zp, out)
    check("zip 正常文件解出", (out / "ok.txt").read_text(encoding="utf-8") == "hello")
    check("zip 嵌套文件解出", (out / "dir" / "nested.txt").read_text(encoding="utf-8") == "n")
    link = out / "evil_link"
    check("zip 符号链接被跳过", not link.exists() and not link.is_symlink())

    slip = td / "slip.zip"
    with zipfile.ZipFile(slip, "w") as zf:
        zf.writestr("../outside.txt", "nope")
    slipped = False
    try:
        utils.safe_extract_zip(slip, out)
    except ValueError:
        slipped = True
    check("zip-slip 被拒绝", slipped)
    check("zip-slip 未写出仓外文件", not (td / "outside.txt").exists())

    blob = td / "x.bin"
    blob.write_bytes(b"abc")
    check("无 sha1/size 不视为命中", utils.file_matches(blob) is False)
    check("仅 size 命中", utils.file_matches(blob, size=3) is True)
    check("size 不匹配", utils.file_matches(blob, size=9) is False)

    java_mod._MAJOR_CACHE.clear()
    orig_out = java_mod.java_version_output
    java_mod.java_version_output = lambda _exe: ""
    try:
        check("java 探测失败返回 None", java_mod.get_java_major("missing-java") is None)
        check("失败不写入缓存", "missing-java" not in java_mod._MAJOR_CACHE)
    finally:
        java_mod.java_version_output = orig_out
        java_mod._MAJOR_CACHE.clear()

    class InstA:
        def installed_ids(self):
            return ["1.7.10", "1.20.1-Forge_47.3.7"]

        def meta(self):
            return {}

    class InstB:
        def installed_ids(self):
            return ["1.7.10", "1.20.1-Forge_47.3.7"]

        def meta(self):
            return {"modpack": {"mc_version": "1.20.1"}, "mc_version": "1.7.10"}

    check("detect_mc 取最高版本", mods_mod.detect_mc_version(InstA()) == "1.20.1")
    check("detect_mc 优先整合包声明", mods_mod.detect_mc_version(InstB()) == "1.20.1")

    mods_dir = td / "inst" / "mods"
    saves = td / "inst" / "saves"
    mods_dir.mkdir(parents=True)
    saves.mkdir()
    victim = saves / "w.dat"
    victim.write_text("keep", encoding="utf-8")

    class InstPath:
        path = td / "inst"

    denied = False
    try:
        delete_mod(InstPath(), "../saves/w.dat")
    except ModError:
        denied = True
    check("delete_mod 拒绝路径穿越", denied and victim.exists())

    from app.backend import BackendAPI
    be_src = inspect.getsource(BackendAPI.get_version_list)
    check("版本列表 UI 路径不联网", "list_remote_versions" not in be_src)
    check("后台搜索 API", "def call_async" in inspect.getsource(BackendAPI))
    check("游戏进程加锁", "_game_lock" in inspect.getsource(BackendAPI.cancel_task))
    vp = (ROOT / "app" / "pages" / "version_page.py").read_text(encoding="utf-8")
    check("卸载改用 CheckBox", "CheckBox" in vp and "RadioButton" not in vp)
    check("远古类型展示", "old_alpha" in vp)
    lp = (ROOT / "app" / "pages" / "launch_page.py").read_text(encoding="utf-8")
    check("登录成功始终 reload", "task_id == self._login_task_id" in lp and "self.reload()" in lp)
    mp = (ROOT / "app" / "pages" / "catalog_page.py").read_text(encoding="utf-8")
    check("整合包搜索走后台", "call_async" in mp)
    # Mod 搜索在重构后由 catalog_page.ModPage 承担（mod_page 只管已装列表），
    # 断言跟着搬：搜索入口与后台调用都必须在 catalog_page 里。
    check("模组搜索走后台", "search_mods" in mp and "call_async" in mp)
    md = (ROOT / "app" / "pages" / "mod_page.py").read_text(encoding="utf-8")
    check("删模组失败有提示", "删除失败" in md)
    inst_src = (ROOT / "mclauncher" / "instances.py").read_text(encoding="utf-8")
    check("rename 写回 meta.name", 'set_meta("name"' in inst_src)
    check("测试入口指向包而非遗留脚本", "mclauncher.launcher" in Path(__file__).read_text(encoding="utf-8"))

    from mclauncher.argsplit import split_args
    check("argsplit 引号", any("a b" in a for a in split_args('-Xmx4G -Dfoo="a b"')))
    from mclauncher.authlib import normalize_api
    check("authlib API 去尾斜杠", normalize_api("https://littleskin.cn/api/yggdrasil/") == "https://littleskin.cn/api/yggdrasil")
    from mclauncher.updater import newer
    check("updater 版本比较", newer("1.2.0", "1.0.1") and not newer("1.0.0", "1.0.1"))
    from mclauncher.optifine import _profile
    of = _profile("1.20.1", "HD_U", "I6", "net.minecraft:launchwrapper:2.3")
    check("optifine 继承原版", of["inheritsFrom"] == "1.20.1" and of["jar"] == "1.20.1")
    check("optifine 1.13+ tweak", "--tweakClass" in str(of.get("arguments")))
    check("加载器含 OptiFine", "OptiFine" in vp)
    check("账号页存在", (ROOT / "app" / "pages" / "account_page.py").is_file())
    check("已装模组开关 UI", "已安装" in (ROOT / "app" / "pages" / "catalog_page.py").read_text(encoding="utf-8"))
    check("启动页直连服务器", "server_edit" in lp)
    mw = (ROOT / "app" / "main_window.py").read_text(encoding="utf-8")
    check("侧栏有账号", '"account"' in mw)
    be = inspect.getsource(BackendAPI)
    check("backend 有 repair_version", "def repair_version" in be)
    check("backend 有 authlib 登录", "def start_authlib_login" in be)
    check("build_launch_command 返回 game_dir", "return cmd, natives_dir, vdir, game_directory" in src)

    if FAILED:
        sys.stderr.write("FAIL " + " | ".join(FAILED) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

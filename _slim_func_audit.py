# -*- coding: utf-8 -*-
"""Slim-package functional audit: call every UI-used RPC against a bridge
started with the slim layout (www + native only, NO bridge/ python package),
i.e. what an end user actually gets from dist/PyMCL.exe (Edge shell)."""
from __future__ import annotations
import json, secrets, shutil, subprocess, sys, tempfile, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\Downloads\新建文件夹 (5)").resolve()
EXE = ROOT / "native" / "build" / "pymcl-bridge.exe"

# (method, params, kind) kind: ro=readonly ok, side=side-effect in temp root ok
CALLS = [
    # --- eziapp (slim www UI) ---
    ("get_instances", {}, "ro"),
    ("create_instance", {"name": "audit-inst"}, "side"),
    ("rename_instance", {"instance": "audit-inst", "name": "audit-inst2"}, "side"),
    ("delete_instance", {"instance": "audit-inst2"}, "side"),
    ("get_version_list", {}, "ro"),
    ("fetch_version_list", {}, "ro"),
    ("get_installed_versions", {"instance": "default"}, "ro"),
    ("uninstall_version", {"instance": "default", "version": "__none__"}, "ro"),
    ("get_java_list", {}, "ro"),
    ("java_combo_options", {}, "ro"),
    ("get_settings", {}, "ro"),
    ("save_settings", {"data": {"language": "zh-CN"}}, "ro"),
    ("get_account_rows", {}, "ro"),
    ("add_offline_account", {"username": "AuditUser"}, "side"),
    ("set_active_account", {"name": "AuditUser"}, "side"),
    ("remove_account", {"name": "AuditUser"}, "side"),
    ("get_accounts", {}, "ro"),
    ("open_instance_folder", {"instance": "default"}, "ro"),
    ("open_global_mods", {}, "ro"),
    ("get_installed_mods", {"instance": "default"}, "ro"),
    ("get_installed_mod_entries", {"instance": "default"}, "ro"),
    ("enable_mod", {"instance": "default", "filename": "__nope.jar"}, "ro"),
    ("disable_mod", {"instance": "default", "filename": "__nope.jar"}, "ro"),
    ("list_servers", {"instance": "default"}, "ro"),
    ("add_server", {"instance": "default", "ip": "mc.example.com", "name": "t"}, "side"),
    ("update_server", {"instance": "default", "index": 0, "name": "t2"}, "side"),
    ("delete_server", {"instance": "default", "index": 0}, "side"),
    ("get_all_playtime", {}, "ro"),
    ("format_playtime", {"seconds": 3661}, "ro"),
    ("clear_playtime", {"instance": "default"}, "side"),
    ("submit_feedback", {"message": "audit", "category": "other"}, "ro"),
    ("terracotta_host", {}, "ro"),
    ("terracotta_join", {"code": "x"}, "ro"),
    ("terracotta_idle", {}, "ro"),
    ("terracotta_snapshot", {}, "ro"),
    ("terracotta_open_firewall_settings", {}, "ro"),
    ("lan_hint", {}, "ro"),
    ("ai_answer", {"q": "hi"}, "ro"),
    ("ai_confirm", {}, "ro"),
    ("ai_stop", {}, "ro"),
    # --- WPF (current recommended UI) ---
    ("list_tasks", {}, "ro"),
    ("download_version", {"version": "1.20.1", "instance": "default"}, "ro"),
    ("launch_game", {"instance": "default", "version": ""}, "ro"),
    ("cancel_task", {"task_id": "__none__"}, "ro"),
    # --- core parity spot checks ---
    ("search_mods", {"query": "jei", "instance": "default"}, "ro"),
    ("search_modpacks", {"query": "rpg"}, "ro"),
    ("search_resourcepacks", {"query": "x"}, "ro"),
    ("search_shaders", {"query": "x"}, "ro"),
    ("search_datapacks", {"query": "x"}, "ro"),
    ("get_version_settings", {"instance": "default", "version": "1.20.1"}, "ro"),
    ("save_version_settings", {"instance": "default", "version": "1.20.1", "data": {"memory_mb": 2048}}, "side"),
    ("get_crash", {}, "ro"),
    ("check_update", {}, "ro"),
    ("help_articles", {}, "ro"),
    ("cached_news", {}, "ro"),
    ("fetch_news", {}, "ro"),
    ("cleaner_preview", {}, "ro"),
    ("cleaner_apply", {"items": []}, "ro"),
    ("repair_version", {"instance": "default", "version": "1.20.1"}, "ro"),
    ("search_worlds", {}, "ro"),
    ("install_world", {"path": "x"}, "ro"),
    ("export_modpack", {"instance": "default"}, "ro"),
    ("list_loader_versions", {"loader": "fabric"}, "ro"),
    ("list_catalog_files", {}, "ro"),
    ("start_authlib_login", {"server": "https://littleskin.cn/api/yggdrasil"}, "ro"),
    ("start_nide8_login", {"sub": "x"}, "ro"),
    ("start_mod_updates", {"instance": "default"}, "ro"),
    ("start_self_update", {}, "ro"),
    ("start_microsoft_login", {}, "ro"),
    ("is_game_running", {}, "ro"),
    ("build_launch_command", {"instance": "default", "version": "1.20.1"}, "ro"),
    ("get_launch_command", {"instance": "default", "version": "1.20.1"}, "ro"),
]


def main() -> int:
    td = Path(tempfile.mkdtemp(prefix="pymcl-slim-audit-"))
    fails: list[str] = []
    degraded: list[str] = []
    ok: list[str] = []
    try:
        # exact slim-stage layout: www + native/{build?,data,tools}; NO bridge/
        shutil.copytree(ROOT / "eziapp" / "dist", td / "www")
        cfg = td / "www" / "bridge-config.json"
        if cfg.exists():
            cfg.unlink()
        (td / "native" / "data").mkdir(parents=True)
        shutil.copy2(ROOT / "native" / "data" / "catalog.json", td / "native" / "data" / "catalog.json")
        (td / "native" / "tools").mkdir(parents=True)
        shutil.copy2(ROOT / "native" / "tools" / "py_rpc.py", td / "native" / "tools" / "py_rpc.py")

        token = secrets.token_urlsafe(32)
        p = subprocess.Popen(
            [str(EXE), "--root", str(td), "--host", "127.0.0.1", "--port", "0", "--token", token],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", cwd=str(EXE.parent),
        )
        line = p.stdout.readline().strip()
        if "port=" not in line:
            print("BOOT FAIL:", line)
            return 2
        port = int([x for x in line.split() if x.startswith("port=")][0].split("=", 1)[1])
        print(f"bridge up on {port}, root={td}")

        for method, params, kind in CALLS:
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/rpc", data=body,
                headers={"Content-Type": "application/json", "X-PyMCL-Bridge-Token": token},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    js = json.loads(r.read().decode("utf-8", "replace"))
                    if "error" in js and js["error"]:
                        err = str(js["error"].get("message", js["error"]))[:110]
                        fails.append(method)
                        tag = "ERR "
                    else:
                        res = json.dumps(js.get("result"), ensure_ascii=False)[:110]
                        # degraded detection: empty results / python-needed text
                        rlow = res.lower()
                        if ("python" in rlow or res in ("[]", '""', "{}", "True")
                                and method in DEGRADE_SET):
                            degraded.append(method)
                            tag = "DEG "
                        else:
                            ok.append(method)
                            tag = "OK  "
                        err = res
                print(f"[{tag}] {method:32s} {err}")
            except urllib.error.HTTPError as e:
                try:
                    msg = json.loads(e.read().decode("utf-8", "replace")).get("error", {}).get("message", "")
                except Exception:
                    msg = ""
                fails.append(method)
                print(f"[ERR ] {method:32s} HTTP {e.code} {str(msg)[:100]}")
            except Exception as e:
                fails.append(method)
                print(f"[ERR ] {method:32s} {e}")
        p.terminate()
        try:
            p.wait(timeout=3)
        except Exception:
            p.kill()
    finally:
        shutil.rmtree(td, ignore_errors=True)

    print(f"\n== ok={len(ok)} degraded={len(degraded)} fail={len(fails)} ==")
    if degraded:
        print("DEGRADED:", ", ".join(sorted(set(degraded))))
    if fails:
        print("FAILED  :", ", ".join(sorted(set(fails))))
    return 0


DEGRADE_SET = {
    "help_articles", "cached_news", "fetch_news", "list_loader_versions",
    "list_catalog_files", "search_worlds", "terracotta_snapshot", "lan_hint",
    "ai_list_chats", "ai_new_chat", "ai_delete_chat", "ai_set_active",
    "check_update", "test_ai_connection", "submit_feedback",
    "terracotta_allow_firewall",
}

if __name__ == "__main__":
    sys.exit(main())

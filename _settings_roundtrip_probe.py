# -*- coding: utf-8 -*-
"""实测设置保存链路：验证「局部提交不会清掉没提交的键」确实成立。"""
import app.backend as app_backend
import bridge.api as bridge_api
from mclauncher.config import CONFIG

snapshot = dict(CONFIG.data)
try:
    CONFIG.update({
        "ui_fly_duration_ms": 999,
        "ui_fly_animation": False,
        "ai_base_url": "https://probe.example/v1",
        "ai_gateway_url": "https://gw.probe.example",
        "curseforge_api_key": "PROBE-CF-KEY",
        "download_limit_kbps": 512,
        "default_java": r"C:\probe\java.exe",
    })

    print("--- app.backend.save_settings({'theme_color': ...}) ---")
    app_backend.BackendAPI.save_settings(None, {"theme_color": "#123456"})
    for key in ("ui_fly_duration_ms", "ui_fly_animation", "curseforge_api_key",
                "download_limit_kbps", "ai_base_url", "default_java"):
        print(f"  {key:<22} = {CONFIG.get(key)!r}")

    print("--- app.backend.save_settings({'curseforge_api_key': ''}) 主动清空 ---")
    app_backend.BackendAPI.save_settings(None, {"curseforge_api_key": ""})
    print(f"  curseforge_api_key     = {CONFIG.get('curseforge_api_key')!r}")

    print("--- bridge.save_settings({'ai_mode': 'custom'}) ---")
    bridge_api.BackendAPI.save_settings(None, {"ai_mode": "custom"})
    for key in ("ai_mode", "ai_base_url", "ai_gateway_url"):
        print(f"  {key:<22} = {CONFIG.get(key)!r}")

    print("--- 重启模拟：CONFIG.load() 之后这些键还在吗 ---")
    CONFIG.save()
    CONFIG.load()
    for key in ("ui_fly_animation", "ui_fly_duration_ms", "default_java"):
        print(f"  {key:<22} = {CONFIG.get(key)!r}")
finally:
    CONFIG.data.clear()
    CONFIG.data.update(snapshot)
    CONFIG.save()
    print("config.json 已还原")

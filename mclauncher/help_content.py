# -*- coding: utf-8 -*-
"""内置帮助：启动、模组、隔离、账号、联机。"""
from __future__ import annotations

ARTICLES = [
    {
        "id": "install",
        "title": "安装游戏",
        "body": (
            "打开「下载 → 原版游戏」，选 Minecraft 版本后点安装。\n"
            "安装向导可同时勾选 Forge / Fabric 与 OptiFine。\n"
            "Forge + OptiFine：先装 Forge，再把 OptiFine 放进 mods。\n"
            "加载器版本可在向导里挑选，不必总用最新。\n"
            "「跳过资源校验」适合已经下过 assets 的机器，加快重装。"
        ),
    },
    {
        "id": "mods",
        "title": "模组与整合包",
        "body": (
            "搜索结果点「安装」会打开版本选择页，可按 MC 版本 / 加载器筛选文件。\n"
            "点某一行即可安装指定 build，而不是永远装最新。\n"
            "整合包建议新建实例再装，避免和旧模组混在一起。\n"
            "已安装模组支持开关（.disabled）和检查更新（Modrinth + CurseForge）。"
        ),
    },
    {
        "id": "isolation",
        "title": "版本隔离",
        "body": (
            "关闭：所有版本共用实例目录。\n"
            "隔离存档：各版本独立 saves，mods 等仍共用。\n"
            "隔离 Mod：独立 mods/config，存档共用。\n"
            "隔离全部：该版本拥有完整游戏目录。\n"
            "可在版本设置里改，也可以设「新版本默认隔离」。"
        ),
    },
    {
        "id": "account",
        "title": "账号",
        "body": (
            "微软：设备码登录，会自动打开浏览器。\n"
            "皮肤站：Little Skin 或自建 Yggdrasil，走 authlib-injector。\n"
            "统一通行证：填写 32 位服务器 ID、账号密码。\n"
            "离线：可指定 Steve / Alex 模型。\n"
            "版本设置可绑定该版本启动时使用的账号。"
        ),
    },
    {
        "id": "launch",
        "title": "启动与内存",
        "body": (
            "启动器可见性：游戏启动后可关闭、隐藏、最小化或保持窗口。\n"
            "GC：G1 / 调优 G1 / ZGC / 不指定，写在默认 JVM 或版本 JVM 前。\n"
            "窗口模式：窗口、全屏、最大化、与启动器一致。\n"
            "启动前命令可选「不等待」。\n"
            "崩溃后可在帮助旁的崩溃对话框导出报告。"
        ),
    },
    {
        "id": "lan",
        "title": "联机",
        "body": (
            "陶瓦联机用于 P2P 房间码。官方 PCL 联机大厅已关闭，不会再做旧房间互通。\n"
            "局域网：对方用「直接连接」填你的 IP:端口。"
        ),
    },
]


def list_articles() -> list[dict]:
    return [{"id": a["id"], "title": a["title"]} for a in ARTICLES]


def get_article(article_id: str) -> dict:
    for a in ARTICLES:
        if a["id"] == article_id:
            return dict(a)
    return dict(ARTICLES[0])

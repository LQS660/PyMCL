# -*- coding: utf-8 -*-
"""PyMCL 自检脚本：验证 Python 环境、依赖与网络连通性（不会下载游戏本体）。

用法: python selftest.py
"""
import sys


def main():
    print("== PyMCL 启动器自检 ==")

    # 1. 依赖
    try:
        import requests
        print(f"[OK] requests {requests.__version__}")
    except ImportError:
        print("[FAIL] 缺少依赖 requests，请先运行: pip install -r requirements.txt")
        return 1

    # 2. 基础模块
    try:
        from mclauncher import utils
        from mclauncher.config import CONFIG
        print(f"[OK] 平台: {utils.OS_NAME}-{utils.ARCH}")
        print(f"[OK] 启动器主目录: {utils.ROOT}")
        print(f"[OK] 实例目录: {CONFIG.instances_dir}")
    except Exception as e:
        print(f"[FAIL] 启动器模块加载失败: {e}")
        return 1

    # 3. Java 检测
    try:
        from mclauncher import java as java_mod
        javas = java_mod.all_javas()
        if javas:
            print(f"[OK] 检测到 {len(javas)} 个 Java: {', '.join(j['name'] for j in javas[:5])}")
        else:
            print("[..] 未检测到 Java（启动游戏时会自动下载匹配版本）")
    except Exception as e:
        print(f"[FAIL] Java 检测失败: {e}")
        return 1

    # 4. 网络：Mojang 版本清单
    print("正在测试网络（获取 Mojang 版本清单）…")
    try:
        from mclauncher.downloader import DownloadManager
        from mclauncher import manifest as manifest_mod
        dm = DownloadManager(threads=4)
        versions = manifest_mod.list_remote_versions(dm)
        print(f"[OK] 版本清单获取成功，共 {len(versions)} 个可下载版本")
    except Exception as e:
        print(f"[FAIL] 无法连接 Mojang 服务器: {e}")
        return 1

    # 5. 网络：Modrinth（整合包）
    try:
        from mclauncher import modpack as modpack_mod
        dm = DownloadManager(threads=4)
        hits = modpack_mod.modrinth_search(dm, "optimization", limit=3)
        print(f"[OK] Modrinth API 可用（搜索到 {len(hits)} 个整合包）")
    except Exception as e:
        print(f"[..] Modrinth API 不可用（不影响原版游玩）: {e}")

    # 6. GUI 可用性
    try:
        import tkinter
        print("[OK] tkinter 图形界面可用")
    except ImportError:
        print("[..] 本机 Python 缺少 tkinter，只能使用命令行模式")

    print("\n自检完成！运行 python main.py 或双击 start.bat 打开启动器。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

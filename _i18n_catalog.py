# -*- coding: utf-8 -*-
"""从 app/ 抽取 tr() 词条，生成/更新 mclauncher/locales 下的语言包。

- `zh_CN.json`：全量词条的恒等映射，同时充当**翻译对照表**（译者照着它填别的语言）。
- `en.json`：已有译文 + 本文件 NEW_EN 里的新译文；**没译的键直接不写进去**，
  运行时 `tr()` 找不到就回退 key 本身（= 中文原文），这是 gettext 的标准行为，
  比塞一个半吊子译文更好。

重复执行安全：已有译文不会被覆盖，只做增量合并。
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

CJK = re.compile(r"[\u4e00-\u9fff]")
LOCALES = Path("mclauncher/locales")
SOURCES = (Path("app"),)

NEW_EN: dict[str, str] = {
    # —— 高频动作 / 状态 ——
    "全部": "All", "无": "None", "自动选择": "Auto", "最新": "Latest", "取消": "Cancel",
    "确定": "OK", "默认": "Default", "关闭": "Close", "退出": "Exit", "保存": "Save",
    "刷新": "Refresh", "浏览": "Browse", "创建": "Create", "复制": "Copy", "删除": "Delete",
    "重命名": "Rename", "安装": "Install", "下载": "Download", "停止": "Stop", "发送": "Send",
    "加入": "Join", "使用": "Use", "同意": "Agree", "了解": "Got it", "以后再说": "Later",
    "其他": "Other", "可选": "Optional", "不指定": "Unspecified", "暂无": "None yet",
    "就绪": "Ready", "可用": "Available", "收藏": "Favorites", "热门": "Trending",
    "提示": "Notice", "出错": "Error", "名称": "Name", "描述": "Description",
    # —— 状态回执 ——
    "已停止": "Stopped", "已安装": "Installed", "已取消": "Cancelled", "已复制": "Copied",
    "已保存": "Saved", "已删除": "Deleted", "已发送": "Sent", "已是最新": "Up to date",
    "已正常退出": "Exited normally", "处理中…": "Working…", "搜索中…": "Searching…",
    "发送中…": "Sending…", "正在想…": "Thinking…", "准备启动…": "Preparing to launch…",
    "任务完成": "Task complete", "发现更新": "Update available", "未选择": "Not selected",
    "未同意": "Not agreed", "✔ 全部完成": "✔ All done",
    # —— 失败态 ——
    "删除失败": "Delete failed", "导出失败": "Export failed", "保存失败": "Save failed",
    "创建失败": "Create failed", "复制失败": "Copy failed", "启动失败": "Launch failed",
    "切换失败": "Switch failed", "加载失败": "Load failed", "卸载失败": "Uninstall failed",
    "重命名失败": "Rename failed", "发送失败": "Send failed", "直连失败": "Direct connect failed",
    "加入失败": "Join failed", "创建房间失败": "Failed to create room", "无法打开": "Cannot open",
    "启动中止": "Launch aborted", "启动器出现错误": "Launcher error",
    "启动器后台线程出错": "Launcher background thread error",
    "AI 连接失败": "AI connection failed", "AI 连接成功": "AI connected",
    "助手出错": "Assistant error",
    # —— 导航 / 页面 ——
    "存档": "Worlds", "备份": "Backups", "截图": "Screenshots", "日志": "Logs",
    "崩溃报告": "Crash Reports", "主页": "Home", "助手": "Assistant", "反馈": "Feedback",
    "光影": "Shaders", "光影包": "Shader Packs", "资源包": "Resource Packs",
    "模组": "Mods", "世界": "Worlds", "原版": "Vanilla", "原版游戏": "Vanilla Game",
    "加载器": "Loader", "加载器版本": "Loader Version", "主加载器": "Primary Loader",
    "全局 Mod": "Global Mods", "启动配置": "Launch Profile",
    # —— 账号 ——
    "离线": "Offline", "离线模式": "Offline Mode", "微软登录": "Microsoft Login",
    "皮肤站": "Skin Server", "皮肤站登录": "Skin Server Login", "登录皮肤站": "Log in to Skin Server",
    "统一通行证": "Unified Pass", "密码": "Password", "保存离线账号": "Save Offline Account",
    "使用微软账户登录…": "Sign in with a Microsoft account…",
    # —— 版本 / 实例 ——
    "版本": "Version", "实例": "Instance", "实例目录": "Instance Folder",
    "选择版本": "Select Version", "新版本 ID": "New Version ID", "请先选择版本": "Please select a version first",
    "删除实例": "Delete Instance", "删除存档": "Delete World", "删除备份": "Delete Backup",
    "还原备份": "Restore Backup", "卸载选中版本": "Uninstall Selected",
    "创建桌面快捷方式": "Create Desktop Shortcut", "正式版": "Release", "快照": "Snapshot",
    "远古": "Ancient", "隔离": "Isolation", "隔离全部": "Isolate everything",
    "隔离存档": "Isolate worlds", "隔离 Mod 与配置": "Isolate mods and config",
    "关闭（共用实例目录）": "Off (share the instance folder)",
    "新版本默认隔离": "Default isolation for new versions",
    # —— 启动 / 窗口 ——
    "启动": "Launch", "启动游戏": "Launch Game", "全屏": "Fullscreen", "窗口": "Window",
    "分辨率": "Resolution", "内存": "Memory", "内存 MB": "Memory (MB)",
    "默认内存 (MB)": "Default memory (MB)", "优先级": "Priority",
    "JVM 参数": "JVM Arguments", "内存回收器": "Garbage Collector", "G1（推荐）": "G1 (recommended)",
    "启动前": "Before launch", "启动内核": "Launch Core", "用户名": "Username",
    "跟随启动页": "Follow the Launch page", "Java（本实例）": "Java (this instance)",
    "可被版本设置覆盖": "Can be overridden per version",
    # —— 服务器 / 联机 ——
    "服务器": "Servers", "服务器名称": "Server Name", "服务器地址": "Server Address",
    "端口": "Port", "添加服务器": "Add Server", "编辑服务器": "Edit Server",
    "公网直连": "Direct connection", "防火墙": "Firewall", "允许访问": "Allow access",
    "我想当房客": "Join as a guest", "准备陶瓦联机": "Prepare Terracotta multiplayer",
    "下载陶瓦联机内核": "Download Terracotta core", "启动联机内核": "Start multiplayer core",
    # —— 下载 ——
    "下载任务": "Download Tasks", "取消任务": "Cancel Task", "下载量": "Downloaded",
    "文件下载源": "Download Source", "仅官方": "Official only", "仅 BMCLAPI": "BMCLAPI only",
    "仅 MCIM": "MCIM only", "下载并发线程数": "Concurrent download threads",
    "同时下载的文件数量": "Number of files downloaded at once",
    "0 表示不限制": "0 means unlimited", "下载与性能": "Download & Performance",
    "从链接安装": "Install from link", "导入 zip": "Import zip", "导入本地 zip": "Import local zip",
    "从链接安装光影": "Install shader from link", "从链接安装资源包": "Install resource pack from link",
    "从链接安装整合包": "Install modpack from link", "从链接安装模组": "Install mod from link",
    "从链接安装世界": "Install world from link", "从链接安装数据包": "Install datapack from link",
    "安装光影": "Install Shader", "安装资源包": "Install Resource Pack",
    "安装整合包": "Install Modpack", "安装模组": "Install Mod", "整合包": "Modpack",
    "删除整合包实例": "Delete Modpack Instance", "搜索结果（点击安装）": "Results (click to install)",
    "没有找到相关光影": "No matching shaders", "没有找到相关整合包": "No matching modpacks",
    "没有找到相关模组": "No matching mods", "没有找到相关资源包": "No matching resource packs",
    "还没有安装光影": "No shaders installed yet", "还没有安装模组": "No mods installed yet",
    "还没有安装资源包": "No resource packs installed yet",
    "选择光影包": "Select Shader Pack", "选择数据包": "Select Datapack",
    "选择资源包": "Select Resource Pack", "选择游戏目录": "Select Game Folder",
    "不装进存档": "Do not install into a world", "模组 (*.jar)": "Mods (*.jar)",
    "世界 (*.zip)": "Worlds (*.zip)",
    # —— 设置 ——
    "设置": "Settings", "保存设置": "Save Settings", "主题包": "Theme Pack",
    "主题包名称": "Theme pack name", "主题色": "Theme Color", "保存主题包": "Save Theme Pack",
    "保存当前主题": "Save Current Theme", "加载主题": "Load Theme", "删除主题": "Delete Theme",
    "没有已保存的主题包": "No saved theme packs", "动态效果": "Motion Effects",
    "下载飞入动画": "Download fly-in animation", "启动器可见性": "Launcher Visibility",
    "保持显示": "Keep visible", "关闭启动器": "Close the launcher",
    "启动时检查更新": "Check for updates at startup", "检查更新": "Check for Updates",
    "到设置里安装": "Install it from Settings", "允许多开": "Allow multiple instances",
    "语言已切换": "Language changed",
    "重启启动器后界面才会变成新语言": "Restart the launcher for the new language to take effect",
    "自定义主页": "Custom Home Page", "启动页主页": "Launch page home",
    "主页已设为空白": "Home page set to blank", "一般无需修改": "Usually no need to change",
    "例如 #2E9B6B": "e.g. #2E9B6B", "智能推荐": "Smart Recommendation",
    "官方启动器迁移": "Migrate from Official Launcher", "下载 Java": "Download Java",
    "下载新运行时": "Download new runtime",
    # —— AI / 反馈 ——
    "AI 助手": "AI Assistant", "公益接口": "Free public endpoint",
    "自定义 NewAPI": "Custom NewAPI", "NewAPI 令牌": "NewAPI Token",
    "测试 AI 连接": "Test AI Connection", "删除对话": "Delete Conversation",
    "可以继续说下一句": "You can keep talking", "请在下面选一下": "Please choose below",
    "发送反馈": "Send Feedback", "发送给开发者": "Send to developer",
    "反馈上报地址": "Feedback endpoint", "反馈与诊断": "Feedback & Diagnostics",
    "允许上传诊断数据": "Allow uploading diagnostic data",
    "不同意上传则不会发送": "Nothing is sent unless you agree",
    "显示日志": "Show Log", "收起日志": "Hide Log",
    "删掉后文件找不回来。": "Deleted files cannot be recovered.",
    # —— 玩法标签 ——
    "生存": "Survival", "创造": "Creative", "冒险": "Adventure", "科技": "Tech",
    "魔法": "Magic", "优化": "Optimization", "卡通": "Cartoon", "写实": "Realistic",
    "光追": "Ray Tracing", "热门推荐": "Popular Picks",
    "为当前实例增添玩法": "Add more to play with in this instance",
}


def extract_keys() -> set[str]:
    keys: set[str] = set()
    for root in SOURCES:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_bytes())
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                    continue
                if node.func.id != "tr" or not node.args:
                    continue
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    keys.add(arg.value)
    return keys


def load(name: str) -> dict:
    path = LOCALES / name
    if not path.is_file():
        return {}
    return json.loads(path.read_text("utf-8"))


def dump(name: str, data: dict):
    path = LOCALES / name
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {k: data[k] for k in sorted(data)}
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", "utf-8")


def main() -> int:
    keys = extract_keys()
    zh = load("zh_CN.json")
    en = load("en.json")

    # zh_CN 是全量对照表：源码里的键 + 历史键，一律恒等
    catalog = dict.fromkeys(sorted(keys | set(zh) | set(en)))
    zh_out = {k: zh.get(k) or k for k in catalog}

    en_out = dict(en)
    added = 0
    for key, value in NEW_EN.items():
        if key not in en_out:
            en_out[key] = value
            added += 1
    # 只保留真的有译文的键；没译的留空让 tr() 回退中文原文
    en_out = {k: v for k, v in en_out.items() if v and v != k or k.isascii()}

    dump("zh_CN.json", zh_out)
    dump("en.json", en_out)

    covered = sum(1 for k in keys if k in en_out)
    print(f"源码 tr() 词条: {len(keys)}")
    print(f"zh_CN 对照表: {len(zh_out)} 条（全量恒等）")
    print(f"en 译文: {len(en_out)} 条，本次新增 {added} 条")
    print(f"源码词条英文覆盖率: {covered}/{len(keys)} = {covered * 100 // max(len(keys), 1)}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

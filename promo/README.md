# PyMCL 宣传片工作区

录完的片子丢进 `promo/raw/`，成片会出在 `promo/out/`。

## 已装 MCP（本仓库 `.cursor/mcp.json`）

| 名字 | 干什么 |
|---|---|
| **kinocut** | 裁切 / 拼接 / 字幕 / 竖屏 / 质量检查 |
| **remotion** | 用代码渲标题卡、片头片尾 |
| **edge-tts** | 免费中文旁白（`zh-CN-YunxiNeural` / `zh-CN-XiaoxiaoNeural`） |

依赖：FFmpeg 7.1 + ffprobe 在 `promo/tools/ffmpeg/bin/`。`kino doctor` 核心项已通过。

英文捷径：`C:\pymcl-promo` → 本仓库（避免 MCP 被中文路径打挂）。

Cursor：**命令面板 → Developer: Reload Window**。这三个会出现在 MCP 列表。全局 IDA / x64dbg 没动。

## 现在请录这 4 段（1080p，每段 20–40 秒）

文件名按这个起，我好对上分镜：

1. `01-open-ai.mp4` — 打开启动器，点进 AI 页
2. `02-install-game.mp4` — 打「下一款游戏 1.20.1 Fabric」→ 选项 → 确认 → 下载任务走动
3. `03-mods.mp4` — 「装钠和光影」同样走一遍
4. `04-crash.mp4` — 「启动闪退了帮我看」出诊断

可选：`05-extra.mp4` 启动页 / 实例页空镜。

鼠标大一点，窗口铺满。竖屏以后再裁，先横屏即可。

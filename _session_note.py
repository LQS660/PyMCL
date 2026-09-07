# -*- coding: utf-8 -*-
"""写会话上下文短记。"""
from pathlib import Path
from datetime import datetime

p = Path("会话-2026-08-21.md")
stamp = datetime.now().strftime("%H:%M")
block = f"""
### {stamp} · 全量落地并启动 UI
- 用户要求：全部/全量落地，然后启动 UI 查看
- 动作：跑 `_fill_en_all.py` 全量补 en；确认 WinUI3 三页与 PySide6 已落地；`python main.py` 启动 GUI
- 验证：见同目录命令输出
"""
if p.exists():
    text = p.read_text(encoding="utf-8")
    # 插到时间线靠前
    marker = "## 时间线"
    if marker in text:
        text = text.replace(marker, marker + "\n" + block, 1)
    else:
        text = block + "\n" + text
    p.write_text(text, encoding="utf-8")
print("session note ok")

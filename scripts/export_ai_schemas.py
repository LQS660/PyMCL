# -*- coding: utf-8 -*-
"""从 mclauncher/ai/tools.py 程序化导出 36 工具 schema 与元数据为 C 头文件（T9）。

用法：python scripts/export_ai_schemas.py
产物（native/src/，勿手改）：
- ai_tools_schemas.h  K_TOOL_SCHEMAS[]：TOOL_SCHEMAS 逐条 JSON 字符串
- ai_tools_meta.h     K_TOOL_META[]：{name, readonly, side_effect, risk, long_running}
对照验收：tools.py 与头文件逐字一致（GOAL 4.C「TOOL_META 逐字对齐」）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mclauncher.ai.tools import TOOL_META, TOOL_SCHEMAS  # noqa: E402


def main() -> int:
    out_dir = ROOT / "native" / "src"
    lines = [
        "/* 由 mclauncher/ai/tools.py TOOL_SCHEMAS 程序化导出（scripts/export_ai_schemas.py），勿手改。",
        "   逐字对齐验收见 docs/GOAL-c-bridge-no-python.md T9。 */",
        "static const char *K_TOOL_SCHEMAS[] = {",
    ]
    for s in TOOL_SCHEMAS:
        j = json.dumps(s, ensure_ascii=False, separators=(",", ":")).replace('"', '\\"')
        lines.append('    "%s",' % j)
    lines.append("    NULL };")
    (out_dir / "ai_tools_schemas.h").write_text("\n".join(lines) + "\n", encoding="utf-8")

    rows = []
    for n, m in TOOL_META.items():
        rows.append('{"%s", %d, "%s", "%s", %d}' % (
            n, int(bool(m.readonly)), m.side_effect, m.risk, int(bool(m.long_running))))
    (out_dir / "ai_tools_meta.h").write_text(
        "/* 由 tools.py TOOL_META 导出（scripts/export_ai_schemas.py），勿手改。"
        "字段: name, readonly, side_effect, risk, long_running */\n"
        "typedef struct { const char *name; int readonly; const char *side_effect; "
        "const char *risk; int long_running; } ai_tool_meta;\n"
        "static const ai_tool_meta K_TOOL_META[] = {\n" + ",\n".join(rows)
        + ",\n    {NULL, 0, \"\", \"\", 0}\n};\n",
        encoding="utf-8")
    print("schemas: %d meta: %d -> %s" % (len(TOOL_SCHEMAS), len(TOOL_META), out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

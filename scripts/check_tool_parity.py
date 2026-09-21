# -*- coding: utf-8 -*-
"""跨端 AI 工具集差异门禁（批次 5.3）。

比对桌面端 mclauncher/ai/tools.py 的 TOOL_META 与 Android 端
android/.../AiTools.kt 的工具注册表，输出差集报告。**只报告不挡门**：
Android 对齐是后续事项（见 docs/audit/agent-gap-20260921.md A7/A8），
但差异必须可见、不许静默——CI 每次都跑这一份。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANDROID_TOOLS = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "pymcl" / "mobile" / "data" / "AiTools.kt"

_ANDROID_TOOL_RE = re.compile(r'\b(?:readOnly|writeOnly)\(\s*"([a-z_]+)"')


def desktop_tools() -> dict:
    """{工具名: readonly}。导入即注册，无副作用。"""
    sys.path.insert(0, str(ROOT))
    from mclauncher.ai.tools import TOOL_META
    return {name: bool(meta.readonly) for name, meta in sorted(TOOL_META.items())}


def android_tools() -> dict:
    """{工具名: readonly}，从 AiTools.kt 的 readOnly()/writeOnly() 注册行解析。"""
    src = ANDROID_TOOLS.read_text("utf-8")
    out = {}
    for m in _ANDROID_TOOL_RE.finditer(src):
        out[m.group(1)] = m.group(0).startswith("readOnly(")
    return dict(sorted(out.items()))


def main() -> int:
    desktop = desktop_tools()
    android = android_tools()
    d_names, a_names = set(desktop), set(android)
    missing_on_android = sorted(d_names - a_names)
    android_only = sorted(a_names - d_names)
    readonly_mismatch = sorted(
        n for n in d_names & a_names if desktop[n] != android.get(n))

    print(f"桌面工具 {len(d_names)} 个 / Android 工具 {len(a_names)} 个")
    print(f"Android 缺失（{len(missing_on_android)} 个）：")
    for n in missing_on_android:
        print(f"  - {n}{'（只读）' if desktop[n] else '（写操作）'}")
    print(f"Android 独有（{len(android_only)} 个）：", android_only or "无")
    print(f"readonly 元数据不一致（{len(readonly_mismatch)} 个）：", readonly_mismatch or "无")
    print("结论：Android AI 工具集落后于桌面（含 ask_user 缺席，写路径未开放执行），"
          "对齐为本轮范围外；下一次对齐以本清单为基线。")

    report = {
        "desktop_count": len(d_names),
        "android_count": len(a_names),
        "missing_on_android": missing_on_android,
        "android_only": android_only,
        "readonly_mismatch": readonly_mismatch,
    }
    out = ROOT / "docs" / "audit" / "tool-parity-latest.json"
    try:
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"机器可读报告已写 {out.relative_to(ROOT)}")
    except OSError as exc:
        print(f"报告写盘失败（不影响门禁）: {exc}")
    return 0   # 只报告不挡门：差异可见即可，不要求通过


if __name__ == "__main__":
    raise SystemExit(main())

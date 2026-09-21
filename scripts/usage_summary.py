# -*- coding: utf-8 -*-
"""回合质量本地聚合视图（批次 6.2，无需云端）。

扫 cache/ai_trace/*.jsonl 里的 turn_summary 事件，按停止原因给分布、
给失败工具率与耗时概况。用法：

    C:/Python312/python.exe scripts/usage_summary.py          # 全部
    C:/Python312/python.exe scripts/usage_summary.py --days 7  # 最近 7 天
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACE_DIR = ROOT / "cache" / "ai_trace"


def load_events(days: int):
    cutoff = time.time() - days * 86400 if days else 0
    rows = []
    if not TRACE_DIR.is_dir():
        return rows
    for f in TRACE_DIR.glob("*.jsonl"):
        try:
            if f.stat().st_mtime < cutoff:
                continue
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("event") == "turn_summary":
                    rows.append(e)
        except OSError:
            continue
    return rows


def fmt_dur(sec) -> str:
    try:
        sec = float(sec)
    except (TypeError, ValueError):
        return "?"
    return f"{sec:.1f}s" if sec < 90 else f"{sec / 60:.1f}m"


def main() -> int:
    ap = argparse.ArgumentParser(description="PyMCL AI 回合质量聚合（本地）")
    ap.add_argument("--days", type=int, default=0, help="只统计最近 N 天（0=全部）")
    args = ap.parse_args()

    rows = load_events(args.days)
    if not rows:
        print(f"没有 turn_summary 记录（扫了 {TRACE_DIR}）。跑几轮 AI 对话后再来。")
        return 0

    stops = Counter(str(r.get("stop_reason")) for r in rows)
    total = len(rows)
    tools = sum(int(r.get("tools") or 0) for r in rows)
    failures = sum(int(r.get("tool_failures") or 0) for r in rows)
    durations = [float(r["elapsed"]) for r in rows
                 if isinstance(r.get("elapsed"), (int, float))]
    avg = sum(durations) / len(durations) if durations else 0.0

    print(f"回合总数: {total}" + (f"（最近 {args.days} 天）" if args.days else ""))
    print("\n按停止原因分布：")
    for reason, n in stops.most_common():
        print(f"  {reason:<16} {n:>5}  ({n * 100 // max(1, total)}%)")
    print(f"\n工具调用: {tools} 次，失败 {failures} 次"
          f"（失败率 {failures * 100 / max(1, tools):.0f}%）")
    print(f"回合耗时: 平均 {fmt_dur(avg)} / 最长 {fmt_dur(max(durations or [0]))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

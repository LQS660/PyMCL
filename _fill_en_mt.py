# -*- coding: utf-8 -*-
"""把 en.json 里仍含中文（或被规则半翻糟）的条目机翻补齐，每 10 条落盘。"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCALES = ROOT / "mclauncher" / "locales"
CJK = re.compile(r"[\u4e00-\u9fff]")
EN_PATH = LOCALES / "en.json"
ZH_PATH = LOCALES / "zh_CN.json"


def main() -> int:
    try:
        from deep_translator import GoogleTranslator
    except Exception:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "deep-translator"])
        from deep_translator import GoogleTranslator

    zh = json.loads(ZH_PATH.read_text("utf-8"))
    en = json.loads(EN_PATH.read_text("utf-8"))
    # 半翻糟了的：译文仍含汉字 → 回退成中文原文再机翻
    pending = [k for k, v in en.items() if CJK.search(v or "")]
    print(f"pending={len(pending)}", flush=True)
    tr = GoogleTranslator(source="zh-CN", target="en")
    ok = fail = 0
    for i, k in enumerate(pending, 1):
        src = zh.get(k) or k
        try:
            dst = tr.translate(src)
            if dst and isinstance(dst, str) and not CJK.search(dst):
                en[k] = dst
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1
        if i % 10 == 0 or i == len(pending):
            ordered = {kk: en[kk] for kk in sorted(en)}
            EN_PATH.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", "utf-8")
            still = sum(1 for v in en.values() if CJK.search(v or ""))
            print(f"[{i}/{len(pending)}] ok={ok} fail={fail} still_cjk={still}", flush=True)
            time.sleep(0.15)
    still = sum(1 for v in en.values() if CJK.search(v or ""))
    print(f"done en={len(en)} still_cjk={still}", flush=True)
    return 0 if still < 50 else 1


if __name__ == "__main__":
    raise SystemExit(main())

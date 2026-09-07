# -*- coding: utf-8 -*-
"""用 MyMemory 免费 API（短超时）补齐 en.json 仍含中文的条目。"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EN_PATH = ROOT / "mclauncher" / "locales" / "en.json"
ZH_PATH = ROOT / "mclauncher" / "locales" / "zh_CN.json"
CJK = re.compile(r"[\u4e00-\u9fff]")


def mt(text: str, timeout: float = 4.0) -> str | None:
    q = urllib.parse.quote(text[:450])
    url = f"https://api.mymemory.translated.net/get?q={q}&langpair=zh-CN|en-US"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        out = (data.get("responseData") or {}).get("translatedText") or ""
        out = out.strip()
        if not out or CJK.search(out):
            return None
        # MyMemory 偶发返回 QUERY LENGTH LIMIT 之类
        if "QUERY LENGTH" in out.upper() or out.upper().startswith("MYMEMORY"):
            return None
        return out
    except Exception:
        return None


def main() -> int:
    zh = json.loads(ZH_PATH.read_text("utf-8"))
    en = json.loads(EN_PATH.read_text("utf-8"))
    # 先把半翻糟的恢复成中文原文，避免残留 Download板块 这种
    pending = []
    for k, v in list(en.items()):
        if CJK.search(v or ""):
            en[k] = zh.get(k) or k
            pending.append(k)
    print(f"pending={len(pending)}", flush=True)
    ok = fail = 0
    for i, k in enumerate(pending, 1):
        src = zh.get(k) or k
        dst = mt(src)
        if dst:
            en[k] = dst
            ok += 1
        else:
            fail += 1
        if i % 10 == 0 or i == len(pending):
            EN_PATH.write_text(
                json.dumps({kk: en[kk] for kk in sorted(en)}, ensure_ascii=False, indent=2) + "\n",
                "utf-8",
            )
            still = sum(1 for v in en.values() if CJK.search(v or ""))
            print(f"[{i}/{len(pending)}] ok={ok} fail={fail} still_cjk={still}", flush=True)
            time.sleep(0.05)
    still = sum(1 for v in en.values() if CJK.search(v or ""))
    print(f"done en={len(en)} still_cjk={still} cov_keys={len(en)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

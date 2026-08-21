# -*- coding: utf-8 -*-
"""深色模式覆盖审计：找出缺 restyle / 硬编码浅色 / 配置键不一致。"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
PAGES = APP / "pages"

LIGHT_HEX = {
    "#FFFFFF", "#FFF", "#F3F7F5", "#F0F4F8", "#EEF3F7", "#F4F6F5",
    "#E8F6EF", "#EFEFEF", "#F5F5F5", "#FAFAFA", "#EEEEEE", "#F8F8F8",
    "#2B2B2B", "#1B7A54", "#E6E6E6", "#FDECEC", "#FFF8E8",
}

KEY_PATTERNS = [
    r'["\']ui_dark["\']',
    r'["\']ui_dark["\']',
    r'get_setting\(\s*["\']ui_dark',
    r'get_setting\(\s*["\']ui_dark',
]


def scan_py(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    hexes = [h.upper() for h in re.findall(r"#[0-9A-Fa-f]{3,8}\b", text)]
    light = sorted({h if len(h) != 4 else "#" + "".join(c * 2 for c in h[1:]) for h in hexes} & LIGHT_HEX)
    theme_refs = re.findall(r"Theme\.\w+", text)
    return {
        "restyle": bool(re.search(r"def restyle\s*\(", text)),
        "theme_refs": len(theme_refs),
        "theme_attrs": sorted(set(theme_refs)),
        "light_hard": light,
        "setStyleSheet_theme": len(re.findall(r"setStyleSheet\([^)]*Theme\.", text, re.S)),
        "ui_dark": len(re.findall(r'["\']ui_dark["\']', text)),
        "ui_dark_alt": len(re.findall(r'["\']ui_dark["\']', text)),  # same visually in some fonts — check both spellings below
    }


def main():
    print("=== pages restyle coverage ===")
    missing = []
    for p in sorted(PAGES.glob("*.py")):
        if p.name.startswith("_"):
            continue
        info = scan_py(p)
        flag = ""
        if info["theme_refs"] and not info["restyle"]:
            flag = " ** NEEDS restyle **"
            missing.append(p.name)
        print(
            f"{p.name:28} restyle={str(info['restyle']):5} "
            f"Theme={info['theme_refs']:3} ssTheme={info['setStyleSheet_theme']:2} "
            f"light={info['light_hard'] or '-'}{flag}"
        )

    print("\n=== Theme attribute usage (unknown?) ===")
    known = {
        "Theme.dark", "Theme.green", "Theme.green_deep", "Theme.bg", "Theme.card",
        "Theme.line", "Theme.text", "Theme.muted", "Theme.title", "Theme.hover",
        "Theme.chip", "Theme.btn_bg", "Theme.row_hover", "Theme.row_line",
        "Theme.apply", "Theme._version",
    }
    unknown = set()
    for p in list(APP.rglob("*.py")):
        if "__pycache__" in str(p) or "_app_backup" in str(p):
            continue
        for ref in re.findall(r"Theme\.\w+", p.read_text(encoding="utf-8", errors="ignore")):
            if ref not in known:
                unknown.add((ref, p.relative_to(ROOT).as_posix()))
    for ref, loc in sorted(unknown):
        print(f"  {ref} @ {loc}")

    print("\n=== config key spellings (ui_dark / ui_dark) ===")
    # Explicit byte-level: ui_dark vs ui_dark — they look similar; search both ASCII forms
    for label, pat in [("ui_dark", r"ui_dark"), ("ui_dark", r"ui_dark")]:
        hits = []
        for p in ROOT.rglob("*"):
            if p.suffix.lower() not in {".py", ".ts", ".json", ".cs", ".xaml", ".md"}:
                continue
            if any(x in str(p) for x in ("node_modules", "__pycache__", "obj\\", "dist\\", "_app_backup")):
                continue
            try:
                t = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            n = len(re.findall(pat, t))
            if n:
                hits.append((n, p.relative_to(ROOT).as_posix()))
        print(f"  {label}: {sum(n for n,_ in hits)} hits in {len(hits)} files")
        for n, loc in sorted(hits, reverse=True)[:15]:
            print(f"    {n:3} {loc}")

    print("\n=== pages missing restyle but using Theme ===")
    for name in missing:
        print(" ", name)


if __name__ == "__main__":
    main()

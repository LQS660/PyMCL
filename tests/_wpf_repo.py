"""定位 WPF 前端的源码树。

WPF 前端自 2026-09-29 起独立成仓（github.com/LQS660/PyMCL.Wpf），不再住在
本仓的 wpf/ 目录下。本仓里那几个守跨端一致性的测试（i18n 词表、反馈页文案、
侧栏键表）仍要读它的源码，于是这里统一回答一个问题：**WPF 源码在哪。**

查找顺序：

1. 环境变量 `PYMCL_WPF_SRC` 指向的目录（CI 或并行检出时显式指定）；
2. 本仓的 wpf/PyMCL.Wpf（老布局，或把独立仓克隆回来挂在 wpf/ 下）；
3. 与本仓同级目录的 PyMCL.Wpf/PyMCL.Wpf（两个仓并排克隆的常见布局）；
4. 同级目录的 PyMCL.Wpf（独立仓根，源码就在根下的 PyMCL.Wpf/）。

找不到时 `find_src()` 返回 None，调用方据此 skip——独立仓没克隆过来时这些
测试静默跳过，而不是报一堆 FileNotFoundError。
"""
from __future__ import annotations

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_PROJECT = "PyMCL.Wpf"


def _candidates() -> list[Path]:
    seen: list[Path] = []

    def add(p: Path) -> None:
        if p not in seen:
            seen.append(p)

    env = os.environ.get("PYMCL_WPF_SRC")
    if env:
        # 允许直接给到 PyMCL.Wpf/ 这一层，也允许给到仓根
        add(Path(env))
        add(Path(env) / _PROJECT)
    add(REPO / "wpf" / _PROJECT)
    add(REPO.parent / _PROJECT / _PROJECT)
    add(REPO.parent / _PROJECT)
    return seen


def _is_src(p: Path) -> bool:
    return p.is_dir() and (p / "Services" / "I18n.cs").is_file()


def find_src() -> Path | None:
    """WPF 源码目录（含 Services/I18n.cs 的那一层），找不到返回 None。"""
    for p in _candidates():
        if _is_src(p):
            return p
    return None


SRC = find_src()
WPF_EXE = next(
    (p for p in (
        SRC / "bin" / "Debug" / "net8.0-windows" / "PyMCL.Wpf.exe",
        SRC / "bin" / "Release" / "net8.0-windows" / "PyMCL.Wpf.exe",
    ) if p.is_file()),
    None,
) if SRC else None

MISSING_HINT = (
    "找不到 WPF 源码（独立仓 github.com/LQS660/PyMCL.Wpf）。"
    "克隆到本仓同级目录，或设 PYMCL_WPF_SRC 指向源码目录后重跑。"
)

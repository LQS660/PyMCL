# -*- coding: utf-8 -*-
"""内存垃圾回收器预设。对齐 PCL 2.12：G1 / 调优 G1 / ZGC / 不指定。"""
from __future__ import annotations

from .argsplit import split_args

LABELS = {
    "auto": "G1（推荐）",
    "g1": "G1",
    "g1_tuned": "调优 G1",
    "zgc": "ZGC",
    "none": "不指定",
}

ARGS = {
    "auto": "-XX:+UseG1GC -XX:+UnlockExperimentalVMOptions -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 -XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M",
    "g1": "-XX:+UseG1GC",
    "g1_tuned": (
        "-XX:+UseG1GC -XX:+UnlockExperimentalVMOptions -XX:G1NewSizePercent=20 "
        "-XX:G1ReservePercent=20 -XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M "
        "-XX:+DisableExplicitGC -XX:+AlwaysPreTouch -XX:+ParallelRefProcEnabled"
    ),
    "zgc": "-XX:+UseZGC -XX:+UnlockExperimentalVMOptions",
    "none": "",
}

_GC_FLAGS = (
    "-XX:+UseG1GC", "-XX:+UseZGC", "-XX:+UseShenandoahGC", "-XX:+UseParallelGC",
    "-XX:+UseConcMarkSweepGC", "-XX:+UseSerialGC",
)


def preset_args(key: str) -> str:
    return ARGS.get((key or "auto").strip().lower(), ARGS["auto"])


def apply(preset: str, existing: str = "") -> str:
    """把 GC 预设接到已有 JVM 参数前面；已有 GC 旗标时不再重复。"""
    bits = split_args(existing or "")
    if any(a in _GC_FLAGS or a.startswith("-XX:+Use") and "GC" in a for a in bits):
        return (existing or "").strip()
    extra = preset_args(preset)
    if not extra:
        return (existing or "").strip()
    if not existing:
        return extra
    return f"{extra} {existing}".strip()

# -*- coding: utf-8 -*-
"""自定义布局的数据模型与持久化（纯数据层，不依赖 Qt，便于单测）。

坐标采用「画布比例」：x/y/w/h 均为 0..1 的浮点，表示相对画布可视区域
的比例。窗口任意缩放时布局按比例随之伸缩，避免绝对像素在小窗口溢出。
编辑时的拖拽/吸附在像素空间进行，落点再换算回比例存盘。

持久化键（config.json）：
  ui_layout          当前生效的布局文档（None/缺省 = 内置默认布局）
  ui_layouts         {方案名: 文档} 已保存的布局方案
  ui_layout_profile  当前方案名（"" 表示未命名的自定义）
"""

from __future__ import annotations

import json
import time
from pathlib import Path

LAYOUT_VERSION = 1

# 每种卡片的最小尺寸（像素）。交互时用来卡住缩放下限。
CARD_MIN_SIZE: dict[str, tuple[int, int]] = {
    "banner": (340, 150),
    "config": (330, 300),
    "log": (260, 180),
    "news": (220, 180),
    "quick": (220, 150),
    "notes": (180, 130),
    "playtime": (220, 130),
    "tasks": (220, 130),
}

DEFAULT_PROFILE = ""
FALLBACK_MIN = (200, 120)


def min_size_for(card_type: str) -> tuple[int, int]:
    return CARD_MIN_SIZE.get(card_type, FALLBACK_MIN)


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else float(v))


class LayoutItem:
    """画布上的一张卡片。几何全部是画布比例。"""

    __slots__ = ("id", "type", "x", "y", "w", "h", "z", "hidden", "settings")

    def __init__(self, item_type: str, x: float, y: float, w: float, h: float,
                 item_id: str = "", z: int = 0, hidden: bool = False,
                 settings: dict | None = None):
        self.id = item_id or f"{item_type}-{int(time.time() * 1000) % 100000000}"
        self.type = str(item_type)
        self.x = _clamp01(x)
        self.y = _clamp01(y)
        self.w = max(0.04, min(1.0, float(w)))
        self.h = max(0.04, min(1.0, float(h)))
        self.z = int(z)
        self.hidden = bool(hidden)
        self.settings: dict = dict(settings or {})

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type,
            "x": round(self.x, 5), "y": round(self.y, 5),
            "w": round(self.w, 5), "h": round(self.h, 5),
            "z": self.z, "hidden": self.hidden, "settings": self.settings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LayoutItem":
        return cls(
            str(data.get("type") or "notes"),
            float(data.get("x") or 0.0),
            float(data.get("y") or 0.0),
            float(data.get("w") or 0.3),
            float(data.get("h") or 0.3),
            item_id=str(data.get("id") or ""),
            z=int(data.get("z") or 0),
            hidden=bool(data.get("hidden")),
            settings=dict(data.get("settings") or {}),
        )

    def geometry_px(self, size: tuple[int, int]) -> tuple[int, int, int, int]:
        """换算为画布像素几何 (x, y, w, h)。"""
        cw, ch = size
        return (
            int(round(self.x * cw)),
            int(round(self.y * ch)),
            max(1, int(round(self.w * cw))),
            max(1, int(round(self.h * ch))),
        )

    def set_geometry_px(self, x: int, y: int, w: int, h: int, size: tuple[int, int]):
        """从画布像素几何写回比例（clamp 到画布内）。"""
        cw, ch = size
        cw = max(1, cw)
        ch = max(1, ch)
        w = max(1, min(w, cw))
        h = max(1, min(h, ch))
        x = max(0, min(x, cw - w))
        y = max(0, min(y, ch - h))
        self.x = _clamp01(x / cw)
        self.y = _clamp01(y / ch)
        self.w = max(0.01, min(1.0, w / cw))
        self.h = max(0.01, min(1.0, h / ch))


class LayoutDoc:
    """一份完整布局：网格吸附步长 + 卡片列表。"""

    def __init__(self, items: list[LayoutItem] | None = None, grid: int = 8):
        self.items: list[LayoutItem] = list(items or [])
        # 吸附网格（像素）。0 = 完全自由，不吸附。
        self.grid = int(grid)

    # ---- 序列化 ----
    def to_dict(self) -> dict:
        self.normalize()
        return {
            "version": LAYOUT_VERSION,
            "grid": self.grid,
            "items": [it.to_dict() for it in self.items],
        }

    @classmethod
    def from_dict(cls, data) -> "LayoutDoc":
        if not isinstance(data, dict):
            return default_doc()
        try:
            grid = int(data.get("grid", 8))
        except (TypeError, ValueError):
            grid = 8
        doc = cls(grid=max(0, grid))
        raw = data.get("items")
        if isinstance(raw, list):
            for row in raw:
                if isinstance(row, dict):
                    doc.items.append(LayoutItem.from_dict(row))
        if not doc.items:
            return default_doc()
        doc.normalize()
        return doc

    def normalize(self):
        """修 id 重复 / z 序空洞；交互层每次落盘前调用。"""
        seen = set()
        for i, it in enumerate(self.items):
            base = it.id or f"{it.type}-{i}"
            nid, n = base, 2
            while nid in seen:
                nid = f"{base}-{n}"
                n += 1
            it.id = nid
            seen.add(nid)
        for z, it in enumerate(sorted(self.items, key=lambda i: i.z)):
            it.z = z

    def clone(self) -> "LayoutDoc":
        return LayoutDoc.from_dict(json.loads(json.dumps(self.to_dict())))

    # ---- 查询/修改 ----
    def get(self, item_id: str) -> LayoutItem | None:
        for it in self.items:
            if it.id == item_id:
                return it
        return None

    def next_z(self) -> int:
        return max((it.z for it in self.items), default=-1) + 1

    def visible_items(self) -> list[LayoutItem]:
        return [it for it in sorted(self.items, key=lambda i: i.z) if not it.hidden]


def default_doc() -> LayoutDoc:
    """内置默认布局：还原改造前启动页的版式（横幅通栏 + 三栏）。"""
    return LayoutDoc([
        LayoutItem("banner", 0.0, 0.0, 1.0, 0.26, item_id="banner-main", z=0),
        LayoutItem("config", 0.0, 0.275, 0.315, 0.725, item_id="config-main", z=1),
        LayoutItem("log", 0.325, 0.275, 0.41, 0.725, item_id="log-main", z=2),
        LayoutItem("news", 0.745, 0.275, 0.255, 0.725, item_id="news-main", z=3),
    ], grid=8)


# ----------------------------------------------------------------------
# 持久化（直接走 CONFIG；不走 backend.save_settings 的白名单）
# ----------------------------------------------------------------------
def _cfg():
    from mclauncher.config import CONFIG
    return CONFIG


def load_active_doc() -> LayoutDoc:
    raw = _cfg().get("ui_layout")
    if not raw:
        return default_doc()
    return LayoutDoc.from_dict(raw)


def save_active_doc(doc: LayoutDoc, profile: str | None = None):
    cfg = _cfg()
    cfg.set("ui_layout", doc.to_dict())
    if profile is not None:
        cfg.set("ui_layout_profile", profile)
    cfg.save()


def active_profile() -> str:
    return str(_cfg().get("ui_layout_profile") or DEFAULT_PROFILE)


def list_profiles() -> dict[str, dict]:
    raw = _cfg().get("ui_layouts")
    return dict(raw) if isinstance(raw, dict) else {}


def save_profile(name: str, doc: LayoutDoc):
    name = (name or "").strip()
    if not name:
        return
    cfg = _cfg()
    profiles = list_profiles()
    profiles[name] = doc.to_dict()
    cfg.set("ui_layouts", profiles)
    cfg.set("ui_layout_profile", name)
    cfg.set("ui_layout", profiles[name])
    cfg.save()


def activate_profile(name: str) -> LayoutDoc:
    cfg = _cfg()
    name = (name or "").strip()
    if not name:
        cfg.set("ui_layout", None)
        cfg.set("ui_layout_profile", DEFAULT_PROFILE)
        cfg.save()
        return default_doc()
    doc_data = list_profiles().get(name)
    if doc_data is None:
        # 指名的方案不存在：回落默认并修正记录，避免死键。
        cfg.set("ui_layout", None)
        cfg.set("ui_layout_profile", DEFAULT_PROFILE)
        cfg.save()
        return default_doc()
    cfg.set("ui_layout", doc_data)
    cfg.set("ui_layout_profile", name)
    cfg.save()
    return LayoutDoc.from_dict(doc_data)


def delete_profile(name: str) -> bool:
    name = (name or "").strip()
    profiles = list_profiles()
    if name not in profiles:
        return False
    del profiles[name]
    cfg = _cfg()
    cfg.set("ui_layouts", profiles)
    if active_profile() == name:
        cfg.set("ui_layout", None)
        cfg.set("ui_layout_profile", DEFAULT_PROFILE)
    cfg.save()
    return True


def reset_to_default():
    cfg = _cfg()
    cfg.set("ui_layout", None)
    cfg.set("ui_layout_profile", DEFAULT_PROFILE)
    cfg.save()


def export_doc(doc: LayoutDoc, path: str) -> bool:
    try:
        Path(path).write_text(
            json.dumps(doc.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8")
        return True
    except OSError:
        return False


def import_doc(path: str) -> LayoutDoc | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return None
    doc = LayoutDoc.from_dict(data)
    # 未知卡片类型（旧版本导出/手改的文件）直接丢弃，不进文档占 z 序
    doc.items = [it for it in doc.items if it.type in CARD_MIN_SIZE]
    return doc if doc.items else None

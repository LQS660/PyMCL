# -*- coding: utf-8 -*-
"""启动页自定义布局的数据模型与持久化（纯数据层，不依赖任何 UI 框架）。

Qt 版（app/dashboard.py）与 eziapp（bridge/api.py 的 *_layout RPC）共用这一份：
两套界面读写的是同一组 config.json 键，在一边拖好的布局另一边打开就是同一个。
历史位置 app/layout_model.py 保留为 re-export，Qt 侧引用不用改。

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

__all__ = [
    "LAYOUT_VERSION", "CARD_MIN_SIZE", "DEFAULT_PROFILE", "FALLBACK_MIN",
    "LayoutItem", "LayoutDoc", "min_size_for", "default_doc", "parse_doc",
    "load_active_doc", "save_active_doc", "active_profile", "list_profiles",
    "save_profile", "activate_profile", "delete_profile", "reset_to_default",
    "export_doc", "import_doc",
]

LAYOUT_VERSION = 1

# 每种卡片的最小尺寸（像素）。交互时用来卡住缩放下限。
# skin 只有 eziapp 会渲染；Qt 遇到不认识的类型直接跳过，放在这里是为了
# 两边导入/校验时用同一张白名单，eziapp 存的皮肤卡不会被 Qt 的导入丢掉。
CARD_MIN_SIZE: dict[str, tuple[int, int]] = {
    # 横幅 125：卡片本体最小高 = 这里 + 标题栏 40 = 165，扣掉正文宿主的
    # 16px 上下边距正好 149，压着渐变 Hero 自己那 148（量出来的：上下各 26 的
    # 边距 + kicker 16 + 6 + 大标题 39 + 6 + 副标题 17）。横幅里只剩渐变 Hero
    # （启动/停止按钮、进度条、状态行都在启动坞），再给高就多余；矮窗口下
    # 过高的下限会顶过比例高度，把下面那张卡压掉一截。
    "banner": (340, 125),
    "config": (330, 300),
    "log": (260, 180),
    "news": (220, 180),
    "quick": (220, 150),
    "notes": (180, 130),
    "playtime": (220, 130),
    "tasks": (220, 130),
    "skin": (160, 200),
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
        if not doc.items and not isinstance(raw, list):
            # items 缺失 / 不是列表 = 这份数据压根不是布局文档，回落默认。
            # 显式的空列表是用户自己把卡片删光了，照原样留着——换成默认布局
            # 等于下次开机又给他塞回四张卡。
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
    """内置默认布局：横幅通栏 + 左侧启动配置，其余留空。

    实时日志和新闻都不在出厂版式里，想要的人自己在「编辑布局 → 添加卡片」
    里加回来（两种类型仍在 CARD_MIN_SIZE 白名单内，加回来还落在各自那一栏）。
    空出来的右半边留给启动页右下角的启动坞（LaunchPage._build_launch_dock）
    ——那块空着，坞才一张卡都不压。

    启动/停止按钮也不在这几张卡片里，卡片被用户删光了照样能开游戏。
    """
    # 横幅 0.30 而不是 0.26：0.26 在矮窗口里换算出来比横幅卡的最小高（165）还
    # 小，会被下限顶出去、压住下面那张卡。0.30 让比例高度在 1180x600 上就已经
    # 够到下限，四档常见窗口高度下两张卡都隔着 4~10px 不挨着。
    return LayoutDoc([
        LayoutItem("banner", 0.0, 0.0, 1.0, 0.30, item_id="banner-main", z=0),
        LayoutItem("config", 0.0, 0.315, 0.315, 0.685, item_id="config-main", z=1),
    ], grid=8)


def parse_doc(data) -> LayoutDoc | None:
    """严格解析一份外来文档（导入文件 / 前端提交）。

    与 from_dict 的区别：结构不对返回 None 而不是悄悄换成默认布局——
    落盘一份「用户以为是自己的」默认布局比报错更糟。未知卡片类型
    （旧版本导出 / 手改的文件）直接丢弃，不进文档占 z 序。
    """
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return None
    if not data["items"]:
        # from_dict 会把空列表悄悄换成默认布局；作为「外来文档」它就是无效的
        return None
    doc = LayoutDoc.from_dict(data)
    doc.items = [it for it in doc.items if it.type in CARD_MIN_SIZE]
    return doc if doc.items else None


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
    return parse_doc(data)

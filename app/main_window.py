# -*- coding: utf-8 -*-
"""主窗口：细顶栏 + 主侧栏（启动/下载/AI 助手/更多）+ 底部下载任务。

页面懒加载：__init__ 只构造首屏必需的壳（启动页、下载/更多分区壳、
任务页），其余 16 个子页 + AI 页记录成工厂，第一次导航进入才构造。
冷启动从「同步建 21 个页面（每个还各自扫一遍磁盘）」变成建 4 个。
"""

import os
import time

from qfluentwidgets import FluentIcon as FIF, InfoBar, InfoBarPosition, setTheme, setThemeColor, Theme as FluentTheme
from qfluentwidgets.window.fluent_window import FluentWindowBase
from PySide6.QtCore import Qt, QEasingCurve, QEvent, QPoint, QPropertyAnimation, QTimer
from PySide6.QtWidgets import QApplication, QLabel

from mclauncher import APP_DISPLAY_NAME, APP_VERSION
from .backend import BackendAPI
from .background import BackgroundLayer, WallpaperPlaylist
from .fly_anim import fly_to
from .pcl_chrome import (
    Theme, fade_stack_to, paint_theme_surfaces, ensure_theme_surfaces,
    PclSideBar, PclTitleBar, TITLE_H, SIDE_W, install_infobar_offsets,
)
from .widgets import pick_color
from .pages.launch_page import LaunchPage
from .pages.download_hub import DownloadSection, MoreSection
from .pages.tasks_page import DownloadDock, TasksPage
from mclauncher.i18n import tr

# 分区默认成员（子页归属可由 ui_section_members 自定义：哪栏、栏内顺序）
_SUB_DEFAULT_MEMBERS = {
    "download": ["version", "mod", "modpack", "datapack", "resource", "shader", "world", "java"],
    "more": ["instance", "mods", "account", "multiplayer", "servers", "playtime", "feedback", "settings"],
}
_ALL_SUB_KEYS = frozenset(k for keys in _SUB_DEFAULT_MEMBERS.values() for k in keys)
_TOP_KEYS = ("launch", "download", "ai", "more", "tasks")

# 子页标题与工厂方法名（归属按配置动态决定，这两份是静态元数据）
_SUB_TITLES = {
    "version": "原版游戏", "mod": "Mod", "modpack": "整合包", "datapack": "数据包",
    "resource": "资源包", "shader": "光影包", "world": "世界", "java": "Java",
    # instance 这个 key 只剩历史含义（已保存的侧栏布局按它认页面），现在开的是版本管理
    "instance": "版本管理", "mods": "模组", "account": "账号", "multiplayer": "联机",
    "servers": "服务器", "playtime": "时长", "feedback": "反馈", "settings": "设置",
}
_SUB_FACTORIES = {
    "version": "_make_version_page", "mod": "_make_mod_page",
    "modpack": "_make_modpack_page", "datapack": "_make_datapack_page",
    "resource": "_make_resource_page", "shader": "_make_shader_page",
    "world": "_make_world_page", "java": "_make_java_page",
    "instance": "_make_instance_page", "mods": "_make_mods_page",
    "account": "_make_account_page", "multiplayer": "_make_multiplayer_page",
    "servers": "_make_servers_page", "playtime": "_make_playtime_page",
    "feedback": "_make_feedback_page", "settings": "_make_settings_page",
}


def sub_title(key: str) -> str:
    return tr(_SUB_TITLES.get(key, key))


def section_members_from_config() -> dict[str, list[str]]:
    """读 ui_section_members：{download: [key…], more: [key…]}。

    非法键剔除、重复去重、漏掉的子页按默认归属补齐，顺序保留用户排列。
    """
    from mclauncher.config import CONFIG
    pinned = set(pinned_from_config())
    raw = CONFIG.get("ui_section_members")
    result: dict[str, list[str]] = {}
    seen: set[str] = set()
    for sec in ("download", "more"):
        keys = raw.get(sec) if isinstance(raw, dict) else None
        picked = []
        for k in keys or []:
            # 固定到侧栏的子页不属于任何分区（拖出去 = 移动），
            # 配置里残留的成员记录也一并忽略
            if k in _ALL_SUB_KEYS and k not in seen and k not in pinned:
                seen.add(k)
                picked.append(k)
        result[sec] = picked
    for sec, defaults in _SUB_DEFAULT_MEMBERS.items():
        for k in defaults:
            if k not in seen and k not in pinned:
                seen.add(k)
                result[sec].append(k)
    return result


def _default_section_for(key: str) -> str:
    for sec, defaults in _SUB_DEFAULT_MEMBERS.items():
        if key in defaults:
            return sec
    return "more"


# 拖进窗口的整合包落到哪一页：版本管理（key 沿用历史的 instance）
_MODPACK_LANDING_KEY = "instance"

# 侧栏一级项的图标与标题（供自定义排序/显隐重建用）
_NAV_SPECS = {
    "launch": (FIF.PLAY, "启动"),
    "download": (FIF.DOWNLOAD, "游戏"),
    "ai": (getattr(FIF, "CHAT", None) or FIF.HELP, "AI 助手"),
    "more": (getattr(FIF, "MORE", None) or FIF.MENU, "更多"),
    "tasks": (FIF.CLOUD_DOWNLOAD, "下载任务"),
}

# 出厂侧栏：排法见 _DEFAULT_NAV_STYLE；下面这三个键是「精简」那一档的序列，
# 切回精简时还按它们排。改这里要同时把 _NAV_DEFAULTS_VERSION 加一，老用户才会
# 收到新默认——但只在他没动过侧栏时，动过就以他排的为准。
_NAV_DEFAULTS_VERSION = "2026.09-ai-visible"
_DEFAULT_NAV_ORDER = ("launch", "download", "instance", "ai", "more", "settings", "tasks")
_DEFAULT_NAV_PINNED = ("instance", "settings")
_DEFAULT_NAV_HIDDEN = ()
# 历史上的出厂三件套，见 _nav_untouched
_LEGACY_NAV_FACTORIES = (
    # 2026.09-grouped：AI 出厂藏着，精简序列里也没有它
    {"ui_nav_order": ("launch", "download", "instance", "more", "settings", "tasks"),
     "ui_nav_pinned": ("instance", "settings"),
     "ui_nav_hidden": ("ai",)},
)
# 这些键排在分隔线以下，靠侧栏底部。精简档的招牌是线上正好三项
# （启动 / 游戏 / 版本管理），AI 跟「更多」那一撮一起沉底
_BOTTOM_KEYS = ("ai", "more", "settings", "tasks")

# 侧栏两种排法。compact = 三个主入口 + 沉底那一撮；grouped = HMCL 那样按
# 账户 / 游戏 / 通用 分组，组标题只是文字，不可点。
NAV_STYLE_COMPACT = "compact"
NAV_STYLE_GROUPED = "grouped"
NAV_STYLE_LABELS = {
    NAV_STYLE_COMPACT: "精简（启动 / 游戏 / 版本管理）",
    NAV_STYLE_GROUPED: "分组（账户 / 游戏 / 通用）",
}
_GROUPED_NAV = (
    ("账户", ("account",)),
    ("游戏", ("launch", "instance", "download")),
    ("通用", ("settings", "multiplayer", "ai", "more", "tasks")),
)
# 组里另用的名字：「游戏」组底下再写一项「游戏」会读成套娃
_GROUPED_LABELS = {"download": "下载", "multiplayer": "多人联机"}
# 出厂分组里当成「已固定」的子页：它们进侧栏，就不该再长在分区横条上。
# 用户拖动之后以 grouped_layout() 为准，这一份只是没自定义过时的底稿。
_GROUPED_PINNED = tuple(
    k for _title, keys in _GROUPED_NAV for k in keys if k in _ALL_SUB_KEYS)
# 出厂排法
_DEFAULT_NAV_STYLE = NAV_STYLE_GROUPED


def nav_style() -> str:
    from mclauncher.config import CONFIG
    style = str(CONFIG.get("ui_nav_style") or _DEFAULT_NAV_STYLE)
    return style if style in NAV_STYLE_LABELS else _DEFAULT_NAV_STYLE


def grouped_layout() -> list[tuple[str, list[str]]]:
    """分组排法的分组与成员：用户拖过就以 ui_nav_groups 为准，没动过用出厂的。

    这份表以前是写死的常量，于是「把子页拖到侧栏」在分组档下全程静默失败：
    拖拽照收、配置照写、侧栏照重建，重建时却按常量重新生成一遍，刚写进去的
    东西一点不剩。做成数据之后，固定 / 取消固定 / 重排都落在同一份表上。

    一级键缺席要补回来：存进去的表被手改坏、或某个键是新加的，漏掉它就等于
    这一页在界面上彻底没了入口。
    """
    from mclauncher.config import CONFIG
    raw = CONFIG.get("ui_nav_groups")
    groups: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for grp in raw:
            if not isinstance(grp, dict):
                continue
            title = str(grp.get("title") or "").strip()
            if not title:
                continue
            keys = [k for k in (grp.get("keys") or [])
                    if isinstance(k, str)
                    and (k in _TOP_KEYS or k in _ALL_SUB_KEYS)
                    and not (k in seen or seen.add(k))]
            groups.append((title, keys))
    if not any(keys for _t, keys in groups):
        return [(title, list(keys)) for title, keys in _GROUPED_NAV]
    missing = [k for k in _TOP_KEYS if k not in seen]
    if missing:
        groups[-1][1].extend(missing)
    return groups


def save_grouped_layout(groups) -> None:
    from mclauncher.config import CONFIG
    CONFIG.set("ui_nav_groups",
               [{"title": title, "keys": list(keys)} for title, keys in groups])
    CONFIG.save()


def move_within_groups(groups, key: str, target: str, before: bool) -> bool:
    """把 key 挪到 target 的前/后（可跨组）。目标不在表里就原样不动。

    先确认目标存在再摘 key：反过来写的话，目标找不到时 key 已经被摘掉了，
    一次失败的拖拽就能让这一项从侧栏上消失。
    """
    if key == target or not any(target in keys for _t, keys in groups):
        return False
    for _title, keys in groups:
        if key in keys:
            keys.remove(key)
    for _title, keys in groups:
        if target in keys:
            keys.insert(keys.index(target) + (0 if before else 1), key)
            return True
    return False


def grouped_nav_items() -> list:
    """HMCL 式分组侧栏。隐藏项照 ui_nav_hidden 走，整组空了连标题一起不出。"""
    from mclauncher.config import CONFIG
    hidden = set(CONFIG.get("ui_nav_hidden") or [])
    items = []
    for title, keys in grouped_layout():
        visible = [k for k in keys if k not in hidden]
        if not visible:
            continue
        items.append(("header", tr(title)))
        for key in visible:
            if key in _TOP_KEYS:
                fif, label = _NAV_SPECS[key]
                items.append(("item", key, fif,
                              tr(_GROUPED_LABELS.get(key, label)), False, False))
            else:
                spec = _pinned_nav_spec(key)
                if key in _GROUPED_LABELS:
                    spec = (*spec[:3], tr(_GROUPED_LABELS[key]), *spec[4:])
                items.append(spec)
    return items


def _nav_factory() -> dict:
    return {
        "ui_nav_order": _DEFAULT_NAV_ORDER,
        "ui_nav_pinned": _DEFAULT_NAV_PINNED,
        "ui_nav_hidden": _DEFAULT_NAV_HIDDEN,
    }


def _nav_untouched() -> bool:
    """侧栏还是**某一版**出厂那一套（没排过、没藏过、没另外固定过）。

    只跟当前这一版比是不够的：上一版的出厂值同样是用户没动过的样子，
    认不出来就会被当成自定义，新默认永远发不到他手上。
    """
    from mclauncher.config import CONFIG
    stored = {k: list(CONFIG.get(k) or []) for k in _nav_factory()}
    return any(
        all(not stored[key] or stored[key] == list(value)
            for key, value in factory.items())
        for factory in (_nav_factory(), *_LEGACY_NAV_FACTORIES))


def ensure_default_nav() -> bool:
    """侧栏还是一张白纸时，写进出厂布局。返回是否真的写了。

    判据是「三个键全空」，不是版本号标记：标记和三个键分两次落盘，中间
    被别的进程写一次 config.json，就会留下「标记已记、布局没写」的夹生态，
    此后每次开机都以为写过了，用户永远拿不到新默认。空就写，写完自然不空，
    天然幂等，也不用担心两边抢着写。

    换出厂布局（_NAV_DEFAULTS_VERSION 变了）时，还照着上一版出厂样子用的
    老用户整套跟着换一次——这三个键每份 config.json 里都写着字面值，不认版本号
    的话他们永远停在旧默认上（AI 那一项就是这么在侧栏里消失了一整版）。
    自己排过侧栏的不动。
    """
    from mclauncher.config import CONFIG
    if (CONFIG.get("ui_nav_order") or CONFIG.get("ui_nav_pinned")
            or CONFIG.get("ui_nav_hidden")):
        if CONFIG.get("ui_nav_defaults") != _NAV_DEFAULTS_VERSION:
            if _nav_untouched():
                CONFIG.update({k: list(v) for k, v in _nav_factory().items()})
                CONFIG.set("ui_nav_style", _DEFAULT_NAV_STYLE)
                CONFIG.set("ui_nav_groups", None)
            CONFIG.set("ui_nav_defaults", _NAV_DEFAULTS_VERSION)
            CONFIG.save()
        return False
    CONFIG.update({k: list(v) for k, v in _nav_factory().items()})
    CONFIG.update({
        "ui_nav_style": _DEFAULT_NAV_STYLE,
        "ui_nav_defaults": _NAV_DEFAULTS_VERSION,
    })
    CONFIG.save()
    return True


def pinned_from_config() -> list[str]:
    """固定到顶级侧栏的分区子页 key（拖拽固定，非法键过滤）。"""
    from mclauncher.config import CONFIG
    if nav_style() == NAV_STYLE_GROUPED:
        # 分组排法的固定项就是各组里的子页成员，ui_nav_pinned 在这一档不参与
        hidden = set(CONFIG.get("ui_nav_hidden") or [])
        return [k for _title, keys in grouped_layout() for k in keys
                if k in _ALL_SUB_KEYS and k not in hidden]
    raw = CONFIG.get("ui_nav_pinned") or []
    seen, picked = set(), []
    for k in raw:
        if k in _ALL_SUB_KEYS and k not in seen:
            seen.add(k)
            picked.append(k)
    return picked


def _pinned_nav_spec(key: str):
    from .pages.home_cards import quick_icon
    return ("item", key, quick_icon(key), sub_title(key), False, True)


def nav_items_from_config() -> list:
    """生成侧栏条目：一级项与固定的分区子页按 ui_nav_order 混排。

    ui_nav_order 是完整序列（可同时含一级键和固定子页键，拖拽自由混排
    的落点就存在这里）；没进序列的固定子页插在「更多」前（都不在则插在
    「下载任务」前 / 末尾），一级键缺失自动补到末尾。
    """
    from mclauncher.config import CONFIG
    if nav_style() == NAV_STYLE_GROUPED:
        return grouped_nav_items()
    raw = list(CONFIG.get("ui_nav_order") or [])
    pinned = pinned_from_config()
    hidden = set(CONFIG.get("ui_nav_hidden") or [])
    order = []
    for k in raw:
        if k in _TOP_KEYS and k not in order:
            order.append(k)
        elif k in pinned and k not in order:
            order.append(k)
    for k in _TOP_KEYS:
        if k not in order:
            order.append(k)
    # 缺席的固定子页：插到锚点前
    late = [k for k in pinned if k not in order]
    anchor = next((a for a in ("more", "tasks") if a in order), None)
    if late:
        if anchor is not None:
            order[order.index(anchor):order.index(anchor)] = late
        else:
            order.extend(late)
    items = []
    visible = [k for k in order if not (k in _TOP_KEYS and k in hidden)]
    # 分隔线插在第一个「底部键」之前，它和它后面的都被推到侧栏最下方
    split_at = next((i for i, k in enumerate(visible) if k in _BOTTOM_KEYS), -1)
    if split_at <= 0:
        split_at = -1
    for i, key in enumerate(visible):
        if i == split_at:
            items.append(("stretch",))
        if key in _TOP_KEYS:
            fif, title = _NAV_SPECS[key]
            items.append(("item", key, fif, tr(title), False, True))
        else:
            items.append(_pinned_nav_spec(key))
    return items


# ---------------------------------------------------------------- 窗口宽高比
# 壁纸铺在整窗底下、按整窗保比例裁切。窗口比例锁在图片 / 视频常见的档位上，
# 用户挑一张同比例的壁纸就能一点不裁完整显示，拖窗口也不会变成裁头裁脚；
# 档位可在设置里手动改。free = 不锁，随便拖。
WINDOW_ASPECTS: dict[str, float | None] = {"4:3": 4 / 3, "16:9": 16 / 9, "free": None}
WINDOW_ASPECT_LABELS = {"4:3": "标准 4:3", "16:9": "宽屏 16:9", "free": "自由拖动"}
_DEFAULT_WINDOW_ASPECT = "4:3"
# 各档的出厂尺寸（逻辑像素）。侧栏 188 + 下载页横条 628 = 宽至少 ~820；
# 启动页两张卡在这几个尺寸下互不重叠。16:9 不能再矮：横幅有 165 的最小高，
# 画布高 = 窗高 - 64，要 0.315 x 画布高 >= 167 才不压到启动配置卡。
_ASPECT_DEFAULT_SIZE = {"4:3": (960, 720), "16:9": (1072, 603), "free": (1040, 650)}
# 拖边/拖角时 Windows 发 WM_SIZING 的 wParam
_WMSZ_LEFT, _WMSZ_RIGHT, _WMSZ_TOP, _WMSZ_TOPLEFT = 1, 2, 3, 4
_WMSZ_TOPRIGHT, _WMSZ_BOTTOM, _WMSZ_BOTTOMLEFT, _WMSZ_BOTTOMRIGHT = 5, 6, 7, 8
_WM_SIZING, _WM_ENTERSIZEMOVE, _WM_EXITSIZEMOVE = 0x0214, 0x0231, 0x0232


def window_aspect_key() -> str:
    """配置里的比例档位；非法值回出厂 4:3。"""
    from mclauncher.config import CONFIG
    key = str(CONFIG.get("ui_window_aspect") or _DEFAULT_WINDOW_ASPECT)
    return key if key in WINDOW_ASPECTS else _DEFAULT_WINDOW_ASPECT


def window_aspect_ratio() -> float | None:
    """当前锁定的宽/高；None = 自由拖动。"""
    return WINDOW_ASPECTS[window_aspect_key()]


def fit_aspect(width: int, height: int, ratio: float | None, *,
               max_w: int | None = None, max_h: int | None = None,
               min_w: int = 0, min_h: int = 0, drive: str = "width") -> tuple[int, int]:
    """把 (width, height) 收成比例 ratio，并塞进 [min, max] 的盒子里。

    drive="width" 以宽定高（拖左右边），"height" 以高定宽（拖上下边）。
    盒子装不下就整体缩到装得下的最大同比矩形；比最小值还小就整体放大。
    ratio 为 None 只做夹取，不动比例。
    """
    w, h = int(width), int(height)
    if ratio is None or ratio <= 0:
        if max_w:
            w = min(w, int(max_w))
        if max_h:
            h = min(h, int(max_h))
        return max(w, int(min_w)), max(h, int(min_h))
    if drive == "height":
        w = round(h * ratio)
    else:
        h = round(w / ratio)
    # 上限：盒子里能放下的最大同比矩形
    if max_w and w > max_w:
        w = int(max_w)
        h = round(w / ratio)
    if max_h and h > max_h:
        h = int(max_h)
        w = round(h * ratio)
    # 下限：两边都不能小于最小值，按更紧的那一边放大
    if w < min_w or h < min_h:
        w = max(int(min_w), round(int(min_h) * ratio))
        h = round(w / ratio)
        if h < min_h:
            h = int(min_h)
            w = round(h * ratio)
    return int(w), int(h)


def constrain_sizing_rect(edge: int, left: int, top: int, right: int, bottom: int,
                          ratio: float, min_w: int = 0, min_h: int = 0) -> tuple[int, int, int, int]:
    """WM_SIZING：用户正拖着 edge 这条边/角，把提议的矩形改成保比例的。

    拖左右边 → 宽定高，动底边；拖上下边 → 高定宽，动右边；拖角 → 宽定高，
    动的是用户没抓着的那一条水平边，手感上跟着鼠标走的那条边始终贴着光标。
    纯整数运算，不依赖 Qt，方便单测。
    """
    w, h = right - left, bottom - top
    if edge in (_WMSZ_TOP, _WMSZ_BOTTOM):
        w, h = fit_aspect(w, h, ratio, min_w=min_w, min_h=min_h, drive="height")
    else:
        w, h = fit_aspect(w, h, ratio, min_w=min_w, min_h=min_h, drive="width")
    if edge in (_WMSZ_LEFT, _WMSZ_TOPLEFT, _WMSZ_BOTTOMLEFT):
        left = right - w
    else:
        right = left + w
    if edge in (_WMSZ_TOP, _WMSZ_TOPLEFT, _WMSZ_TOPRIGHT):
        top = bottom - h
    else:
        bottom = top + h
    return left, top, right, bottom


def default_window_size() -> tuple[int, int]:
    """首次启动的窗口大小。

    按比例档位取出厂尺寸（4:3 → 960x720，16:9 → 1072x603，自由 → 1040x650），
    大约占桌面六成，旁边还摆得下别的窗口——在 1080p、以及开了 125%/150% 缩放的
    笔记本上，再大就占掉大半个桌面。用户拖过的尺寸由 Qt 自己记着，这里只管第一次。

    小屏再按可用桌面收一道：可用区域的 90% 封顶，任务栏、副屏都算进去；
    封顶时仍保比例。
    """
    key = window_aspect_key()
    width, height = _ASPECT_DEFAULT_SIZE[key]
    ratio = WINDOW_ASPECTS[key]
    max_w = max_h = None
    screen = QApplication.primaryScreen()
    if screen is not None:
        avail = screen.availableGeometry()
        max_w, max_h = int(avail.width() * 0.9), int(avail.height() * 0.9)
    return fit_aspect(width, height, ratio, max_w=max_w, max_h=max_h)


def sidebar_width_from_config() -> int:
    from mclauncher.config import CONFIG
    try:
        w = int(CONFIG.get("ui_sidebar_width") or 0)
    except (TypeError, ValueError):
        w = 0
    return w if 140 <= w <= 320 else SIDE_W


def section_title(sec_key: str) -> str:
    """分区在侧栏上那颗按钮的名字。提示语要跟用户看见的字一致。"""
    spec = _NAV_SPECS.get(sec_key)
    return tr(spec[1]) if spec else sec_key


def visible_sections() -> list[str]:
    """侧栏上真点得进去的分区。被隐藏的分区等于不存在。"""
    keys = {s[1] for s in nav_items_from_config() if s[0] == "item"}
    return [sec for sec in ("download", "more") if sec in keys]


def unpin_nav_config(key: str, back_section: str | None = None,
                     index: int = -1) -> str | None:
    """取消固定并把子页写回某个分区，返回它**真正**落到的分区（None = 没做）。

    落点只能是侧栏上点得进去的分区：放回一个被隐藏的分区，这一页在界面上
    就彻底消失了——侧栏没有它，也没有任何落点能把它拖回来。老代码既不查
    这一条，也不查成员表，直接拿默认归属去写提示，于是「放回了『更多』」
    这句话经常在说谎。

    落点是算出来的、不是猜的，提示语用返回值渲染，两边不会再各说各的。
    """
    from mclauncher.config import CONFIG
    pinned = pinned_from_config()
    if key not in pinned:
        return None
    pinned.remove(key)
    if nav_style() == NAV_STYLE_GROUPED:
        groups = grouped_layout()
        for _title, keys in groups:
            if key in keys:
                keys.remove(key)
        save_grouped_layout(groups)
    else:
        CONFIG.set("ui_nav_pinned", pinned or None)
    # 固定项不属于任何分区，成员表必须在改完 pinned 之后再读
    members = section_members_from_config()
    dest = back_section if back_section in ("download", "more") else None
    if dest is None:
        # 没指定就回它现在的归属（用户在「自定义分区」里挪过的以那份为准）
        dest = next((sec for sec in ("download", "more") if key in members[sec]),
                    _default_section_for(key))
    visible = visible_sections()
    if dest not in visible:
        if visible:
            dest = visible[0]
            index = -1  # 换了个家，原来那个落点位序没有意义
        else:
            # 两个分区都藏了，再挑也没得挑：把落点这个分区放出来，
            # 否则这一页落地即失踪
            hidden = [k for k in (CONFIG.get("ui_nav_hidden") or []) if k != dest]
            CONFIG.set("ui_nav_hidden", hidden or None)
    for sec in ("download", "more"):
        if key in members[sec]:
            members[sec].remove(key)
    bucket = members[dest]
    bucket.insert(index if 0 <= index <= len(bucket) else len(bucket), key)
    CONFIG.set("ui_section_members", members)
    CONFIG.save()
    return dest


class MainWindow(FluentWindowBase):
    def __init__(self):
        # FluentWindowBase 在 super() / resize 时就会发 resizeEvent，
        # 这些属性必须先占位，否则一点开就闪退。
        self.side = None
        self.task_badge = None
        self.download_dock = None
        self._pages = {}
        self._nav_cover = None
        self._nav_fade = None
        self._dock_anim = None
        self._drop_hint = None
        self._fly_jobs = []
        self._launch_after = {}
        self._clip_seen = None
        self._quit_on_exit = False
        self._deferred_boot_reload = False
        self._built = {}          # 子页 key -> 已构造页面（懒加载缓存）
        self._by_obj = {}         # id(page) -> key（反向查找，避免比较时触发构造）
        self._data_dirty = False  # ui_changed 置位：下次导航/刷新必须真刷数据
        self._in_user_sizing = False   # WM_ENTERSIZEMOVE ~ WM_EXITSIZEMOVE 之间
        self._aspect_snapping = False  # _snap_aspect 自己 resize 时的重入护栏
        super().__init__()
        self.setWindowTitle(f"{APP_DISPLAY_NAME} v{APP_VERSION}")
        self.setAcceptDrops(True)
        self.setMicaEffectEnabled(False)
        self.setCustomBackgroundColor("#FFFFFF", "#1B1B1B")
        setThemeColor("#2E9B6B", save=False)

        # 壁纸层要比侧栏、内容区都早建：Qt 按创建顺序叠子控件，先建的在下面，
        # 之后 lower() 再钉一次，保证任何后加的控件都压在它上头。
        self._bg_layer = BackgroundLayer(self)
        self._bg_layer.hide()
        self._wall_playlist = WallpaperPlaylist()
        self._wall_timer = QTimer(self)
        self._wall_timer.timeout.connect(self.next_wallpaper)

        self.backend = BackendAPI(self)
        # 侧栏出厂默认要在建分区壳之前落定：哪些子页被固定，决定它们
        # 是长在侧栏上还是长在分区横条上，建完再改就得整个重建。
        ensure_default_nav()
        self.apply_theme()

        # ---- 分区壳（便宜，先建；子页进分区时才构造）----
        self.download_section = DownloadSection(self.backend, self)
        self.more_section = MoreSection(self.backend, self)
        # 分区也注册进反向表：_visible_key 才能从「下载/更多」下钻到
        # 分区内子页（下载悬浮球隐藏规则、快捷入口跳转都依赖它）。
        self._by_obj[id(self.download_section)] = "download"
        self._by_obj[id(self.more_section)] = "more"
        self._bind_sections()
        self._connect_section_signals()

        # ---- 首屏页面 ----
        self.launch_page = LaunchPage(self.backend, self)
        self._register_page(self.launch_page, "launch")
        self.tasks_page = TasksPage(self.backend, self)
        self._register_page(self.tasks_page, "tasks")

        self._pages = {
            "launch": self.launch_page,
            "download": self.download_section,
            "more": self.more_section,
            "tasks": self.tasks_page,
        }

        bar = PclTitleBar(self)
        self.setTitleBar(bar)
        # 挂在主窗口上的提示条：从标题栏下沿起算、对齐内容区，别压着标题栏
        install_infobar_offsets()

        self._side_items = nav_items_from_config()
        self.side = PclSideBar(self._side_items, width=sidebar_width_from_config())
        self.side.currentChanged.connect(self._on_nav)
        self.side.widthCommitted.connect(self._on_side_width)
        self.side.pinAtRequested.connect(self._pin_nav_at)
        self.side.reorderRequested.connect(self._on_sidebar_reorder)
        self.side.editLayoutRequested.connect(
            lambda: self.launch_page.canvas.set_edit_mode(True))
        self._hint_pinned_buttons()

        self.hBoxLayout.setContentsMargins(0, TITLE_H, 0, 0)
        self.hBoxLayout.addWidget(self.side)
        self.hBoxLayout.addWidget(self.stackedWidget)
        for page in self._pages.values():
            self.stackedWidget.addWidget(page)
        self.stackedWidget.setCurrentWidget(self.launch_page)
        self.side.set_current("launch", emit=False)

        self._create_task_badge()

        self._launch_after = {}
        self.download_dock = DownloadDock(self.backend, self)
        self.backend.finished.connect(self._notify_task)
        self.backend.theme_changed.connect(self.apply_theme)
        self.backend.update_staged.connect(self._on_update_staged)
        self._ui_refresh = QTimer(self)
        self._ui_refresh.setSingleShot(True)
        self._ui_refresh.setInterval(280)
        self._ui_refresh.timeout.connect(lambda: self._refresh_pages(force=True))
        self.backend.ui_changed.connect(self._on_ui_changed)
        self.backend.task_count_changed.connect(self._update_task_badge)
        self.backend.game_started.connect(self._on_game_started)
        self.backend.game_exited.connect(self._on_game_exited)
        self.stackedWidget.currentChanged.connect(lambda *_: self._place_download_dock())
        self.resize(*default_window_size())
        # 上面 apply_theme() 时 _pages 还是空的，ScrollArea 表面没刷到。
        # 页面全部就位后再刷一遍，深色启动才不会白字压浅底。
        self.apply_theme()
        QTimer.singleShot(400, self, self._boot_extras)

    # ------------------------------------------------------------------
    # 懒加载基建
    # ------------------------------------------------------------------
    def _sub_getter(self, key: str):
        return lambda: self._ensure_sub(key)

    def _bind_sections(self, built_pages: dict | None = None):
        """按 ui_section_members 组装 _sub_specs 并 bind 两个分区壳。

        built_pages 传入时（重建分区），把已构造的子页直接 add_page 进
        新壳，保持懒加载缓存不丢、不重复构造。
        """
        members = section_members_from_config()
        pinned = set(pinned_from_config())
        self._sub_specs = {}
        for sec_key in ("download", "more"):
            section = getattr(self, f"{sec_key}_section")
            for key in members[sec_key]:
                self._sub_specs[key] = (section, sub_title(key),
                                        getattr(self, _SUB_FACTORIES[key]))
                section.bind([(sub_title(key), self._sub_getter(key), key)])
        # 固定到侧栏的子页：不 bind（无横条按钮），但保留工厂与归属，
        # 点侧栏按钮时构造进默认分区的栈里直接展示
        for key in pinned:
            if key not in self._sub_specs:
                sec_key = _default_section_for(key)
                section = getattr(self, f"{sec_key}_section")
                self._sub_specs[key] = (section, sub_title(key),
                                        getattr(self, _SUB_FACTORIES[key]))
        if built_pages:
            for key, page in built_pages.items():
                spec = self._sub_specs.get(key)
                if spec is not None:
                    # 固定页只进栈、不建横条按钮（title 空）
                    spec[0].add_page(page, "" if key in pinned else spec[1])

    def _rebuild_sections(self):
        """应用分区内容自定义后重建两个分区壳（已构造子页随迁）。

        整段关掉刷新再一次性放开：中间要拆两个旧壳、装两个新壳、把已构造的
        子页一个个搬过去，每一步都让 Qt 重排重绘一遍纯属白烧——用户看到的
        只有最后那一帧。
        """
        self.setUpdatesEnabled(False)
        try:
            self._rebuild_sections_impl()
        finally:
            self.setUpdatesEnabled(True)

    def _rebuild_sections_impl(self):
        cur_key = self._visible_key()
        old = {"download": self.download_section, "more": self.more_section}
        # 记录当前停留在哪个壳上，重建后回到同一视图
        cur_widget = self.stackedWidget.currentWidget()
        cur_section_key = next((k for k, w in old.items() if w is cur_widget), None)

        self.download_section = DownloadSection(self.backend, self)
        self.more_section = MoreSection(self.backend, self)
        # 壳还是空的这一刻就刷表面：容器上每次 setStyleSheet 都会把整棵子树
        # 重新 polish，等 _bind_sections 把已构造的子页（设置页几百个控件）
        # 搬进来再刷，同一句话贵几十倍（100ms 量级）。
        # 子页自带表面且守卫键没变，搬过来后 ensure_ 直接跳过。
        ensure_theme_surfaces(self.download_section)
        ensure_theme_surfaces(self.more_section)
        for k, w in old.items():
            self._by_obj.pop(id(w), None)
        for sec_key, w in (("download", self.download_section),
                           ("more", self.more_section)):
            self._by_obj[id(w)] = sec_key
        self._bind_sections(built_pages=self._built)
        self._connect_section_signals()

        for sec_key, w in old.items():
            self.stackedWidget.removeWidget(w)
            w.deleteLater()
        self.stackedWidget.addWidget(self.download_section)
        self.stackedWidget.addWidget(self.more_section)
        self._pages["download"] = self.download_section
        self._pages["more"] = self.more_section
        self._style_new_shells()

        # 回到原来的视图：原来在分区里就回到那个分区的同一个子页
        target = None
        if cur_key in self._sub_specs and cur_key in self._built:
            target = self._built[cur_key]
        if target is not None and cur_section_key is not None:
            shell = getattr(self, f"{cur_section_key}_section")
            if shell.has_page(target):
                self.stackedWidget.setCurrentWidget(shell)
                shell.show_page(target)
                self.side.set_current(cur_section_key, emit=False)
                return
        fallback = (self.download_section if cur_section_key == "download"
                    else self.more_section if cur_section_key == "more"
                    else None)
        if fallback is not None:
            fallback.ensure_first()
            self.stackedWidget.setCurrentWidget(fallback)

    def _style_new_shells(self):
        """只把刚建好的两个分区壳刷上主题，别整套重来。

        这里不能走「清掉 _theme_sig + apply_theme()」：apply_theme 是给
        「主题真的变了」准备的，它要走一遍 qfluentwidgets 的 setTheme /
        setThemeColor（内部重算所有注册控件的样式表）、重刷每一个已构造页面
        的表面、再跑一次背景，一下就是 300ms 量级。而重建分区壳时主题、配色、
        壁纸一个都没动，真正需要上色的只有两个新壳和它们的横条。

        随迁过来的子页是同一批控件对象，样式本来就在身上；ensure_ 的守卫键
        没变，这里点到它们也是直接跳过，花不了什么。
        """
        for sec_key in ("download", "more"):
            shell = getattr(self, f"{sec_key}_section", None)
            if shell is None:
                continue
            cat = getattr(shell, "cat", None)
            if cat is not None and hasattr(cat, "restyle"):
                cat.restyle()
            ensure_theme_surfaces(shell)
            for page in shell.pages():
                ensure_theme_surfaces(page)

    def _create_task_badge(self):
        """把任务角标挂到当前侧栏的「下载任务」按钮上（侧栏重建后重挂）。"""
        target = self.side.button("tasks")
        self.task_badge = QLabel("0", target)
        self.task_badge.setObjectName("taskBadge")
        self.task_badge.setAlignment(Qt.AlignCenter)
        self.task_badge.setFixedHeight(16)
        self.task_badge.setMinimumWidth(16)
        self.task_badge.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.task_badge.setStyleSheet(
            "#taskBadge { background: #E23C3C; color: #fff; border-radius: 8px;"
            " font-size: 10px; font-weight: 700; padding: 0 4px; }"
        )
        self.task_badge.hide()

    def _connect_section_signals(self):
        # 注意不能用 UniqueConnection：该标志只对成员函数槽有效，接
        # lambda 会静默连不上（拖回分区横条没反应的根因）。每次重建
        # 分区壳都会换新对象，天然不会重复连接。
        for sec_key, shell in (("download", self.download_section),
                               ("more", self.more_section)):
            shell.cat.unpinRequested.connect(
                lambda k, i, s=sec_key: self._unpin_nav(k, s, i))

    def _on_side_width(self, width: int):
        from mclauncher.config import CONFIG
        CONFIG.set("ui_sidebar_width", int(width))
        CONFIG.save()
        self._place_task_badge()

    def _sidebar_sequence(self) -> list[str]:
        """当前侧栏可见键序列（一级 + 固定子页，按显示顺序）。"""
        return [s[1] for s in nav_items_from_config() if s[0] == "item"]

    def _write_sidebar_sequence(self, seq: list[str]):
        """落盘完整混合序列：ui_nav_order 存位置（一级键+固定子页的
        真实排列），ui_nav_pinned 只记哪些子页被固定。"""
        from mclauncher.config import CONFIG
        seen: set[str] = set()
        clean = [k for k in seq
                 if (k in _TOP_KEYS or k in _ALL_SUB_KEYS)
                 and not (k in seen or seen.add(k))]
        for k in _TOP_KEYS:
            if k not in clean:
                clean.append(k)
        pinned = [k for k in clean if k in _ALL_SUB_KEYS]
        CONFIG.set("ui_nav_order", clean)
        CONFIG.set("ui_nav_pinned", pinned or None)
        CONFIG.save()

    def _on_sidebar_reorder(self, key: str, target: str, before: bool):
        # 固定子页拖到「下载/更多」一级按钮上 = 放回那个分区（直觉手势）
        if key in _ALL_SUB_KEYS and target in ("download", "more"):
            self._unpin_nav(key, target)
            return
        if nav_style() == NAV_STYLE_GROUPED:
            # 分组档的顺序存在组里，写 ui_nav_order 不会有任何效果
            groups = grouped_layout()
            if not any(key in keys for _t, keys in groups):
                return
            if move_within_groups(groups, key, target, before):
                save_grouped_layout(groups)
                self._rebuild_sidebar()
            return
        seq = self._sidebar_sequence()
        if key not in seq or target not in seq or key == target:
            return
        seq.remove(key)
        idx = seq.index(target) + (0 if before else 1)
        seq.insert(idx, key)
        self._write_sidebar_sequence(seq)
        self._rebuild_sidebar()

    def _pin_nav_at(self, key: str, target: str | None, before: bool):
        """分区子页固定到侧栏落点（target 为空则追加在「更多」前）。"""
        if key not in self._sub_specs:
            return
        if key in pinned_from_config():
            return
        if nav_style() == NAV_STYLE_GROUPED:
            self._pin_nav_grouped(key, target, before)
            return
        if target:
            seq = self._sidebar_sequence()
            if target in seq:
                if not self._take_from_section(key):
                    return
                seq.insert(seq.index(target) + (0 if before else 1), key)
                self._write_sidebar_sequence(seq)
                self._rebuild_sections()
                self._rebuild_sidebar()
                return
        self._pin_nav(key)

    def _pin_nav_grouped(self, key: str, target: str | None, before: bool):
        """分组排法下固定：并进落点所在的那一组；没落点就插在「更多」前面。"""
        if not self._take_from_section(key):
            return
        groups = grouped_layout()
        on_target = bool(target) and any(target in keys for _t, keys in groups)
        anchor = target if on_target else "more"
        if not move_within_groups(groups, key, anchor, before if on_target else True):
            groups[-1][1].append(key)
        save_grouped_layout(groups)
        self._rebuild_sections()
        self._rebuild_sidebar()

    def _take_from_section(self, key: str) -> bool:
        """移动语义：固定前把 key 从分区成员里拿走；分区只剩它时拒绝。"""
        from mclauncher.config import CONFIG
        members = section_members_from_config()
        for sec in ("download", "more"):
            if key in members[sec]:
                if len(members[sec]) <= 1:
                    from qfluentwidgets import InfoBar, InfoBarPosition
                    InfoBar.warning(
                        tr("无法移出"),
                        tr("该分区只剩这一个子页，移走会变空栏；先在「自定义分区」里补充其它子页"),
                        parent=self, position=InfoBarPosition.TOP, duration=3500)
                    return False
                members[sec].remove(key)
                CONFIG.set("ui_section_members", members)
                CONFIG.save()
                return True
        return True  # 本就不在分区里（例如配置残留），直接放行

    def _pin_nav(self, key: str):
        """分区子页固定为顶级侧栏项（移动：原分区里不再显示）。"""
        from mclauncher.config import CONFIG
        if key not in self._sub_specs:
            return
        pinned = pinned_from_config()
        if key in pinned:
            return
        if nav_style() == NAV_STYLE_GROUPED:
            self._pin_nav_grouped(key, None, True)
            return
        if not self._take_from_section(key):
            return
        pinned.append(key)
        CONFIG.set("ui_nav_pinned", pinned)
        # 同步进混合序列（插在「更多」前），保持落点位置持久
        seq = self._sidebar_sequence()
        if "more" in seq:
            seq.insert(seq.index("more"), key)
        else:
            seq.append(key)
        CONFIG.set("ui_nav_order", [k for k in seq if k in _TOP_KEYS])
        CONFIG.save()
        self._rebuild_sections()
        self._rebuild_sidebar()

    def _unpin_nav(self, key: str, back_section: str | None = None, index: int = -1):
        """取消固定；拖回某个分区时放回那个分区（index 是横条上的落点）。"""
        landed = unpin_nav_config(key, back_section, index)
        if landed is None:
            return
        self._rebuild_sections()
        self._rebuild_sidebar()
        InfoBar.success(
            tr("已取消固定"),
            tr("「{0}」放回了「{1}」").format(sub_title(key), section_title(landed)),
            parent=self, position=InfoBarPosition.TOP, duration=2500)

    def _rebuild_sidebar(self):
        """应用侧栏自定义（排序/显隐/宽度）后重建侧栏，保留当前选中项。"""
        current = None
        old = getattr(self, "side", None)
        if old is not None:
            for key, btn in old._buttons.items():
                if btn.isChecked():
                    current = key
                    break
        badge = getattr(self, "task_badge", None)
        if badge is not None:
            badge.hide()
            badge.setParent(None)
            badge.deleteLater()
            self.task_badge = None
        if old is not None:
            self.hBoxLayout.removeWidget(old)
            old.deleteLater()
        self._side_items = nav_items_from_config()
        self.side = PclSideBar(self._side_items, width=sidebar_width_from_config())
        self.side.currentChanged.connect(self._on_nav)
        self.side.widthCommitted.connect(self._on_side_width)
        self.side.pinAtRequested.connect(self._pin_nav_at)
        self.side.reorderRequested.connect(self._on_sidebar_reorder)
        self.side.editLayoutRequested.connect(
            lambda: self.launch_page.canvas.set_edit_mode(True))
        self.hBoxLayout.insertWidget(0, self.side)
        self._create_task_badge()
        self._hint_pinned_buttons()
        # 恢复选中态；原来的键被隐藏时回落到第一个可见项
        keys = [s[1] for s in self._side_items if s[0] == "item"]
        want = current if current in keys else (keys[0] if keys else None)
        if want is not None:
            self.side.set_current(want, emit=False)
        self._place_task_badge()
        try:
            self._update_task_badge(self.backend._download_task_count())
        except Exception:
            pass

    def _hint_pinned_buttons(self):
        """固定项挂个提示：不然「怎么放回去」全靠猜。"""
        for key in pinned_from_config():
            btn = self.side.button(key)
            if btn is not None:
                btn.setToolTip(tr("拖回「下载」/「更多」即可放回原分区"))

    def _register_page(self, page, key: str):
        self._by_obj[id(page)] = key
        # 新页面入列后，apply_theme 的签名短路必须失效：
        # 否则启动时「页面建好后的第二次 apply_theme」会被同签名跳过，
        # 首屏页面表面没刷，深色启动就是白字压浅底。
        self._theme_sig = None

    def _finish_page_build(self, page):
        """晚于 apply_theme 构造的页面：补一次表面刷新 + 一次性样式。"""
        try:
            ensure_theme_surfaces(page)
        except Exception:
            pass
        restyle = getattr(page, "restyle", None)
        if callable(restyle):
            try:
                restyle()
            except Exception:
                pass

    def _ensure_sub(self, key: str):
        page = self._built.get(key)
        if page is not None:
            return page
        section, title, factory = self._sub_specs[key]
        # 直接建在分区栈底下：add_page 只入布局、不再换父重新 polish 整页
        page = factory(getattr(section, "stack", None))
        self._built[key] = page
        self._register_page(page, key)
        # 固定到侧栏的子页只进分区栈展示，不建横条按钮（移动语义）
        pinned = set(pinned_from_config())
        section.add_page(page, "" if key in pinned else title)
        self._finish_page_build(page)
        return page

    def _ensure_top(self, key: str):
        page = self._pages.get(key)
        if page is not None:
            return page
        if key == "ai":
            page = self._make_ai_page(self.stackedWidget)
        else:
            return None
        self._pages[key] = page
        self._register_page(page, key)
        self.stackedWidget.addWidget(page)
        self._finish_page_build(page)
        return page

    # ---- 子页工厂（import 放在工厂里：未访问的页面连模块都不加载）----
    # parent 传「它最终要进的那个栈」：页面若先挂在主窗、再被 addWidget 搬进
    # 栈，Qt 会因为换了祖先把整棵页面树重新 polish 一遍（设置页 ~90ms）。
    # 一开始就建在栈底下，addWidget 只是入布局、不换父，这一遍就省了。
    def _make_version_page(self, parent=None):
        from .pages.version_page import VersionPage
        return VersionPage(self.backend, parent or self)

    def _make_mod_page(self, parent=None):
        from .pages.catalog_page import ModPage
        return ModPage(self.backend, parent or self)

    def _make_modpack_page(self, parent=None):
        from .pages.catalog_page import ModpackPage
        return ModpackPage(self.backend, parent or self)

    def _make_datapack_page(self, parent=None):
        from .pages.catalog_page import DatapackPage
        return DatapackPage(self.backend, parent or self)

    def _make_resource_page(self, parent=None):
        from .pages.catalog_page import ResourcePackPage
        return ResourcePackPage(self.backend, parent or self)

    def _make_shader_page(self, parent=None):
        from .pages.catalog_page import ShaderPage
        return ShaderPage(self.backend, parent or self)

    def _make_world_page(self, parent=None):
        from .pages.catalog_page import WorldPage
        return WorldPage(self.backend, parent or self)

    def _make_java_page(self, parent=None):
        from .pages.java_page import JavaPage
        return JavaPage(self.backend, parent or self)

    def _make_instance_page(self, parent=None):
        from .pages.version_manage_page import VersionManagePage
        return VersionManagePage(self.backend, parent or self)

    def _make_mods_page(self, parent=None):
        from .pages.mod_page import ModManagerPage
        return ModManagerPage(self.backend, parent or self)

    def _make_account_page(self, parent=None):
        from .pages.account_page import AccountPage
        return AccountPage(self.backend, parent or self)

    def _make_multiplayer_page(self, parent=None):
        from .pages.multiplayer_page import MultiplayerPage
        return MultiplayerPage(self.backend, parent or self)

    def _make_servers_page(self, parent=None):
        from .pages.servers_page import ServerPage
        return ServerPage(self.backend, parent or self)

    def _make_playtime_page(self, parent=None):
        from .pages.playtime_page import PlaytimePage
        return PlaytimePage(self.backend, parent or self)

    def _make_feedback_page(self, parent=None):
        from .pages.feedback_page import FeedbackPage
        return FeedbackPage(self.backend, parent or self)

    def _make_settings_page(self, parent=None):
        from .pages.settings_page import SettingsPage
        return SettingsPage(self.backend, parent or self)

    def _make_ai_page(self, parent=None):
        from .pages.ai_page import AiPage
        return AiPage(self.backend, parent or self)

    # ---- 懒加载属性：只在确实要用时才构造 ----
    @property
    def version_page(self):
        return self._ensure_sub("version")

    @property
    def mod_page(self):
        return self._ensure_sub("mod")

    @property
    def modpack_page(self):
        return self._ensure_sub("modpack")

    @property
    def datapack_page(self):
        return self._ensure_sub("datapack")

    @property
    def resource_page(self):
        return self._ensure_sub("resource")

    @property
    def shader_page(self):
        return self._ensure_sub("shader")

    @property
    def world_page(self):
        return self._ensure_sub("world")

    @property
    def java_page(self):
        return self._ensure_sub("java")

    @property
    def instance_page(self):
        return self._ensure_sub("instance")

    @property
    def mods_page(self):
        return self._ensure_sub("mods")

    @property
    def account_page(self):
        return self._ensure_sub("account")

    @property
    def multiplayer_page(self):
        return self._ensure_sub("multiplayer")

    @property
    def servers_page(self):
        return self._ensure_sub("servers")

    @property
    def playtime_page(self):
        return self._ensure_sub("playtime")

    @property
    def feedback_page(self):
        return self._ensure_sub("feedback")

    @property
    def settings_page(self):
        return self._ensure_sub("settings")

    @property
    def ai_page(self):
        return self._ensure_top("ai")

    def apply_theme(self):
        color = self.backend.get_setting("theme_color", "#2E9B6B") or "#2E9B6B"
        dark = bool(self.backend.get_setting("ui_dark", False))
        image = str(self.backend.get_setting("ui_background", "") or "").strip()
        # get_settings 那头已经夹过范围，这里拿到的一定是合法值
        opacity = int(self.backend.get_setting("ui_sidebar_opacity", 100) or 100)
        blur = int(self.backend.get_setting("ui_background_blur", 0) or 0)
        dim = int(self.backend.get_setting("ui_background_dim", 0) or 0)
        rotate = (str(self.backend.get_setting("ui_background_folder", "") or ""),
                  bool(self.backend.get_setting("ui_background_shuffle", False)),
                  int(self.backend.get_setting("ui_background_interval", 10) or 10))
        # 签名短路：主题相关几个键没变就直接返回。设置保存、探针、双保险
        # 路径都会重复触发 apply_theme，全量跑一次要重刷所有已构造页面。
        # 新页面注册时会清掉签名（见 _register_page），不会漏刷首屏。
        sig = (dark, str(color), image, opacity, blur, dim, rotate)
        if getattr(self, "_theme_sig", None) == sig:
            return
        self._theme_sig = sig
        Theme.sidebar_opacity = opacity
        self.setUpdatesEnabled(False)
        try:
            self._apply_theme_impl(color, dark)
        finally:
            self.setUpdatesEnabled(True)

    def _apply_theme_impl(self, color, dark):
        Theme.apply(dark)
        # lazy=True：qfluentwidgets 只重刷当前可见控件，隐藏页打 dirty-qss
        # 标记、下一次 Paint 时由 DirtyStyleSheetWatcher 补刷。全量重刷是
        # 主题翻转卡 3 秒多的元凶——页面建得越多越惨。
        setThemeColor(color, save=False, lazy=True)
        setTheme(FluentTheme.DARK if dark else FluentTheme.LIGHT, save=False, lazy=True)
        # 必须固定传「浅色槽 / 深色槽」两套值。若拿 Theme.bg 当浅色槽，
        # 一切深色 Theme.bg 已是 #1B1B1B，会把浅色槽也污染成深色，切回浅色时
        # Fluent 背景动画/缓存会短暂甚至一直停在脏值上。
        self.setCustomBackgroundColor("#FFFFFF", "#1B1B1B")
        if hasattr(self, "_updateBackgroundColor"):
            try:
                self._updateBackgroundColor()
            except Exception:
                pass
        bar = self.titleBar
        if hasattr(bar, "restyle"):
            bar.restyle()
        side = getattr(self, "side", None)
        if side is not None and hasattr(side, "restyle"):
            side.restyle()
        for key in ("download_section", "more_section"):
            cat = getattr(getattr(self, key, None), "cat", None)
            if cat is not None and hasattr(cat, "restyle"):
                cat.restyle()
        # 只立即重刷当前可见页；其余已构造页面打「主题待刷」标记，
        # 导航进入时再补。主题翻转最贵的不是改样式，而是每次
        # setStyleSheet 后 Qt 的样式重算+重排——给几十个看不见的
        # 页面全做一遍纯属浪费（一次翻转 3 秒多就是这么来的）。
        visible = self._visible_key()
        for page in list(self._pages.values()) + list(self._built.values()):
            if page is None:
                continue
            key = self._by_obj.get(id(page))
            if (page is not self.download_section and page is not self.more_section
                    and key is not None and key != visible):
                page._pymcl_theme_stale = True
                continue
            if hasattr(page, "restyle"):
                try:
                    page.restyle()
                except Exception:
                    pass
        self._apply_background()
        self._paint_page_surfaces()
        if getattr(self, "_pages", None):
            page = self.stackedWidget.currentWidget()
            if page is not None:
                if self.isVisible():
                    self._reload_page(page, force=True)
                elif not self._deferred_boot_reload:
                    # 首帧前的两次 apply_theme 都会走到这里；同步 reload 会在
                    # show() 前扫盘（实例/账号/版本），合并成事件循环空转后的
                    # 一次，首帧先出壳。singleShot(0) 在 exec() 后才触发，
                    # 那时 show() 已发生。
                    self._deferred_boot_reload = True
                    QTimer.singleShot(0, self, self._boot_reload)
        self.update()

    def _boot_reload(self):
        self._deferred_boot_reload = False
        page = self.stackedWidget.currentWidget() if getattr(self, "_pages", None) else None
        if page is not None:
            self._reload_page(page, force=True)

    def _refresh_if_stale(self, page):
        """主题翻转时被延迟重刷的页面，进入视野前补刷。"""
        if page is None or not getattr(page, "_pymcl_theme_stale", False):
            return
        try:
            page._pymcl_theme_stale = False
            ensure_theme_surfaces(page)
            restyle = getattr(page, "restyle", None)
            if callable(restyle):
                restyle()
        except Exception:
            pass

    def _paint_page_surfaces(self):
        """刷页面 + ScrollArea/viewport/宿主底色，并修正 QFormLayout 系统标签。

        Fluent 卡片深色是半透明白，必须压在 Theme.bg 上；只刷 page 本身不够，
        设置/实例里的 ScrollArea 仍是浅灰时就会白字压浅底。
        ensure_ 带主题版本守卫：Theme.apply 自增 _version，切主题必真刷；
        导航路径重复调用时同键直接跳过，省掉 4 轮 findChildren 全树遍历。
        隐藏页面在这里只打待刷标记（见 _apply_theme_impl）。
        """
        visible = self._visible_key()
        for page in list(self._pages.values()) + list(self._built.values()):
            if page is None:
                continue
            key = self._by_obj.get(id(page))
            if (page is not self.download_section and page is not self.more_section
                    and key is not None and key != visible):
                page._pymcl_theme_stale = True
                continue
            ensure_theme_surfaces(page)
        dock = getattr(self, "download_dock", None)
        if dock is not None:
            ensure_theme_surfaces(dock)
            if hasattr(dock, "restyle"):
                try:
                    dock.restyle()
                except Exception:
                    pass

    def _wallpaper_source(self) -> str:
        """这一刻该显示哪张壁纸：文件夹轮播优先，没有才用单张设置。"""
        folder = str(self.backend.get_setting("ui_background_folder", "") or "").strip()
        shuffle = bool(self.backend.get_setting("ui_background_shuffle", False))
        rotating = self._wall_playlist.set_folder(folder, shuffle)
        minutes = int(self.backend.get_setting("ui_background_interval", 10) or 10)
        if rotating:
            self._wall_timer.start(max(1, minutes) * 60_000)
            return self._wall_playlist.current()
        self._wall_timer.stop()
        return str(self.backend.get_setting("ui_background", "") or "").strip()

    def next_wallpaper(self):
        """轮播到下一张。只换图源，不走 apply_theme——那会把所有页面重刷一遍。"""
        nxt = self._wall_playlist.advance()
        if not nxt:
            # 文件夹被删空/移走了：回落到单张设置，这一步要整套重刷
            self._theme_sig = None
            self.apply_theme()
            return
        self._bg_layer.set_source(nxt)
        self._sync_background_playback()

    def _apply_background(self):
        """把当前壁纸（静态图 / mp4 / 文件夹轮播）交给底层画布。

        文件被用户删掉、改名后要静默回落纯色：靠 QSS border-image 指着一个
        不存在的文件只会画成一片空白，界面看起来像坏了。

        画布铺满整窗还不够：页面作为子控件铺着不透明 Theme.bg，永远盖在下层
        兄弟之上。所以这里同时裁决 Theme.background_active，
        paint_theme_surfaces 按它把页面表面刷透明，壁纸才真正透得出来。
        """
        image = self._wallpaper_source()
        active = bool(image) and os.path.isfile(image)
        Theme.background_active = active
        layer = getattr(self, "_bg_layer", None)
        if layer is not None:
            layer.set_source(image if active else "")
            layer.set_effects(
                int(self.backend.get_setting("ui_background_blur", 0) or 0),
                int(self.backend.get_setting("ui_background_dim", 0) or 0),
                Theme.bg)
            if active:
                layer.setGeometry(self.rect())
                layer.lower()
                layer.show()
                self._sync_background_playback()
            else:
                layer.hide()
        # stacked 的透明**不能**靠自己 setStyleSheet 抢：qfluentwidgets 的
        # DirtyStyleSheetWatcher 会在下一次绘制时把整份 Fluent 样式表刷回来，
        # 其中 `StackedWidget { background-color: rgba(255,255,255,0.5) }` 会给
        # 壁纸蒙一层 50% 白。它自己留了 `StackedWidget[isTransparent=true]`
        # 这条出口，翻这个属性才是刷回来也不丢的做法。
        stack = self.stackedWidget
        if bool(stack.property("isTransparent")) != active:
            stack.setProperty("isTransparent", active)
            stack.setStyle(QApplication.style())
        if active:
            # 自带的样式表必须清掉，否则控件自身那条规则压过属性选择器
            stack.setStyleSheet("")
        else:
            # 纯色时显式铺 Theme.bg：否则 stacked 透明，下面页又是浅色默认底
            stack.setStyleSheet(
                f"QStackedWidget {{ background-color: {Theme.bg}; border: none; }}")

    def _sync_background_playback(self):
        """只有窗口真的摆在用户眼前才播动态壁纸：失焦、最小化、隐藏一律暂停。"""
        layer = getattr(self, "_bg_layer", None)
        if layer is None:
            return
        layer.set_playing(
            self.isVisible() and not self.isMinimized() and self.isActiveWindow())

    def _boot_extras(self):
        if self.backend.get_setting("first_run", True):
            from .pages.first_run import FirstRunDialog
            dlg = FirstRunDialog(self.backend, self)
            if dlg.exec():
                dlg.apply()
            else:
                data = self.backend.get_settings()
                data["first_run"] = False
                self.backend.save_settings(data)
        self._ask_feedback_consent()
        if not self.backend.get_setting("auto_check_update", True):
            return

        def ok(info):
            info = info or {}
            if info.get("has_update"):
                InfoBar.info(tr("发现更新"), info.get("message") or tr("到设置里安装"), parent=self,
                             position=InfoBarPosition.TOP_RIGHT, duration=5000)

        self.backend.call_async(self.backend.check_update, ok, lambda *_: None)

    def _on_update_staged(self, _path):
        """替换脚本已在等我们退出：给用户看一眼提示，然后真的退出。"""
        InfoBar.success(tr("更新就绪"), tr("启动器即将关闭并换成新版本"), parent=self,
                        position=InfoBarPosition.TOP_RIGHT, duration=2500)
        QTimer.singleShot(1500, QApplication.instance().quit)

    def _on_game_started(self):
        mode = self.backend.get_setting("launcher_visibility") or "keep"
        if mode == "close":
            self._quit_on_exit = True
            self.hide()
        elif mode in ("hide", "hide_reopen"):
            self.hide()
        elif mode == "minimize":
            self.showMinimized()

    def _on_game_exited(self, _code):
        if self._quit_on_exit:
            self._quit_on_exit = False
            QApplication.instance().quit()
            return
        mode = self.backend.get_setting("launcher_visibility") or "keep"
        if mode == "hide_reopen":
            self.show()
            self.raise_()
            self.activateWindow()

    def _ask_feedback_consent(self):
        from mclauncher import feedback as fb
        from .widgets import prompt_feedback_consent
        if not fb.consent_asked():
            prompt_feedback_consent(self)
            return
        if fb.has_consent():
            fb.start_heartbeat()

    def _on_ui_changed(self):
        self._data_dirty = True
        self._ui_refresh.start()

    def _on_nav(self, key: str):
        if key in self._sub_specs:
            # 固定到侧栏的分区子页：进分区展示，选中态留在固定按钮上
            self.switchTo(key)
            self.side.set_current(key, emit=False)
            return
        page = self._pages.get(key)
        if page is None:
            page = self._ensure_top(key)
        if page is None:
            return
        if hasattr(page, "ensure_first"):
            page.ensure_first()
        # 主题翻转时被延迟的页面，切过来之前补刷，首帧就是正确配色
        self._refresh_if_stale(page)
        if hasattr(page, "current_page"):
            self._refresh_if_stale(page.current_page())
        fade_stack_to(self.stackedWidget, page, self)
        ensure_theme_surfaces(page)
        self._reload_page(page)

    def _visible_key(self):
        """当前显示页的 key；落在下载/更多分区时下钻到分区内子页。"""
        page = self.stackedWidget.currentWidget()
        if page is None:
            return None
        key = self._by_obj.get(id(page))
        if key in ("download", "more") and hasattr(page, "current_page"):
            inner = page.current_page()
            if inner is not None and inner is not page:
                key = self._by_obj.get(id(inner)) or key
        return key

    def switchTo(self, interface):
        if isinstance(interface, str):
            interface = (self._ensure_top(interface) if interface in _TOP_KEYS
                         else self._ensure_sub(interface))
            if interface is None:
                return
        for key, sec in (("download", self.download_section), ("more", self.more_section)):
            if sec.has_page(interface) and interface is not sec:
                fade_stack_to(self.stackedWidget, sec, self)
                self.side.set_current(key, emit=False)
                sec.show_page(interface)
                return
        fade_stack_to(self.stackedWidget, interface, self)
        for key, page in self._pages.items():
            if page is interface:
                self.side.set_current(key, emit=False)
                self._reload_page(page)
                return

    def _reload_page(self, page, force: bool = False):
        if page is None:
            return
        self._refresh_if_stale(page)
        # 同一页面 1.2 秒内的重复 reload 直接跳过（导航来回点、分区壳
        # 二次触发都会撞上）；数据真变了走 force 或 _data_dirty。
        now = time.monotonic()
        if not force and not self._data_dirty \
                and (now - getattr(page, "_pymcl_last_reload", 0.0)) < 1.2:
            return
        try:
            page._pymcl_last_reload = now
        except Exception:
            pass
        if page is self.download_section or page is self.more_section:
            inner = page.current_page()
            if inner is not None and inner is not page:
                self._reload_page(inner, force)
            return
        key = self._by_obj.get(id(page))
        if key == "version":
            if getattr(page, "_all_versions", None):
                page.reload_installed_only()
            else:
                page.reload()
            return
        if key == "java":
            page.reload(scan_system=False)
            return
        if hasattr(page, "reload_installed"):
            page.reload_installed()
            return
        if hasattr(page, "reload"):
            try:
                page.reload()
            except TypeError:
                pass

    def _update_task_badge(self, count: int):
        if count <= 0:
            self.task_badge.hide()
            return
        prev = int(self.task_badge.property("count") or 0)
        self.task_badge.setText("99+" if count > 99 else str(count))
        self.task_badge.adjustSize()
        self.task_badge.setFixedHeight(16)
        self.task_badge.show()
        self.task_badge.setProperty("count", int(count))
        self._place_task_badge()
        if count > prev:
            from .motion import pop
            pop(self.task_badge)

    def _place_task_badge(self):
        side = getattr(self, "side", None)
        badge = getattr(self, "task_badge", None)
        if side is None or badge is None or badge.isHidden():
            return
        btn = side.button("tasks")
        if btn is None:
            return
        icon_w = btn.iconSize().width() if not btn.icon().isNull() else 16
        pad, gap = 14, 6
        text_w = btn.fontMetrics().horizontalAdvance(btn.text())
        x = pad + icon_w + gap + text_w + 6
        y = (btn.height() - badge.height()) // 2
        x = min(x, btn.width() - badge.width() - 8)
        x = max(pad + icon_w, x)
        badge.move(x, y)
        badge.raise_()

    def _place_download_dock(self, animate=True):
        dock = getattr(self, "download_dock", None)
        if not dock:
            return
        hide_on = {"settings", "instance", "tasks", "feedback"}
        want = bool(getattr(dock, "_active", None)) and self._visible_key() not in hide_on
        g = self.stackedWidget.geometry()
        dock.adjustSize()
        w = min(640, max(420, g.width() - 40))
        h = dock.sizeHint().height()
        x = g.x() + (g.width() - w) // 2
        y = g.y() + g.height() - h - 18
        dest = QPoint(max(g.x() + 12, x), max(g.y() + 12, y))
        dock.setFixedWidth(w)
        prev = getattr(self, "_dock_anim", None)
        if prev is not None:
            prev.stop()
            self._dock_anim = None
        if want:
            if not dock.isVisible():
                dock.move(dest.x(), dest.y() + 28)
                dock.show()
                dock.raise_()
                if animate:
                    self._dock_anim = self._anim_pos(dock, dest, 280)
                else:
                    dock.move(dest)
            else:
                dock.move(dest)
                dock.raise_()
            return
        if not dock.isVisible():
            return
        if not animate:
            dock.hide()
            return

        def after():
            dock.hide()
            self._dock_anim = None

        self._dock_anim = self._anim_pos(dock, QPoint(dest.x(), dest.y() + 24), 200, after)

    def _anim_pos(self, widget, end, ms, done=None):
        anim = QPropertyAnimation(widget, b"pos", self)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setStartValue(widget.pos())
        anim.setEndValue(end)
        if done:
            anim.finished.connect(done)
        anim.start()
        return anim

    # ------------------------------------------------------------------
    # 拖进窗口的整合包
    # ------------------------------------------------------------------
    @staticmethod
    def _dropped_paths(mime) -> list[str]:
        if not mime.hasUrls():
            return []
        return [p for p in (u.toLocalFile() for u in mime.urls() if u.isLocalFile()) if p]

    def _unpin_drag_key(self, mime) -> str:
        """落在窗口其它地方的「把固定项拖回去」；不是这种拖拽就返回空串。

        分区页自己已经收了这种拖拽，这里兜的是启动页 / AI / 下载任务这些
        非分区页面——松手在哪都能放回去，比只认那条 48px 横条好找得多。
        """
        from .pages.download_hub import unpinnable_key_of
        return unpinnable_key_of(mime)

    def dragEnterEvent(self, event):
        # 整合包页自己也收拖放，落在它上面的事件不会冒到这里来
        if self._unpin_drag_key(event.mimeData()):
            event.acceptProposedAction()
            return
        if not self._dropped_paths(event.mimeData()):
            return
        self._show_drop_hint()
        event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if (self._unpin_drag_key(event.mimeData())
                or self._dropped_paths(event.mimeData())):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._hide_drop_hint()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._hide_drop_hint()
        key = self._unpin_drag_key(event.mimeData())
        if key:
            event.acceptProposedAction()
            # 重建侧栏会删掉拖拽源那个按钮，等这一帧的拖放收完再动
            QTimer.singleShot(0, self, lambda k=key: self._unpin_nav(k))
            return
        paths = self._dropped_paths(event.mimeData())
        if not paths:
            return
        event.acceptProposedAction()
        # 延后一拍再动手：拖放这一帧里开模态窗会把拖源那边卡住
        QTimer.singleShot(0, self, lambda p=list(paths): self.take_dropped_files(p))

    def take_dropped_files(self, paths: list[str]):
        """认一认这些文件是什么，再决定放哪儿（整合包 / 模组 / 壁纸 / 皮肤…）。"""
        from .pages.file_drop import handle_dropped_files
        handle_dropped_files(self, paths)

    def _show_drop_hint(self):
        hint = self._drop_hint
        if hint is None:
            hint = QLabel(self)
            hint.setAlignment(Qt.AlignCenter)
            hint.setAttribute(Qt.WA_TransparentForMouseEvents)
            self._drop_hint = hint
        hint.setText(tr("松手放进来 · 整合包、模组、资源包、存档、壁纸、皮肤都认"))
        veil = "rgba(0, 0, 0, 150)" if Theme.dark else "rgba(255, 255, 255, 200)"
        hint.setStyleSheet(
            f"QLabel {{ color: {Theme.title}; font-size: 16px; font-weight: 600;"
            f" border: 2px dashed {Theme.green}; border-radius: 12px;"
            f" background-color: {veil}; }}"
        )
        hint.setGeometry(self.stackedWidget.geometry().adjusted(14, 14, -14, -14))
        hint.show()
        hint.raise_()

    def _hide_drop_hint(self):
        if self._drop_hint is not None:
            self._drop_hint.hide()

    def import_modpack_file(self, path: str):
        """认包 → 确认 → 跳版本管理建新版本。整合包页的拖放与导入按钮也走这条。"""
        from .pages.modpack_drop import ModpackDropDialog, probe
        info = probe(path)
        if info is None:
            InfoBar.warning(
                tr("这不是整合包"),
                f'{os.path.basename(str(path).rstrip("/\\")) or path} — '
                + tr("支持 Modrinth .mrpack、CurseForge .zip、直接压缩的 .minecraft 目录，"
                     "以及它们解开后的文件夹"),
                parent=self, position=InfoBarPosition.TOP_RIGHT, duration=5000)
            return
        dlg = ModpackDropDialog(info, self)
        if not dlg.exec():
            return
        self.switchTo(_MODPACK_LANDING_KEY)
        self.backend.install_modpack(info["path"], tr("本地"), extra={
            "instance": "", "path": info["path"], "source": tr("本地"),
            "version_name": dlg.version_name(), "isolate": dlg.isolate(),
        })
        InfoBar.success(
            tr("开始导入整合包"), tr("装完会多出一个新版本，进度看「下载任务」"),
            parent=self, position=InfoBarPosition.TOP_RIGHT, duration=3000)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        layer = getattr(self, "_bg_layer", None)
        if layer is not None and not layer.isHidden():
            layer.setGeometry(self.rect())
        # 比例锁着、又不是用户正拖着边（那条路 WM_SIZING 已经保住了）：
        # 贴边 / Win+方向键这类系统改的尺寸，下一拍吸回去。
        if (self._aspect_lock_active() and not self._in_user_sizing
                and not self._aspect_snapping and self._aspect_off_by() > 2):
            QTimer.singleShot(0, self, self._snap_aspect)
        if getattr(self, "side", None) is None:
            return
        self._place_download_dock(animate=False)
        self._place_task_badge()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.ActivationChange, QEvent.WindowStateChange):
            self._sync_background_playback()
        if (event.type() == QEvent.WindowStateChange
                and self.isMaximized() and self._aspect_lock_active()):
            # 比例锁着就没有「铺满屏幕」这回事：最大化 = 屏幕里放得下的最大同比矩形
            QTimer.singleShot(0, self, self._unmaximize_to_aspect)

    # ------------------------------------------------------------------
    # 窗口宽高比
    # ------------------------------------------------------------------
    @staticmethod
    def _aspect_lock_active() -> bool:
        """比例锁只在真 Windows 窗口上生效：它靠 WM_SIZING / 贴边 / 最大化这些
        系统路径；离屏平台（探针、冒烟、pytest）没有用户拖拽，而且那里的
        「屏幕」只有 800x600，吸一下就把用例量的任意尺寸窗口缩没了。"""
        return (window_aspect_ratio() is not None
                and QApplication.platformName().lower() == "windows")

    def nativeEvent(self, eventType, message):
        """拖边 / 拖角时把 Windows 提议的矩形改成保比例的（WM_SIZING），
        这样拖的过程中就是同比的，不是松手才跳一下。"""
        ratio = window_aspect_ratio()
        if ratio is not None:
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.hWnd:
                if msg.message == _WM_ENTERSIZEMOVE:
                    self._in_user_sizing = True
                elif msg.message == _WM_EXITSIZEMOVE:
                    self._in_user_sizing = False
                    QTimer.singleShot(0, self, self._snap_aspect)
                elif msg.message == _WM_SIZING and msg.lParam:
                    rect = wintypes.RECT.from_address(msg.lParam)
                    dpr = self.devicePixelRatioF() or 1.0
                    min_w = int(self.minimumWidth() * dpr)
                    min_h = int(self.minimumHeight() * dpr)
                    l, t, r, b = constrain_sizing_rect(
                        int(msg.wParam), rect.left, rect.top, rect.right, rect.bottom,
                        ratio, min_w, min_h)
                    rect.left, rect.top, rect.right, rect.bottom = l, t, r, b
                    return True, 1
        return super().nativeEvent(eventType, message)

    def _aspect_off_by(self) -> int:
        """当前尺寸偏离锁定比例多少个像素（按高算）。"""
        ratio = window_aspect_ratio()
        if ratio is None:
            return 0
        return abs(self.height() - round(self.width() / ratio))

    def _aspect_box(self) -> tuple[int | None, int | None]:
        """所在屏幕可用区域，作为同比矩形的上限。"""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return None, None
        avail = screen.availableGeometry()
        return avail.width(), avail.height()

    def _snap_aspect(self):
        """把窗口吸到锁定比例上（以宽定高，装不下就整体缩）。"""
        ratio = window_aspect_ratio()
        if not self._aspect_lock_active() or self.isMaximized() or self.isMinimized() or self.isFullScreen():
            return
        if self._in_user_sizing or self._aspect_snapping:
            return
        max_w, max_h = self._aspect_box()
        w, h = fit_aspect(self.width(), self.height(), ratio, max_w=max_w, max_h=max_h,
                          min_w=self.minimumWidth(), min_h=self.minimumHeight())
        if (w, h) == (self.width(), self.height()):
            return
        self._aspect_snapping = True
        try:
            self.resize(w, h)
        finally:
            self._aspect_snapping = False

    def _unmaximize_to_aspect(self):
        """最大化时退回普通态，取屏幕里放得下的最大同比矩形并居中。"""
        ratio = window_aspect_ratio()
        if not self._aspect_lock_active() or not self.isMaximized():
            return
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            self.showNormal()
            return
        avail = screen.availableGeometry()
        w, h = fit_aspect(avail.width(), avail.height(), ratio,
                          max_w=avail.width(), max_h=avail.height(),
                          min_w=self.minimumWidth(), min_h=self.minimumHeight())
        x = avail.x() + (avail.width() - w) // 2
        y = avail.y() + (avail.height() - h) // 2
        self._aspect_snapping = True
        try:
            # 无边框窗口下 Qt 的 showNormal() 只改了自己的状态，系统那边
            # （GetWindowPlacement）还记着「最大化」，接着又发一次 WM_SIZE 把
            # 我们拉回去。直接走 Win32：先 SW_RESTORE 再 SetWindowPos 落到目标
            # 矩形（物理像素），Qt 顺着 WM_WINDOWPOSCHANGED 自己同步。
            import ctypes
            hwnd = int(self.winId())
            dpr = self.devicePixelRatioF() or 1.0
            user32 = ctypes.windll.user32
            user32.ShowWindow(hwnd, 9)   # SW_RESTORE
            user32.SetWindowPos(hwnd, None, int(x * dpr), int(y * dpr),
                                int(w * dpr), int(h * dpr), 0x0004 | 0x0010)  # NOZORDER | NOACTIVATE
            self.resize(w, h)
            self.move(x, y)
        finally:
            self._aspect_snapping = False

    def apply_window_aspect(self):
        """设置里切了比例档位：锁死的档位立刻把窗口吸过去；自由档不动。"""
        if window_aspect_ratio() is None:
            return
        if self.isMaximized():
            self._unmaximize_to_aspect()
        else:
            self._snap_aspect()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_background_playback()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._sync_background_playback()

    def closeEvent(self, event):
        ai_page = getattr(self, "_pages", {}).get("ai") or getattr(self, "ai_page", None)
        if ai_page is not None:
            abandon = getattr(ai_page, "_abandon_run", None)
            if callable(abandon):
                try:
                    abandon()
                except Exception:
                    pass
        layer = getattr(self, "_bg_layer", None)
        if layer is not None:
            try:
                layer.stop()
            except Exception:
                pass
        try:
            self.backend.terracotta_shutdown()
        except Exception:
            pass
        try:
            from mclauncher.feedback import stop_heartbeat
            stop_heartbeat(send_offline=True)
        except Exception:
            pass
        try:
            self.backend.shutdown()
        except Exception:
            pass
        super().closeEvent(event)

    def fly_to_tasks(self, source, text: str, color: str | None = None):
        if source is None:
            return
        if not self.backend.get_setting("ui_fly_animation", True):
            return
        duration = max(1, int(self.backend.get_setting("ui_fly_duration_ms", 620)))
        letter = (str(text or "").strip()[:1] or "↓").upper()
        side = getattr(self, "side", None)
        target = side.button("tasks") if side is not None else None
        if target is None:
            return
        fly_to(
            self, source, letter, color or pick_color(str(text or "")),
            target=target, duration=duration,
        )

    def queue_launch_after(self, task_id, instance: str, version: str, loader: str = tr("无")):
        if not task_id:
            return
        self._launch_after[task_id] = (instance, version, loader or tr("无"))

    def _launch_installed(self, instance: str, version: str, loader: str = tr("无")):
        last = getattr(self.backend, "_last_installed", None) or {}
        vid = last.get("version") or version
        self.switchTo(self.launch_page)
        self.launch_page.reload()
        box = self.launch_page.version_box
        ids = [box.itemText(i) for i in range(box.count())]
        pick = vid if vid in ids else next(
            (i for i in ids if vid and vid in i),
            next((i for i in ids if version and version in i and (
                loader in ("", tr("无")) or (loader or "").lower() in i.lower()
            )), ids[0] if ids else ""),
        )
        if pick:
            box.setCurrentText(pick)
        self.launch_page._on_launch()

    def _notify_task(self, task_id, success, message):
        pending = self._launch_after.pop(task_id, None)
        title = self.backend.task_title(task_id)
        if pending and success:
            instance, version, loader = pending
            InfoBar.success(tr("安装完成"), tr("正在启动游戏…"), parent=self,
                            position=InfoBarPosition.TOP_RIGHT, duration=2500)
            QTimer.singleShot(
                380, self,
                lambda i=instance, v=version, l=loader: self._launch_installed(i, v, l))
            return
        if str(title).startswith(tr("启动游戏")) or str(title).startswith(tr("微软登录")):
            return
        self._place_download_dock()
        if success:
            InfoBar.success(title, message, parent=self,
                            position=InfoBarPosition.TOP_RIGHT, duration=3000)
        elif message != tr("已取消"):
            InfoBar.error(title, message, parent=self,
                          position=InfoBarPosition.TOP_RIGHT, duration=5000)

    def _refresh_pages(self, force: bool = False):
        if force:
            self._data_dirty = False
        key = self._visible_key()
        if key is None:
            return
        page = self._pages.get(key) or self._built.get(key)
        if page is None:
            return
        if key == "launch":
            self.launch_page.reload()
            return
        if key == "mods":
            page.reload_list()
            return
        if key == "version":
            if hasattr(page, "reload_installed_only"):
                page.reload_installed_only()
            else:
                page.reload()
            return
        if key == "java":
            page.reload(scan_system=False)
            return
        if hasattr(page, "reload_installed"):
            page.reload_installed()
            return
        if hasattr(page, "reload"):
            try:
                page.reload()
            except TypeError:
                pass

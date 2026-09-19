# -*- coding: utf-8 -*-
"""PCL 风格色板：细顶栏 + 左侧主导航。深浅色运行时切换。"""

from PySide6.QtCore import (
    QEasingCurve, QEvent, QParallelAnimationGroup, QPoint, QPropertyAnimation,
    Qt, Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QStyle, QStyleOption,
    QToolButton, QVBoxLayout, QWidget, QGraphicsOpacityEffect,
)
from qframelesswindow import TitleBar


class Theme:
    """运行时色板。页面样式请读 Theme.xxx，不要缓存导入时的常量。"""

    dark = False
    green = "#2E9B6B"
    green_deep = "#1E7A52"
    bg = "#FFFFFF"
    card = "#FFFFFF"
    line = "#E6E6E6"
    text = "#2B2B2B"
    muted = "#888888"
    title = "#1B7A54"
    hover = "#F3F7F5"
    chip = "#F0F4F8"
    btn_bg = "#FFFFFF"
    row_hover = "#F3F7F5"
    row_line = "#EEF3F7"
    _version = 0  # 每次 apply 自增，方便 widget 检测主题变更
    # 背景图生效中：页面表面必须刷透明，否则不透明 Theme.bg 会把压在
    # 窗口最底层的壁纸整张盖住，背景图看起来「设置无效」。
    # 由 MainWindow._apply_background 统一裁决，paint_theme_surfaces 只读。
    background_active = False
    # 侧栏与标题栏的不透明度 0–100。壁纸铺在整窗底下，这个值调低它俩就透得出壁纸。
    # 名字跟配置键 ui_sidebar_opacity 保持一致，别只看名字以为只管侧栏。
    # 由 MainWindow.apply_theme 从配置写入，各家 restyle 只读。
    sidebar_opacity = 100

    @classmethod
    def apply(cls, dark: bool):
        dark = bool(dark)
        # 只在深浅真正翻转时才自增 _version：ensure_theme_surfaces 的守卫
        # 靠它判断「表面要不要重刷」。若每次 apply 都 +1，主窗口里
        # apply_theme 一被重复调用（设置保存、探针、双重保险路径）就会把
        # 所有已构造页面整树重刷一遍，21 个页面一次好几秒。
        changed = dark != cls.dark
        cls.dark = dark
        if cls.dark:
            cls.bg = "#1B1B1B"
            cls.card = "#242424"
            cls.line = "#3A3A3A"
            cls.text = "#E8E8E8"
            cls.muted = "#9A9A9A"
            cls.title = "#6FCF9A"
            cls.hover = "#2A332F"
            cls.chip = "#333333"
            cls.btn_bg = "#2C2C2C"
            cls.row_hover = "#2A332F"
            cls.row_line = "#333333"
        else:
            cls.bg = "#FFFFFF"
            cls.card = "#FFFFFF"
            cls.line = "#E6E6E6"
            cls.text = "#2B2B2B"
            cls.muted = "#888888"
            cls.title = "#1B7A54"
            cls.hover = "#F3F7F5"
            cls.chip = "#F0F4F8"
            cls.btn_bg = "#FFFFFF"
            cls.row_hover = "#F3F7F5"
            cls.row_line = "#EEF3F7"
        if changed:
            cls._version += 1
        _sync_aliases()


def _sync_aliases():
    global PCL_BG, PCL_CARD, PCL_LINE, PCL_TEXT, PCL_MUTED, PCL_TITLE, PCL_HOVER
    PCL_BG = Theme.bg
    PCL_CARD = Theme.card
    PCL_LINE = Theme.line
    PCL_TEXT = Theme.text
    PCL_MUTED = Theme.muted
    PCL_TITLE = Theme.title
    PCL_HOVER = Theme.hover


PCL_GREEN = "#2E9B6B"
PCL_GREEN_DEEP = "#1E7A52"
PCL_BLUE = PCL_GREEN
PCL_BLUE_DEEP = PCL_GREEN_DEEP
PCL_BG = Theme.bg
PCL_CARD = Theme.card
PCL_LINE = Theme.line
PCL_TEXT = Theme.text
PCL_MUTED = Theme.muted
PCL_TITLE = Theme.title
PCL_HOVER = Theme.hover
TITLE_H = 40
SIDE_W = 188


def install_infobar_offsets() -> None:
    """窗口级的顶部提示条从标题栏下沿起算，横向对齐内容区，不再压着标题栏。

    InfoBar 挂在主窗口上（parent=window）时，qfluentwidgets 按整窗算位置：
    y=24 正压在 40 高的标题栏上，x 按整窗居中、骑在侧栏和内容区的交界上，
    滑入动画又从更高处起步。页面自己挂的提示条（parent=页面）本来就落在
    标题栏下面 24px，这里把窗口级的挪到同一条线上，两种来源看着是一个位置。
    只改「顶层窗口且带 titleBar」的情况，对话框、页面级提示条照旧。
    """
    from qfluentwidgets.components.widgets import info_bar as _ib

    def _shift(manager_cls, align: str):
        if getattr(manager_cls, "_pymcl_shifted", False):
            return
        orig = manager_cls._pos

        def _pos(self, infoBar, parentSize=None, _orig=orig, _align=align):
            pos = _orig(self, infoBar, parentSize)
            p = infoBar.parent()
            try:
                if p is None or not p.isWindow():
                    return pos
                bar = getattr(p, "titleBar", None)
                if bar is None:
                    return pos
                pos.setY(pos.y() + bar.height())
                side = getattr(p, "side", None)
                if side is None or not side.isVisible():
                    return pos
                width = parentSize.width() if parentSize is not None else p.width()
                sw = side.width()
                if _align == "center":
                    pos.setX(sw + max(0, (width - sw - infoBar.width()) // 2))
                elif _align == "left":
                    pos.setX(sw + self.margin)
            except RuntimeError:
                pass
            return pos

        manager_cls._pos = _pos
        manager_cls._pymcl_shifted = True

    _shift(_ib.TopInfoBarManager, "center")
    _shift(_ib.TopLeftInfoBarManager, "left")
    _shift(_ib.TopRightInfoBarManager, "right")


def rgba(color: str, opacity: int) -> str:
    """`#RRGGBB` + 0–100 不透明度 → QSS 的 `rgba(...)`；满值时原样返回。

    满值走原样是有意的：QSS 里 `rgba(r,g,b,1.0)` 和 `#RRGGBB` 画出来一样，
    但前者会让 Qt 把控件判成非不透明，白白多走一遍「先画父控件和下层兄弟」。
    """
    pct = max(0, min(100, int(opacity)))
    if pct >= 100:
        return color
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {pct / 100:.3f})"


def mark_opaque(widget, opaque: bool) -> None:
    """告诉 Qt「这块矩形被我自己填满了」（或者不再是）。

    上面那句「满值原样返回就不会被判成非不透明」只对了一半：QSS 画的背景
    根本不参与 Qt 的 isOpaque 判定，只有调色板填充和这个属性算数。于是壁纸
    一开，窗口每次重绘都要把整棵树自下而上重新合成——实测 90 帧要走 6100 次
    paint，不开壁纸只要 1700 次，光侧栏那 9 颗导航按钮就占 810 次（每颗都要
    现渲一遍 SVG 图标）。

    不透明度满 100 的侧栏与标题栏本来就是实底，标上之后 Qt 会把这两块从上层
    重绘区里减掉，它们和它们的子控件都不用再跟着壁纸重画。

    只在「整块矩形都被实色填满」时才标：有圆角、或者用户把不透明度调下去了，
    标了就会留下一片没人画的脏像素。
    """
    if widget is None:
        return
    try:
        if widget.testAttribute(Qt.WA_OpaquePaintEvent) != bool(opaque):
            widget.setAttribute(Qt.WA_OpaquePaintEvent, bool(opaque))
            widget.update()
    except RuntimeError:
        pass


def paint_opaque_styled_background(widget) -> None:
    """被 mark_opaque 标成不透明的控件，在 paintEvent 开头自己把样式表底补上。

    Qt 只给「没标 WA_OpaquePaintEvent」的控件走 paintBackground——样式表里的
    background / border 就是在那一步（PE_Widget）画的。标上之后这一笔被整段
    跳过，控件那块矩形从此没人清底：浅色主题下恰好是白底盖白底看不出来，
    深色主题一开，侧栏和标题栏就成了两块白板，字是深色主题的浅灰、底却还是
    白的；从顶上滑进来的 InfoBar 也会在标题栏留下一串没人擦的残影。
    这里把 Qt 跳掉的那一笔按原样补回来：同一套 QSS、同一个 PE_Widget。
    """
    if widget is None or not widget.testAttribute(Qt.WA_OpaquePaintEvent):
        return
    opt = QStyleOption()
    opt.initFrom(widget)
    painter = QPainter(widget)
    widget.style().drawPrimitive(QStyle.PE_Widget, opt, painter, widget)
    painter.end()


def _lend_wallpaper(root, transparent: bool) -> None:
    """壁纸生效时，让页面根部直接拿「它盖住的那块壁纸」当自己的不透明底。

    画出来跟透到底下那一层一模一样，区别只在 Qt 知不知道这块矩形被填满了：
    透明时窗口每重绘一次，整棵页面树都要自下而上重新合成（实测 90 帧 6100
    次 paint）；换成不透明底之后，重绘停在页面这一层，静态壁纸下鼠标划过
    界面几乎不再产生重绘。

    只借给页面根部这一层：滚动区内部的宿主会跟着内容滚，裁片会错位。
    动态壁纸由背景层自己回绝（每帧都在变，借了只是多一次整幅拷贝）。
    """
    if root is None:
        return
    layer = getattr(root.window(), "_bg_layer", None)
    if layer is None or not hasattr(layer, "adopt_surface"):
        return
    if transparent:
        layer.adopt_surface(root)
    else:
        layer.release_surface(root)


def ensure_theme_surfaces(root, allow_transparent: bool = True) -> None:
    """paint_theme_surfaces 的带守卫版本：主题/背景态没变过就跳过。

    paint_theme_surfaces 要对 root 做整树 findChildren 遍历，导航切页、
    任务完成后的页面刷新都会点到已刷过的页面，没有守卫就是一遍遍重刷。
    守卫键 = (Theme._version, background_active, allow_transparent)；
    新构造的页面没有标记，首次必定真刷。
    """
    if root is None:
        return
    key = (Theme._version, bool(Theme.background_active), bool(allow_transparent))
    try:
        if getattr(root, "_pymcl_surf_key", None) == key:
            return
    except RuntimeError:
        return
    paint_theme_surfaces(root, allow_transparent)
    try:
        root._pymcl_surf_key = key
    except RuntimeError:
        pass


def _surface_color(allow_transparent: bool) -> str:
    """页面容器此刻该刷成什么底：壁纸生效就透明，否则 Theme.bg。"""
    transparent = bool(Theme.background_active) and allow_transparent
    return "transparent" if transparent else Theme.bg


def _ensure_name(w, hint: str) -> str:
    name = w.objectName()
    if not name:
        name = f"{hint}_{id(w)}"
        w.setObjectName(name)
    return name


def _set_palette(w, color: QColor) -> None:
    from PySide6.QtGui import QPalette
    if w is None:
        return
    # 写前去重：palette 一致就跳过，setPalette 会触发 changeEvent
    # + 样式重算，几百个控件每个都写一遍就是卡顿。
    pal = w.palette()
    if (pal.color(QPalette.ColorRole.Window) == color
            and pal.color(QPalette.ColorRole.Base) == color
            and w.autoFillBackground()):
        return
    pal.setColor(QPalette.ColorRole.Window, color)
    pal.setColor(QPalette.ColorRole.Base, color)
    w.setPalette(pal)
    # 容器需要自绘底；子控件不要开 autoFill，否则字旁又出色块
    w.setAutoFillBackground(True)


def _clear_fill(w) -> None:
    """透明模式：palette 底清成全透明并关掉 autoFill，否则 palette 填充
    仍会在 QSS 透明背景下面垫一层实色。"""
    from PySide6.QtGui import QPalette
    if w is None:
        return
    transparent = QColor(0, 0, 0, 0)
    pal = w.palette()
    if (pal.color(QPalette.ColorRole.Window) == transparent
            and not w.autoFillBackground()):
        return
    pal.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
    pal.setColor(QPalette.ColorRole.Base, QColor(0, 0, 0, 0))
    w.setPalette(pal)
    w.setAutoFillBackground(False)
    # 刚把底刷没了：如果这块之前借着壁纸裁片，标记也得跟着落下，
    # 否则「标记说借着、刷子其实是空的」，下游按不透明处理就画不出东西。
    # 紧随其后的 _lend_wallpaper 会重新借一次。
    w.setProperty("pymclLentWallpaper", False)


def _set_qss(w, qss: str) -> None:
    if w.styleSheet() != qss:
        w.setStyleSheet(qss)


def _paint_one(w, surface: str, *, hint: str = "pymclSurf", fill: str | None = None) -> None:
    if w is None:
        return
    color = fill or surface
    name = _ensure_name(w, hint)
    w.setAttribute(Qt.WA_StyledBackground, True)
    # 只用 ID 选择器，禁止无选择器规则
    _set_qss(w, f"#{name} {{ background-color: {color}; border: none; }}")
    if color == "transparent":
        _clear_fill(w)
    else:
        _set_palette(w, QColor(color))


def _paint_scroll(w, surface: str, bg_c: QColor) -> None:
    """滚动区三件套：外框、视口、内容宿主，各自只刷自己（ID 选择器）。"""
    transparent = surface == "transparent"
    sname = _ensure_name(w, "pymclScroll")
    w.setAttribute(Qt.WA_StyledBackground, True)
    _set_qss(w, f"#{sname} {{ background-color: {surface}; border: none; }}")
    if transparent:
        _clear_fill(w)
    else:
        _set_palette(w, bg_c)
    vp = w.viewport()
    if vp is not None:
        vname = _ensure_name(vp, "pymclVp")
        vp.setAttribute(Qt.WA_StyledBackground, True)
        _set_qss(vp, f"#{vname} {{ background-color: {surface}; border: none; }}")
        if transparent:
            _clear_fill(vp)
        else:
            _set_palette(vp, bg_c)
    inner = w.widget() if hasattr(w, "widget") else None
    if inner is not None:
        _paint_one(inner, surface, hint="pymclHost")


def prestyle_page(root, *scrolls, allow_transparent: bool = True) -> None:
    """页面构造早期就把根 / 滚动区 / 视口 / 宿主刷成 paint_theme_surfaces
    之后会刷的那一套（同名、同 QSS、同 palette）。

    为什么要提前：容器上每一次 setStyleSheet，Qt 都要把它**整棵子树**重新
    polish 一遍（setStyle_helper 递归到每个后代 + StyleChange 事件）。
    设置页有 54 张卡、几百个控件，页面建完再来刷根 / 滚动区 / 视口 / 宿主
    这四下，光这四次 setStyleSheet 就是 ~150ms，占首次进设置页一半以上。
    子控件还没进来时刷，同一句话几乎不花钱；等 _finish_page_build 里的
    paint_theme_surfaces 再走到这些容器，字符串已经相等，直接跳过。

    用法：`scroll.setWidget(host)` 之后、往 host 里加第一个子控件之前调
    `prestyle_page(self, scroll)`。不接管 ensure_theme_surfaces 的守卫键：
    标签清底 / SettingCard 补色仍由它首次真刷一遍。
    """
    if root is None:
        return
    surface = _surface_color(allow_transparent)
    bg_c = QColor(Theme.bg)
    _paint_one(root, surface, hint="pymclPage")
    for w in scrolls:
        if w is not None and not w.property("pymclTransparentScroll"):
            _paint_scroll(w, surface, bg_c)


def paint_theme_surfaces(root, allow_transparent: bool = True) -> None:
    """把 root 下承托 Fluent 卡片的容器刷成 Theme.bg。

    注意：Qt 样式表若写成无选择器的 `background-color: ...`，会**级联到所有子控件**，
    QLabel/Fluent 文字旁会出现一块深色底（实例卡、反馈 FAQ 就是这病）。
    因此这里一律用 `#objectName { ... }` 只刷自身。

    背景图生效（Theme.background_active）时改刷透明，让 stackedWidget 的
    border-image 从页面底下透出来；对话框里的表单宿主传 allow_transparent=False
    保持实底，不透出主窗背景图。
    """
    from PySide6.QtWidgets import (
        QAbstractScrollArea, QFormLayout, QFrame, QLabel, QScrollArea, QWidget,
    )

    if root is None:
        return
    bg = Theme.bg
    card = Theme.card
    fg = Theme.text
    bg_c = QColor(bg)
    card_c = QColor(card)
    surface = _surface_color(allow_transparent)
    transparent = surface == "transparent"

    _paint_one(root, surface, hint="pymclPage")
    _lend_wallpaper(root, transparent)

    try:
        from qfluentwidgets import SettingCard as FluentSettingCard
    except Exception:
        FluentSettingCard = type(None)
    transparent_c = QColor(0, 0, 0, 0)
    form_labels = []

    # 整棵子树只走一趟：findChildren 每调一次就把整棵子树重新包一遍
    # Python 对象，设置页几百个控件，分成滚动区 / QFrame / QLabel / QFormLayout
    # 四趟查就是四份包装开销（光这个函数就要 200ms+）。
    for w in root.findChildren(QWidget):
        lay = w.layout()
        if isinstance(lay, QFormLayout):
            # QFormLayout 的系统标签留到最后统一刷（保持原来的先后顺序）
            for i in range(lay.rowCount()):
                item = lay.itemAt(i, QFormLayout.ItemRole.LabelRole)
                lab = item.widget() if item is not None else None
                if isinstance(lab, QLabel) and "FluentLabel" not in type(lab).__name__:
                    form_labels.append(lab)

        if isinstance(w, QAbstractScrollArea):
            if w.property("pymclTransparentScroll"):
                # 透明滚动区（布局卡片内部）：保持透明，别刷成页面底色
                # 在卡片 (Theme.card) 上出色块。
                continue
            # 只刷「承托页面内容的滚动容器」（QScrollArea 及 Fluent 的
            # ScrollArea / SmoothScrollArea）。文本框、列表、表格
            # （QPlainTextEdit / QTextEdit / QListView / QTableView…）虽然
            # 也是 QAbstractScrollArea，但样式表是它们自己那套 Fluent 皮肤：
            # 这里一句 setStyleSheet 会把整份皮肤连同 `color: white` 一起
            # 抹掉，字色退回系统调色板的黑——深色下就是黑字压黑底、占位符
            # 几乎看不见（反馈页正文框、任务日志框都是这么坏的）。
            # 它们的底色由自己的皮肤负责，这里不碰。
            if isinstance(w, QScrollArea):
                _paint_scroll(w, surface, bg_c)
            continue

        # SettingCard：补卡片底色（选择器限定在 SettingCard，不灌进子 QLabel）
        if isinstance(w, QFrame) and isinstance(w, FluentSettingCard):
            prev = w.styleSheet() or ""
            marker = "/*pymcl-card*/"
            base = prev.split(marker)[0].rstrip() if marker in prev else prev
            target = (f"{base}\n{marker}\nSettingCard {{ background-color: {card};"
                      " border-radius: 6px; }")
            if prev != target:
                w.setStyleSheet(target)
            _set_palette(w, card_c)
            continue

        # 清掉子 QLabel 上被旧无选择器 QSS / palette 染上的实心底
        if isinstance(w, QLabel):
            _clear_label_fill(w, transparent_c)

    # QFormLayout 系统标签：字色跟 Theme，底透明
    for lab in form_labels:
        if lab.autoFillBackground():
            lab.setAutoFillBackground(False)
        _set_qss(lab, f"QLabel {{ color: {fg}; background: transparent; }}")


def _clear_label_fill(lab, transparent_c=None) -> None:
    """标签不要实心底。写前先读：autoFillBackground / setPalette 都会触发
    changeEvent + 样式重算，一页几百个标签每个都盲写一遍就是白卡。"""
    from PySide6.QtGui import QPalette
    if transparent_c is None:
        transparent_c = QColor(0, 0, 0, 0)
    if lab.autoFillBackground():
        lab.setAutoFillBackground(False)
    # Pill 等有意设了实心底的跳过
    if lab.property("pymclKeepBg"):
        return
    # FluentLabel 自己管 color；只确保不要 opaque Window 底
    try:
        pal = lab.palette()
        if pal.color(QPalette.ColorRole.Window) == transparent_c:
            return
        pal.setColor(QPalette.ColorRole.Window, transparent_c)
        lab.setPalette(pal)
    except Exception:
        pass


def clear_label_fills(root) -> None:
    """只做「清标签实心底」这一件事的轻量入口。

    新添几张卡时不必为它们整页重刷一遍表面（那要走整棵树 + 一堆
    setStyleSheet）；卡片自己带样式，真正会被旧 QSS 染上底的只有标签。
    """
    from PySide6.QtWidgets import QLabel
    if root is None:
        return
    transparent_c = QColor(0, 0, 0, 0)
    for lab in root.findChildren(QLabel):
        _clear_label_fill(lab, transparent_c)


def form_label(text: str):
    """表单左侧标签：跟 Theme，切深浅色可 restyle。"""
    from qfluentwidgets import BodyLabel
    lab = BodyLabel(text)
    lab.setProperty("pymclFormLabel", True)
    return lab


def ghost_btn_qss() -> str:
    return (
        f"PushButton {{ border: 1px solid {Theme.green}; color: {Theme.green};"
        f" background: {Theme.btn_bg}; border-radius: 4px; }}"
        f"PushButton:hover {{ background: {Theme.hover}; }}"
    )


def row_qss(name: str = "pclRow") -> str:
    return (
        f"#{name} {{ background: transparent; border-bottom: 1px solid {Theme.row_line}; }}"
        f"#{name}:hover {{ background: {Theme.row_hover}; }}"
    )


def chip_qss() -> str:
    return (
        f"color: {Theme.muted}; background: {Theme.chip}; border-radius: 3px;"
        " padding: 1px 6px; font-size: 11px;"
    )


def _icon(fif, color: str, size: int = 18):
    return fif.icon(color=QColor(color)).pixmap(size, size)


class PclTitleBar(TitleBar):
    """仅品牌 + 窗口按钮，不含主导航。"""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedHeight(TITLE_H)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.maxBtn.hide()
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.hBoxLayout.setSpacing(0)
        brand = QLabel("PyMCL")
        brand.setObjectName("pclBrand")
        self._brand = brand
        self.hBoxLayout.insertWidget(0, brand, 0, Qt.AlignVCenter)
        self.restyle()

    def paintEvent(self, e):
        # 标了不透明就得自己清底，见 paint_opaque_styled_background
        paint_opaque_styled_background(self)
        super().paintEvent(e)

    def restyle(self):
        # 跟侧栏共用一个不透明度，两条边框才不会一边实一边透
        mark_opaque(self, Theme.sidebar_opacity >= 100)
        self.setStyleSheet(
            f"PclTitleBar {{ background-color: {rgba(Theme.bg, Theme.sidebar_opacity)};"
            f" border-bottom: 1px solid {rgba(Theme.line, Theme.sidebar_opacity)}; }}"
            f"QLabel#pclBrand {{ color: {Theme.text}; font-size: 16px; font-weight: 700;"
            " background: transparent; padding-left: 16px; }"
        )
        idle = QColor(Theme.text)
        for btn in (self.minBtn, self.closeBtn):
            btn.setFixedSize(46, TITLE_H)
            btn.setNormalColor(idle)
            btn.setHoverColor(idle)
            btn.setPressedColor(idle)
            btn.setHoverBackgroundColor(QColor(0, 0, 0, 40) if Theme.dark else QColor(0, 0, 0, 20))
            btn.setPressedBackgroundColor(QColor(0, 0, 0, 70) if Theme.dark else QColor(0, 0, 0, 40))
        self.closeBtn.setHoverColor(QColor(255, 255, 255))
        self.closeBtn.setPressedColor(QColor(255, 255, 255))
        self.closeBtn.setHoverBackgroundColor(QColor(232, 17, 35))
        self.closeBtn.setPressedBackgroundColor(QColor(241, 112, 122))


class PclNavButton(QPushButton):
    def __init__(self, fif, text: str, indent: bool = False, parent=None):
        super().__init__(text, parent)
        self._fif = fif
        self._indent = indent
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32 if indent else 36)
        self.toggled.connect(self._sync_icon)
        self.restyle()

    def restyle(self):
        pad = 40 if self._indent else 14
        fs = "12px" if self._indent else "13px"
        idle = Theme.muted if self._indent else Theme.text
        # 侧栏半透明时高亮底也得跟着透，否则悬停/选中是一块实色方块糊在壁纸上。
        # 比侧栏本身多给一点不透明度，高亮才读得出来。
        hover = rgba(Theme.hover, min(100, Theme.sidebar_opacity + 15))
        self.setStyleSheet(
            f"PclNavButton {{ border: none; text-align: left; padding-left: {pad}px;"
            f" color: {idle}; background: transparent; font-size: {fs}; }}"
            f"PclNavButton:hover {{ background: {hover}; }}"
            f"PclNavButton:checked {{ color: {Theme.green}; background: {hover}; font-weight: 600; }}"
            f'PclNavButton[sectionOn="true"] {{ color: {Theme.green}; font-weight: 600; }}'
        )
        self._sync_icon(self.isChecked())

    def _sync_icon(self, checked: bool):
        size = 14 if self._indent else 16
        idle = Theme.muted if self._indent else Theme.text
        self.setIcon(_icon(self._fif, Theme.green if checked else idle, size))

    def set_section_on(self, on: bool):
        self.setProperty("sectionOn", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        if not self.isCheckable() or not self.isChecked():
            size = 14 if self._indent else 16
            idle = Theme.muted if self._indent else Theme.text
            self.setIcon(_icon(self._fif, Theme.green if on else idle, size))


class _SideResizer(QFrame):
    """侧栏右缘拖动条：拖动实时调宽，松手发 widthCommitted。"""

    MIN_W, MAX_W = 140, 320

    def __init__(self, bar: "PclSideBar"):
        super().__init__(bar)
        self.bar = bar
        self.setFixedWidth(5)
        self.setCursor(Qt.SizeHorCursor)
        self.setStyleSheet("background: transparent;")
        self._start = None  # (global_x, width)

    def mousePressEvent(self, e):
        self._start = (e.globalPosition().toPoint().x(), self.bar.width())
        e.accept()

    def mouseMoveEvent(self, e):
        if self._start is None:
            return
        gx, w0 = self._start
        w = w0 + int(e.globalPosition().toPoint().x() - gx)
        self.bar.setFixedWidth(max(self.MIN_W, min(self.MAX_W, w)))
        e.accept()

    def mouseReleaseEvent(self, e):
        if self._start is not None:
            self._start = None
            self.bar.widthCommitted.emit(self.bar.width())
        e.accept()


class PclSideBar(QFrame):
    """左侧导航。item=一级；group=可展开父级，children 为二级。"""

    currentChanged = Signal(str)
    widthCommitted = Signal(int)
    pinRequested = Signal(str)          # 兼容旧信号（无落点固定）
    pinAtRequested = Signal(str, str, bool)  # 拖到落点固定：(key, 目标key, 之前/之后)
    reorderRequested = Signal(str, str, bool)  # 侧栏内重排
    editLayoutRequested = Signal()      # 底部「编辑布局」动作（不切换页面）

    def __init__(self, items: list, parent=None, width: int | None = None):
        super().__init__(parent)
        self.setObjectName("pclSide")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(width if width and width >= 120 else SIDE_W)
        self._resizer = _SideResizer(self)
        self.setAcceptDrops(True)

        sl = QVBoxLayout(self)
        sl.setContentsMargins(0, 8, 0, 8)
        sl.setSpacing(1)
        self._root = sl

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        self._groups = {}
        self._last_group_child = {}
        self._headers = []
        self._dividers = []
        self.header_download = None

        first = None
        had_stretch = False
        for spec in items:
            kind = spec[0]
            if kind == "stretch":
                sl.addStretch(1)
                line = QFrame()
                line.setFixedHeight(1)
                self._dividers.append(line)
                sl.addWidget(line)
                had_stretch = True
                continue
            if kind == "header":
                lab = QLabel(spec[1])
                self._headers.append(lab)
                sl.addWidget(lab)
                continue
            if kind == "group":
                self._add_group(spec, sl)
                continue
            self._add_leaf(spec, sl, indent=spec[4] if len(spec) > 4 else False)
            if first is None:
                first = spec[1]
        if not had_stretch:
            sl.addStretch(1)

        # 底部动作：编辑启动页布局。放在侧栏最底：画布被卡片铺满，
        # 悬浮按钮放页面里总会压住卡片文字。
        from qfluentwidgets import FluentIcon as _FIF
        from mclauncher.i18n import tr as _tr
        self.edit_btn = PclNavButton(_FIF.EDIT, _tr("编辑布局"), indent=False)
        self.edit_btn.setCheckable(False)
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.setToolTip(_tr("自由调整启动页布局：拖动、缩放、增删卡片"))
        self.edit_btn.clicked.connect(self.editLayoutRequested.emit)
        sl.addWidget(self.edit_btn)

        self.restyle()
        if first:
            self.set_current(first, emit=False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "_resizer", None) is not None:
            self._resizer.setGeometry(self.width() - 5, 0, 5, self.height())

    def paintEvent(self, e):
        # 标了不透明就得自己清底，见 paint_opaque_styled_background
        paint_opaque_styled_background(self)
        super().paintEvent(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat("application/x-pymcl-nav"):
            e.acceptProposedAction()
        self._dragOver(e)

    def dragLeaveEvent(self, e):
        self._hide_drop_line()
        super().dragLeaveEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat("application/x-pymcl-nav"):
            e.acceptProposedAction()
        self._dragOver(e)

    def dropEvent(self, e):
        self._hide_drop_line()
        key = bytes(e.mimeData().data("application/x-pymcl-nav")).decode("utf-8", "ignore")
        if not key:
            e.ignore()
            return
        hit = self._button_at(e.position().toPoint())
        if key in self._buttons:
            # 已在侧栏里：按落点重排（拖到按钮上半=插它前面，下半=后面）
            if hit is not None and hit[0] != key:
                self.reorderRequested.emit(key, hit[0], hit[1])
        else:
            # 分区子页拖入：固定，并落到落点位置（没有落点则追加）
            target, before = (hit[0], hit[1]) if hit else (None, True)
            self.pinAtRequested.emit(key, target, before)
        e.acceptProposedAction()

    def _button_at(self, pos):
        """pos 处的 (key, 是否插它前面)；返回 None 表示落在按钮区外。

        可见性用几何有效性判断而非 isVisible()：布局尚未激活时 isVisible
        可能为假但几何已对（离屏/动画中途），反过来宽度超 sidebar 视为
        未布局的脏几何，直接跳过。
        """
        for key, btn in self._buttons.items():
            if btn.width() <= 0 or btn.width() > self.width() + 2:
                continue
            top = btn.mapTo(self, QPoint(0, 0))
            if top.x() <= pos.x() <= top.x() + btn.width():
                if top.y() <= pos.y() <= top.y() + btn.height():
                    return key, pos.y() < top.y() + btn.height() // 2
        return None

    def _dragOver(self, e):
        hit = self._button_at(e.position().toPoint())
        line = self._drop_line()
        if hit is None:
            line.hide()
            return
        key, before = hit
        btn = self._buttons[key]
        top = btn.mapTo(self, QPoint(0, 0))
        y = top.y() - 1 if before else top.y() + btn.height() - 1
        line.setGeometry(6, max(0, y), self.width() - 12, 2)
        line.raise_()
        line.show()

    def _drop_line(self):
        if getattr(self, "_line", None) is None:
            from PySide6.QtWidgets import QFrame as _QF
            self._line = _QF(self)
            self._line.setObjectName("pclDropLine")
            self._line.setFixedHeight(2)
            self._line.setStyleSheet(f"#pclDropLine {{ background: {Theme.green}; border: none; }}")
            self._line.hide()
        return self._line

    def _hide_drop_line(self):
        if getattr(self, "_line", None) is not None:
            self._line.hide()

    def eventFilter(self, obj, e):
        # navkey 属性的按钮：拖出 = 取消固定 / 拖动重排的拖拽源
        key = obj.property("navkey") if hasattr(obj, "property") else ""
        if not key:
            return super().eventFilter(obj, e)
        if e.type() == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
            self._drag_from = e.position().toPoint()
            return super().eventFilter(obj, e)
        if e.type() == QEvent.MouseButtonRelease:
            self._drag_from = None
            return super().eventFilter(obj, e)
        if e.type() == QEvent.MouseMove and getattr(self, "_drag_from", None) is not None:
            if (e.position().toPoint() - self._drag_from).manhattanLength() > 8:
                self._drag_from = None
                self._start_nav_drag(obj, str(key))
                return True
        return super().eventFilter(obj, e)

    @staticmethod
    def _start_nav_drag(widget, key: str):
        from PySide6.QtCore import QMimeData, QPoint
        from PySide6.QtGui import QDrag
        drag = QDrag(widget)
        mime = QMimeData()
        mime.setData("application/x-pymcl-nav", key.encode("utf-8"))
        drag.setMimeData(mime)
        # 带上按钮快照做拖拽影像，否则部分平台只变光标、看起来"没反应"
        pix = widget.grab()
        if not pix.isNull():
            drag.setPixmap(pix)
            drag.setHotSpot(QPoint(pix.width() // 2, pix.height() // 2))
        drag.exec(Qt.CopyAction)

    def restyle(self):
        # 半透明靠 rgba 背景，不用 QGraphicsOpacityEffect：后者会把整棵子树
        # （图标、文字、角标）一起调淡，导航项直接糊掉。
        mark_opaque(self, Theme.sidebar_opacity >= 100)
        self.setStyleSheet(
            f"#pclSide {{ background: {rgba(Theme.card, Theme.sidebar_opacity)};"
            f" border-right: 1px solid {rgba(Theme.line, Theme.sidebar_opacity)}; }}"
        )
        for lab in self._headers:
            lab.setStyleSheet(
                f"color: {Theme.muted}; font-size: 11px; padding: 12px 14px 4px 14px;"
                " background: transparent;")
        for line in self._dividers:
            line.setStyleSheet(f"background: {Theme.line}; border: none;")
        for btn in self._buttons.values():
            btn.restyle()
        for info in self._groups.values():
            info["btn"].restyle()
            info["chevron"].setStyleSheet(
                f"QToolButton {{ border: none; color: {Theme.muted}; font-size: 11px; background: transparent; }}"
            )

    def _add_leaf(self, spec, layout, indent=False):
        key, fif, title = spec[1], spec[2], spec[3]
        btn = PclNavButton(fif, title, indent=indent)
        if len(spec) > 5 and spec[5]:
            btn.setProperty("navkey", key)
            btn.installEventFilter(self)
        layout.addWidget(btn)
        self._group.addButton(btn)
        self._buttons[key] = btn
        btn.clicked.connect(lambda _, k=key: self.set_current(k, emit=True))
        return btn

    def _add_group(self, spec, layout):
        gkey, fif, title, children = spec[1], spec[2], spec[3], spec[4]
        wrap = QWidget()
        vl = QVBoxLayout(wrap)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(0)

        head = QWidget()
        head.setFixedHeight(36)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 4, 0)
        hl.setSpacing(0)
        gbtn = PclNavButton(fif, title, indent=False)
        gbtn.setCheckable(False)
        chevron = QToolButton()
        chevron.setAutoRaise(True)
        chevron.setCursor(Qt.PointingHandCursor)
        chevron.setFixedSize(22, 22)
        hl.addWidget(gbtn, 1)
        hl.addWidget(chevron, 0, Qt.AlignVCenter)

        child_host = QWidget()
        cl = QVBoxLayout(child_host)
        cl.setContentsMargins(0, 0, 0, 4)
        cl.setSpacing(0)
        child_keys = []
        for child in children:
            self._add_leaf(child, cl, indent=True)
            child_keys.append(child[1])

        vl.addWidget(head)
        vl.addWidget(child_host)
        layout.addWidget(wrap)

        gbtn.clicked.connect(lambda: self._on_group_click(gkey))
        chevron.clicked.connect(lambda: self._toggle_group(gkey))

        self._groups[gkey] = {
            "btn": gbtn,
            "chevron": chevron,
            "host": child_host,
            "children": child_keys,
            "expanded": True,
        }
        if gkey == "download":
            self.header_download = gbtn
        self._sync_group(gkey)

    def _toggle_group(self, gkey: str):
        info = self._groups[gkey]
        info["expanded"] = not info["expanded"]
        self._sync_group(gkey)

    def _on_group_click(self, gkey: str):
        info = self._groups[gkey]
        if not info["expanded"]:
            info["expanded"] = True
            self._sync_group(gkey)
        last = self._last_group_child.get(gkey) or (info["children"][0] if info["children"] else None)
        if last:
            self.set_current(last, emit=True)

    def _sync_group(self, gkey: str):
        info = self._groups[gkey]
        host = info["host"]
        info["chevron"].setText("▾" if info["expanded"] else "▸")
        prev = info.get("anim")
        if prev is not None:
            prev.stop()
        from .motion import tween
        if info["expanded"]:
            if not host.isVisible():
                target = max(1, host.sizeHint().height())
                host.setMaximumHeight(0)
                host.setVisible(True)
                # context=host：侧栏被 _rebuild_sidebar 整个重建时 host 先死，
                # 动画得随它一起停，不然剩下的几帧都打在死控件上。
                info["anim"] = tween(
                    lambda h: host.setMaximumHeight(int(h)), 0, target, ms=180,
                    on_done=lambda: host.setMaximumHeight(16777215), context=host)
            else:
                host.setMaximumHeight(16777215)
                info["anim"] = None
        else:
            target = max(1, host.sizeHint().height())
            info["anim"] = tween(
                lambda h: host.setMaximumHeight(int(h)), target, 0, ms=160,
                on_done=lambda: host.hide() if not info["expanded"]
                else host.setMaximumHeight(16777215), context=host)
        current_in = any(
            self._buttons[k].isChecked() for k in info["children"] if k in self._buttons
        )
        info["btn"].set_section_on(current_in)

    def set_current(self, key: str, emit: bool = True):
        if key in self._groups and key not in self._buttons:
            self._on_group_click(key)
            return
        btn = self._buttons.get(key)
        if btn is None:
            return
        btn.setChecked(True)
        for gkey, info in self._groups.items():
            if key in info["children"]:
                self._last_group_child[gkey] = key
                if not info["expanded"]:
                    info["expanded"] = True
            self._sync_group(gkey)
        if emit:
            self.currentChanged.emit(key)

    def button(self, key: str):
        if key in self._buttons:
            return self._buttons[key]
        info = self._groups.get(key)
        return info["btn"] if info else None


PclSubButton = PclNavButton


def fade_stack_to(stack, widget, holder, duration: int = 170):
    """主栈切页：直接瞬时，不做「截图封面滑入/淡出」——那要在每点一次导航时
    同步抓整屏光栅图，弱机就是肉眼可见的顿挫。动效只留给小范围的局部动画
    （进度补间、角标脉冲等）。
    """
    _cleanup_nav_covers(holder)
    _set_stack(stack, widget)


def _cleanup_nav_covers(holder):
    prev = getattr(holder, "_nav_cover", None)
    if prev is not None:
        try:
            prev.hide()
            prev.deleteLater()
        except RuntimeError:
            pass
        holder._nav_cover = None
    group = getattr(holder, "_nav_fade", None)
    if group is not None:
        try:
            group.stop()
        except RuntimeError:
            pass
        holder._nav_fade = None


def _stack_popout(stack, widget) -> bool:
    try:
        stack.setCurrentWidget(widget, popOut=False)
        return True
    except TypeError:
        stack.setCurrentWidget(widget)
        return False


def _set_stack(stack, widget):
    _stack_popout(stack, widget)

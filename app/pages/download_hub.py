# -*- coding: utf-8 -*-
"""下载分区：顶部分类横条 + 内容页。"""

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QEvent, QParallelAnimationGroup, QPoint,
    QPropertyAnimation, QRect, Qt, QTimer, Signal,
)
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..motion import fade as _mcl_fade
from ..pcl_chrome import Theme


class SlideHStack(QStackedWidget):
    """左右滑页：先盖住旧帧，切到真页后再抓新帧，动画层盖住切换。"""

    DURATION = 260

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self._from = QLabel(self)
        self._to = QLabel(self)
        for lab in (self._from, self._to):
            lab.setScaledContents(True)
            lab.hide()
        self._ani = None
        self._pending = None
        self._grab_gen = 0
        self._last_slide_ms = 0

    def slide_to(self, widget):
        if widget is None:
            return
        if widget is self.currentWidget() or self.indexOf(widget) < 0:
            return
        from ..motion_prefs import ui_motion_ok
        import time
        now = int(time.monotonic() * 1000)
        rapid = (now - self._last_slide_ms) < 180
        self._last_slide_ms = now
        if (not ui_motion_ok()) or rapid:
            if self._ani and self._ani.state() == QAbstractAnimation.Running:
                self._ani.stop()
            self._finish_now(widget)
            return
        if self._ani and self._ani.state() == QAbstractAnimation.Running:
            self._ani.stop()
            self._finish_now(self._pending or widget)
        elif self._pending is not None and self._ani is None:
            # 上一帧 grab 尚未回来，直接落到目标页
            self._grab_gen += 1
            self._finish_now(widget)
            return
        old = self.currentWidget()
        if old is None or self.width() < 8:
            super().setCurrentWidget(widget)
            return
        direction = 1 if self.indexOf(widget) > self.indexOf(old) else -1
        w, h = self.width(), self.height()
        pix_old = old.grab()
        if pix_old.isNull():
            super().setCurrentWidget(widget)
            return
        self._from.setPixmap(pix_old)
        self._from.setGeometry(0, 0, w, h)
        self._from.show()
        self._from.raise_()
        super().setCurrentWidget(widget)
        widget.resize(w, h)
        widget.ensurePolished()
        lay = widget.layout()
        if lay is not None:
            lay.activate()
        # setCurrentWidget 后立刻 grab 常抓到未布局完的空白帧；推迟到下一事件循环再抓
        self._pending = widget
        self._grab_gen += 1
        gen = self._grab_gen
        QTimer.singleShot(
            0, self, lambda: self._grab_new_and_animate(widget, direction, w, h, gen))

    def _grab_new_and_animate(self, widget, direction, w, h, gen):
        if gen != self._grab_gen or self._pending is not widget:
            return
        if self.currentWidget() is not widget or self.indexOf(widget) < 0:
            self._clear_slides()
            return
        pix_new = widget.grab()
        if pix_new.isNull():
            self._clear_slides()
            return
        self._to.setPixmap(pix_new)
        self._to.setGeometry(direction * w, 0, w, h)
        self._to.show()
        self._to.raise_()

        group = QParallelAnimationGroup(self)
        a1 = QPropertyAnimation(self._from, b"pos", self)
        a1.setEndValue(QPoint(-direction * w, 0))
        a2 = QPropertyAnimation(self._to, b"pos", self)
        a2.setEndValue(QPoint(0, 0))
        for ani in (a1, a2):
            ani.setDuration(self.DURATION)
            ani.setEasingCurve(QEasingCurve.OutCubic)
            ani.setStartValue(ani.targetObject().pos())
            group.addAnimation(ani)
        group.finished.connect(self._clear_slides)
        self._ani = group
        group.start()

    def _finish_now(self, widget):
        self._grab_gen += 1
        self._clear_slides()
        if widget is not None and self.indexOf(widget) >= 0:
            super().setCurrentWidget(widget)

    def _clear_slides(self):
        self._from.hide()
        self._to.hide()
        self._from.clear()
        self._to.clear()
        self._ani = None
        self._pending = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._from.isVisible():
            target = self._pending or self.currentWidget()
            if self._ani:
                self._ani.stop()
            self._finish_now(target)


NAV_MIME = "application/x-pymcl-nav"


def nav_key_of(mime) -> str:
    """拖拽里带的导航键；不是导航拖拽就返回空串。"""
    if not mime.hasFormat(NAV_MIME):
        return ""
    return bytes(mime.data(NAV_MIME)).decode("utf-8", "ignore")


def unpinnable_key_of(mime) -> str:
    """这一拖是不是「把侧栏固定项拖回分区」；不是就返回空串。

    横条按钮在自己栏里乱拖也带同一种 mime，那种不该亮落点提示——
    真能放回来的只有当前固定在侧栏上的键。
    """
    key = nav_key_of(mime)
    if not key:
        return ""
    from ..main_window import pinned_from_config
    return key if key in pinned_from_config() else ""


def section_of(widget):
    """往上找承载这个子页的分区壳，找不到返回 None。"""
    w = widget.parentWidget()
    while w is not None and not isinstance(w, DownloadSection):
        w = w.parentWidget()
    return w


def forward_nav_drag(widget, event) -> bool:
    """子页替身后的分区壳接住导航拖拽。

    Qt 的拖放不冒泡：自己也 setAcceptDrops 的子页（整合包页、模组页）
    会把落在它上面的事件整个吃掉，分区壳再也收不到。这些页在自己的
    dragEnter/drop 里调一下这个函数，把导航拖拽转交给壳。
    """
    key = unpinnable_key_of(event.mimeData())
    if not key:
        return False
    sec = section_of(widget)
    if sec is None:
        return False
    if event.type() == QEvent.Drop:
        sec.take_nav_drop(key)
    else:
        sec.show_drop_veil(True)
    event.acceptProposedAction()
    return True


def forward_nav_leave(widget):
    """配合 forward_nav_drag：拖拽移出子页时把壳上的提示收掉。"""
    sec = section_of(widget)
    if sec is not None:
        sec.show_drop_veil(False)


class _DragButton(QPushButton):
    """分类按钮 + 拖拽源：拖到侧栏即"固定为一级导航项"。"""

    def __init__(self, title: str, nav_key: str = "", parent=None):
        super().__init__(title, parent)
        self._nav_key = nav_key
        if nav_key:
            self.setProperty("navkey", nav_key)
        self._press_pos = None

    def mousePressEvent(self, e):
        self._press_pos = e.position().toPoint() if self._nav_key else None
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._press_pos = None
        super().mouseReleaseEvent(e)

    def mouseMoveEvent(self, e):
        if self._press_pos is not None and (e.position().toPoint() - self._press_pos).manhattanLength() > 8:
            self._press_pos = None
            self._start_nav_drag()
            return
        super().mouseMoveEvent(e)

    def _start_nav_drag(self):
        from PySide6.QtCore import QMimeData, QPoint
        from PySide6.QtGui import QDrag
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(NAV_MIME, self._nav_key.encode("utf-8"))
        mime.setText(self.text())
        drag.setMimeData(mime)
        pix = self.grab()
        if not pix.isNull():
            drag.setPixmap(pix)
            drag.setHotSpot(QPoint(pix.width() // 2, pix.height() // 2))
        drag.exec(Qt.CopyAction)


class DownloadCatBar(QFrame):
    currentChanged = Signal(object)
    unpinRequested = Signal(str, int)   # 拖回分类条：(key, 插入位序，-1=末尾)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("downloadCatBar")
        self.setFixedHeight(48)
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("catScroll")
        self._scroll.setWidgetResizable(False)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setFixedHeight(48)

        self._host = QWidget()
        self._layout = QHBoxLayout(self._host)
        self._layout.setContentsMargins(16, 0, 16, 4)
        self._layout.setSpacing(4)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons = {}
        self._lazy = {}  # index -> (btn, title)：bind 先建的懒按钮，页面构造后 wire
        self._layout.addStretch(1)
        self._scroll.setWidget(self._host)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._scroll)

        self.setAcceptDrops(True)
        self._indicator = QFrame(self._host)
        self._indicator.setObjectName("catIndicator")
        self._indicator.setFixedHeight(2)
        self._indicator.hide()
        self._ind_anim = QPropertyAnimation(self._indicator, b"geometry", self)
        self._ind_anim.setDuration(240)
        self._ind_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.restyle()

    def restyle(self):
        self.setStyleSheet(
            f"#downloadCatBar {{ background: transparent; border-bottom: 1px solid {Theme.line}; }}"
        )
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:horizontal { height: 6px; background: transparent; }"
            f"QScrollBar::handle:horizontal {{ background: {Theme.line}; border-radius: 3px; min-width: 24px; }}"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }"
        )
        self._indicator.setStyleSheet(
            f"#catIndicator {{ background: {Theme.green}; border: none; border-radius: 1px; }}"
        )
        for btn, _ in self._buttons.values():
            self._style_btn(btn)
        for btn, _ in self._lazy.values():
            self._style_btn(btn)

    def _style_btn(self, btn):
        btn.setStyleSheet(
            f"QPushButton {{ border: none; background: transparent; color: {Theme.muted};"
            " font-size: 14px; padding: 0 16px; }"
            f"QPushButton:hover {{ color: {Theme.text}; background: {Theme.hover}; }}"
            f"QPushButton:checked {{ color: {Theme.green}; font-weight: 700; }}"
        )

    def add_item(self, title: str, page):
        btn = self._make_btn(title)
        self._buttons[id(page)] = (btn, page)
        btn.clicked.connect(lambda _, p=page: self.currentChanged.emit(p))
        self._add_btn(btn)

    def add_lazy_item(self, title: str, owner, index: int, nav_key: str = ""):
        """bind 阶段先建按钮（页面还没构造）：点击时回调 owner._open_pending。"""
        btn = self._make_btn(title, nav_key)
        self._lazy[index] = (btn, title)
        btn.clicked.connect(lambda _, o=owner, i=index: o._open_pending(i))
        self._add_btn(btn)
        _mcl_fade(btn, 0.0, 1.0, ms=150)

    def wire_item(self, title: str, page) -> bool:
        """页面真正构造好后，把同名的懒建按钮接到页面上（不重复建按钮）。"""
        for index, (btn, t) in list(self._lazy.items()):
            if t == title:
                del self._lazy[index]
                self._buttons[id(page)] = (btn, page)
                try:
                    btn.clicked.disconnect()
                except TypeError:
                    pass
                btn.clicked.connect(lambda _, p=page: self.currentChanged.emit(p))
                return True
        return False

    def _make_btn(self, title: str, nav_key: str = "") -> QPushButton:
        btn = _DragButton(title, nav_key)
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(40)
        self._style_btn(btn)
        self._group.addButton(btn)
        return btn

    def _add_btn(self, btn):
        self._layout.insertWidget(self._layout.count() - 1, btn)
        self._host.adjustSize()
        self._host.setMinimumWidth(max(self._host.sizeHint().width(), self._layout.sizeHint().width()))
        if len(self._group.buttons()) == 1:
            btn.setChecked(True)

    def select_page(self, page, animate: bool = True):
        hit = self._buttons.get(id(page))
        if not hit:
            return
        btn, _ = hit
        btn.setChecked(True)
        self._move_indicator(btn, animate=animate)
        self._scroll.ensureWidgetVisible(btn, 24, 0)

    def dragEnterEvent(self, e):
        if unpinnable_key_of(e.mimeData()):
            self._show_drop_line(e.position().toPoint())
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if unpinnable_key_of(e.mimeData()):
            self._show_drop_line(e.position().toPoint())
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._hide_drop_line()
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self._hide_drop_line()
        # 判据跟 dragEnter / dragMove 同一个：那两处只认「当前固定在侧栏上的
        # 键」，这里却放行任意导航键，松手后上游又因为「不在 pinned 里」静默
        # 返回——用户看到的就是光标说能放、放下去什么也没发生。
        key = unpinnable_key_of(e.mimeData())
        if not key:
            e.ignore()
            return
        self.unpinRequested.emit(key, self.insert_index_at(e.position().toPoint()))
        e.acceptProposedAction()

    # ---- 落点计算与提示线（对齐侧栏那条绿线的手感）----
    def ordered_buttons(self) -> list:
        """横条上按显示顺序排好的按钮（跟分区成员列表一一对应）。"""
        out = []
        for i in range(self._layout.count()):
            w = self._layout.itemAt(i).widget()
            if isinstance(w, QPushButton):
                out.append(w)
        return out

    def insert_index_at(self, pos) -> int:
        """pos 处的插入位序；落在按钮区之外返回 -1（= 追加到末尾）。"""
        for i, btn in enumerate(self.ordered_buttons()):
            left = self._host.mapTo(self, btn.geometry().topLeft()).x()
            w = btn.width()
            if pos.x() < left + w // 2:
                return i
            if pos.x() < left + w:
                return i + 1
        return -1

    def _drop_line(self) -> QFrame:
        if getattr(self, "_dline", None) is None:
            self._dline = QFrame(self)
            self._dline.setObjectName("catDropLine")
            self._dline.setFixedWidth(2)
            self._dline.setStyleSheet(
                f"#catDropLine {{ background: {Theme.green}; border: none; }}")
            self._dline.hide()
        return self._dline

    def _show_drop_line(self, pos):
        btns = self.ordered_buttons()
        idx = self.insert_index_at(pos)
        line = self._drop_line()
        if not btns:
            x = 16
        elif idx < 0 or idx >= len(btns):
            last = btns[-1].geometry()
            x = self._host.mapTo(self, last.topLeft()).x() + last.width()
        else:
            x = self._host.mapTo(self, btns[idx].geometry().topLeft()).x()
        line.setGeometry(max(0, x - 1), 6, 2, max(8, self.height() - 16))
        line.raise_()
        line.show()

    def _hide_drop_line(self):
        if getattr(self, "_dline", None) is not None:
            self._dline.hide()

    def _indicator_rect(self, btn) -> QRect:
        r = btn.geometry()
        pad = 16
        return QRect(r.x() + pad, self._host.height() - 6, max(16, r.width() - pad * 2), 2)

    def _move_indicator(self, btn, animate: bool = True):
        if btn is None:
            return
        target = self._indicator_rect(btn)
        self._indicator.show()
        self._indicator.raise_()
        if (not animate) or (not self._indicator.geometry().isValid()) or self._indicator.width() < 4:
            self._ind_anim.stop()
            self._indicator.setGeometry(target)
            return
        self._ind_anim.stop()
        self._ind_anim.setStartValue(self._indicator.geometry())
        self._ind_anim.setEndValue(target)
        self._ind_anim.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        btn = self._group.checkedButton()
        if btn:
            self._move_indicator(btn, animate=False)

    def showEvent(self, event):
        super().showEvent(event)
        btn = self._group.checkedButton()
        if btn:
            self._move_indicator(btn, animate=False)


class DownloadSection(QWidget):
    """侧栏「下载」：分类横条切换子页。

    子页懒加载：bind 收 (标题, getter)，第一次进入分区或点开某页时
    getter 才真正构造页面（MainWindow._ensure_sub 负责构造+注册+回填
    本分区）。冷启动不用再为 8 个搜索页各建一整套表单。
    """

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("downloadSection")
        self.backend = backend
        self.hub = self
        self._by_widget = {}
        self._pending = []  # [(title, getter)]，按声明顺序

        self.cat = DownloadCatBar()
        self.cat.currentChanged.connect(self.show_page)
        self.stack = SlideHStack(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.cat)
        root.addWidget(self.stack, 1)

        # 整个分区页都收「把固定项拖回来」，不只顶上那条 48px 的横条：
        # 只认横条的话用户十有八九松手在内容区，看到的是禁止光标。
        self.setAcceptDrops(True)
        self._drop_veil = None

    # ---- 把侧栏固定项拖回本分区 ----
    def dragEnterEvent(self, e):
        if unpinnable_key_of(e.mimeData()):
            self.show_drop_veil(True)
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if unpinnable_key_of(e.mimeData()):
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.show_drop_veil(False)
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        key = unpinnable_key_of(e.mimeData())
        if key:
            self.take_nav_drop(key)
            e.acceptProposedAction()

    def take_nav_drop(self, key: str):
        """收下一个拖回来的导航键：落到横条末尾。"""
        self.show_drop_veil(False)
        self.cat.unpinRequested.emit(key, -1)

    def show_drop_veil(self, on: bool):
        """拖拽悬停时铺一层「松手放回这一栏」的提示，让落点看得见。"""
        if not on:
            if self._drop_veil is not None:
                self._drop_veil.hide()
            return
        veil = self._drop_veil
        if veil is None:
            veil = QLabel(self)
            veil.setAlignment(Qt.AlignCenter)
            veil.setAttribute(Qt.WA_TransparentForMouseEvents)
            self._drop_veil = veil
        veil.setText(self._drop_veil_text())
        bg = "rgba(0, 0, 0, 140)" if Theme.dark else "rgba(255, 255, 255, 190)"
        veil.setStyleSheet(
            f"QLabel {{ color: {Theme.title}; font-size: 16px; font-weight: 600;"
            f" border: 2px dashed {Theme.green}; border-radius: 12px;"
            f" background-color: {bg}; }}"
        )
        veil.setGeometry(self.rect().adjusted(12, 12, -12, -12))
        veil.show()
        veil.raise_()

    def _drop_veil_text(self) -> str:
        from mclauncher.i18n import tr
        return tr("松手放回「下载」")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._drop_veil is not None and self._drop_veil.isVisible():
            self._drop_veil.setGeometry(self.rect().adjusted(12, 12, -12, -12))

    def add_page(self, page, title: str = ""):
        if page is None or page in self._by_widget:
            return
        self.stack.addWidget(page)
        self._by_widget[page] = title
        if title and not self.cat.wire_item(title, page):
            # bind 没建过懒按钮（如重建分区时顺序错位）才直接补一个
            self.cat.add_item(title, page)
        if self.stack.count() == 1:
            self.stack.setCurrentWidget(page)
            self.cat.select_page(page, animate=False)

    def bind(self, items: list, opener=None):
        del opener
        for spec in items:
            title, getter = spec[0], spec[1]
            key = spec[2] if len(spec) > 2 else ""
            index = len(self._pending)
            self._pending.append((title, getter))
            # 按钮立刻建（横条完整），页面留到第一次点击/进入才构造
            self.cat.add_lazy_item(title, self, index, key)

    def _open_pending(self, index: int):
        """懒按钮被点：先构造对应子页（getter → _ensure_sub → add_page），再切换。"""
        if not (0 <= index < len(self._pending)):
            return
        _title, getter = self._pending[index]
        page = getter()
        if page is not None:
            self.show_page(page)

    def ensure_first(self):
        """第一次进入分区时构造第一个子页（add_page 会把它设为当前页）。"""
        if self._by_widget or not self._pending:
            return
        _title, getter = self._pending[0]
        getter()

    def has_page(self, page) -> bool:
        return page is self or page in self._by_widget

    def current_page(self):
        return self.stack.currentWidget()

    def pages(self) -> list:
        return list(self._by_widget)

    def pending_specs(self) -> list:
        return list(self._pending)

    def show_hub(self):
        self.ensure_first()
        if self._by_widget:
            self.show_page(next(iter(self._by_widget)))

    def show_page(self, page):
        if page is self:
            self.show_hub()
            return
        if page not in self._by_widget:
            return
        if page is not self.stack.currentWidget():
            self.stack.slide_to(page)
        self.cat.select_page(page)
        win = self.window()
        fn = getattr(win, "_reload_page", None)
        if callable(fn):
            fn(page)


class MoreSection(DownloadSection):
    """侧栏「更多」：杂项页（版本管理/模组/账号/联机/服务器/时长/反馈/设置）共用横条切换壳。"""

    def _drop_veil_text(self) -> str:
        from mclauncher.i18n import tr
        return tr("松手放回「更多」")

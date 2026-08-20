# -*- coding: utf-8 -*-
"""下载分区：顶部分类横条 + 内容页。"""

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QParallelAnimationGroup, QPoint,
    QPropertyAnimation, QRect, Qt, Signal,
)
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
)

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

    def slide_to(self, widget):
        if widget is None:
            return
        if widget is self.currentWidget() or self.indexOf(widget) < 0:
            return
        if self._ani and self._ani.state() == QAbstractAnimation.Running:
            self._ani.stop()
            self._finish_now(self._pending or widget)
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
        pix_new = widget.grab()
        if pix_new.isNull():
            self._clear_slides()
            return
        self._to.setPixmap(pix_new)
        self._to.setGeometry(direction * w, 0, w, h)
        self._to.show()
        self._to.raise_()
        self._pending = widget

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


class DownloadCatBar(QFrame):
    currentChanged = Signal(object)

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
        self._layout.addStretch(1)
        self._scroll.setWidget(self._host)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._scroll)

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

    def _style_btn(self, btn):
        btn.setStyleSheet(
            f"QPushButton {{ border: none; background: transparent; color: {Theme.muted};"
            " font-size: 14px; padding: 0 16px; }"
            f"QPushButton:hover {{ color: {Theme.text}; background: {Theme.hover}; }}"
            f"QPushButton:checked {{ color: {Theme.green}; font-weight: 700; }}"
        )

    def add_item(self, title: str, page):
        btn = QPushButton(title)
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(40)
        self._style_btn(btn)
        self._group.addButton(btn)
        self._buttons[id(page)] = (btn, page)
        btn.clicked.connect(lambda _, p=page: self.currentChanged.emit(p))
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
    """侧栏「下载」：分类横条切换子页。"""

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setObjectName("downloadSection")
        self.backend = backend
        self.hub = self
        self._by_widget = {}

        self.cat = DownloadCatBar()
        self.cat.currentChanged.connect(self.show_page)
        self.stack = SlideHStack(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.cat)
        root.addWidget(self.stack, 1)

    def add_page(self, page, title: str = ""):
        if page is None or page in self._by_widget:
            return
        self.stack.addWidget(page)
        self._by_widget[page] = title
        if title:
            self.cat.add_item(title, page)
        if self.stack.count() == 1:
            self.stack.setCurrentWidget(page)
            self.cat.select_page(page, animate=False)

    def bind(self, items: list, opener=None):
        del opener
        for spec in items:
            if len(spec) == 2:
                title, page = spec
            else:
                title, page = spec[2], spec[4]
            self.add_page(page, title)

    def has_page(self, page) -> bool:
        return page is self or page in self._by_widget

    def current_page(self):
        return self.stack.currentWidget()

    def show_hub(self):
        pages = list(self._by_widget)
        if pages:
            self.show_page(pages[0])

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

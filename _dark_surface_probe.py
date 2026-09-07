# -*- coding: utf-8 -*-
"""离屏探针：深色模式下 ScrollArea viewport / SettingCard 是否不再浅灰。"""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from PySide6.QtGui import QPalette

app = QApplication([])

from qfluentwidgets import (
    FluentIcon as FIF, SettingCard, ScrollArea, setTheme, Theme as FT, isDarkTheme,
)
from app.pcl_chrome import Theme, paint_theme_surfaces

setTheme(FT.DARK, save=False)
Theme.apply(True)

page = QWidget()
page.setObjectName("settingsPage")
scroll = ScrollArea(page)
scroll.setWidgetResizable(True)
host = QWidget()
scroll.setWidget(host)
outer = QVBoxLayout(page)
outer.setContentsMargins(0, 0, 0, 0)
outer.addWidget(scroll)
lay = QVBoxLayout(host)
card = SettingCard(FIF.BRIGHTNESS, "深色模式", "立即生效")
lay.addWidget(card)

paint_theme_surfaces(page)

vp = scroll.viewport()
vp_c = vp.palette().color(QPalette.ColorRole.Window).name().upper()
host_c = host.palette().color(QPalette.ColorRole.Window).name().upper()
card_c = card.palette().color(QPalette.ColorRole.Window).name().upper()
ok = (
    isDarkTheme()
    and vp_c == "#1B1B1B"
    and host_c == "#1B1B1B"
    and card_c == "#242424"
    and "pymcl-card" in (card.styleSheet() or "")
)
print("RESULT", "PASS" if ok else "FAIL")
print("isDark", isDarkTheme(), "vp", vp_c, "host", host_c, "card", card_c)
print("card_marker", "pymcl-card" in (card.styleSheet() or ""))
raise SystemExit(0 if ok else 1)

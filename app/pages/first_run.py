# -*- coding: utf-8 -*-
"""首次运行向导：把该定的定了，顺带把几处藏得深的功能指一遍。

以前这里是一页四个输入框的设置框。目录和下载源它问得出来，但「分区里的
子页能拖到侧栏固定」「文件直接往窗口里拖就行，不用先找对页面」「壁纸和
AI 在哪」这些，用户只能自己撞见——而多数人撞不见。

所以改成分步：前两步照旧问设置，最后一步纯介绍。每一步都能「跳过向导」，
跳了也不会再弹（first_run 由主窗口那边落盘）；想再看，「设置 → 界面 → 启动向导」
能手动重跑（settings_page._rerun_wizard）。
"""
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ComboBox, LineEdit, MessageBoxBase, PushButton, SpinBox,
    StrongBodyLabel, SubtitleLabel,
)

from mclauncher.config import CONFIG
from mclauncher.i18n import tr

# 最后一步里指给用户看的那几件事：(标题, 说明)
HIGHLIGHTS = (
    ("把文件直接拖进窗口",
     "整合包、模组、资源包、光影、存档、皮肤、壁纸都认；认不准会问你一句，不用先找对页面。"),
    ("侧栏是可以排的",
     "「游戏」「更多」里的子页拖到侧栏就固定成一级项，从侧栏拖回去就还原；"
     "排法和显隐在「设置 → 自定义侧栏」。"),
    ("换个背景",
     "设置页能设静态壁纸、mp4 动态壁纸，或者指一个文件夹轮播；模糊和遮罩也在那儿调。"),
    ("AI 助手在侧栏「通用」组里",
     "崩溃日志看不懂、模组冲突理不清，可以直接问它。"),
    ("这个向导随时能再看",
     "「设置 → 界面 → 启动向导」点「重新运行」，目录、下载源、内存、隔离会再问一遍。"),
)


class FirstRunDialog(MessageBoxBase):
    """分步向导。yesButton 在最后一步之前是「下一步」，之后才是「开始使用」。"""

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.backend = backend
        self._index = 0

        self.title = SubtitleLabel(tr("欢迎使用 PyMCL"), self)
        self.viewLayout.addWidget(self.title)
        self.hint = BodyLabel("", self)
        self.hint.setWordWrap(True)
        self.viewLayout.addWidget(self.hint)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self._page_welcome())
        self.stack.addWidget(self._page_paths())
        self.stack.addWidget(self._page_game())
        self.stack.addWidget(self._page_highlights())
        self.viewLayout.addWidget(self.stack)

        self.step_label = CaptionLabel("", self)
        self.viewLayout.addWidget(self.step_label)

        self.back_btn = PushButton(tr("上一步"), self.buttonGroup)
        self.back_btn.clicked.connect(lambda: self._show(self._index - 1))
        self.buttonLayout.insertWidget(0, self.back_btn, 1)
        self.cancelButton.setText(tr("跳过向导"))
        self.widget.setMinimumWidth(520)
        self._show(0)

    # ------------------------------------------------------------------ 分步
    def _page_welcome(self) -> QWidget:
        page = QWidget(self)
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(StrongBodyLabel(tr("三步就能开始玩"), page))
        for line in (tr("1. 选游戏目录和下载源"),
                     tr("2. 定默认内存和版本隔离"),
                     tr("3. 看一眼几个容易错过的功能")):
            box.addWidget(BodyLabel(line, page))
        note = CaptionLabel(tr("这些以后都能在设置里改；不想现在弄就点「跳过向导」。"), page)
        note.setWordWrap(True)
        box.addWidget(note)
        box.addStretch(1)
        return page

    def _page_paths(self) -> QWidget:
        page = QWidget(self)
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(BodyLabel(tr("游戏目录（版本都装在这里）"), page))
        self.game_dir = LineEdit(page)
        self.game_dir.setText(str(self.backend.get_settings().get("game_dir") or CONFIG.instances_dir))
        row = QHBoxLayout()
        row.addWidget(self.game_dir, 1)
        browse = PushButton(tr("浏览"), page)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        box.addLayout(row)

        box.addWidget(BodyLabel(tr("文件下载源"), page))
        self.src = ComboBox(page)
        self.src.addItems([tr("自动（官方慢则 BMCLAPI）"), tr("仅官方"), tr("仅 BMCLAPI")])
        box.addWidget(self.src)
        tip = CaptionLabel(tr("国内网络建议保持「自动」：官方慢的时候会自己切到 BMCLAPI 镜像。"), page)
        tip.setWordWrap(True)
        box.addWidget(tip)
        box.addStretch(1)
        return page

    def _page_game(self) -> QWidget:
        from mclauncher.version_settings import ISOLATION_LABELS
        page = QWidget(self)
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(BodyLabel(tr("默认内存 (MB)"), page))
        self.memory = SpinBox(page)
        self.memory.setRange(512, 32768)
        self.memory.setValue(int(CONFIG.get("memory_mb") or 4096))
        box.addWidget(self.memory)

        box.addWidget(BodyLabel(tr("新版本默认隔离"), page))
        self._iso_keys = {tr(v): k for k, v in ISOLATION_LABELS.items()}
        self.iso = ComboBox(page)
        self.iso.addItems(list(self._iso_keys))
        current = CONFIG.get("default_isolation") or "all"
        for text, key in self._iso_keys.items():
            if key == current:
                self.iso.setCurrentText(text)
                break
        box.addWidget(self.iso)
        tip = CaptionLabel(
            tr("「完全独立」= 每个版本有自己的 mods / 配置 / 存档，换版本不会把上一个版本的模组拖进去。"),
            page)
        tip.setWordWrap(True)
        box.addWidget(tip)
        box.addStretch(1)
        return page

    def _page_highlights(self) -> QWidget:
        page = QWidget(self)
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        for title, body in HIGHLIGHTS:
            box.addWidget(StrongBodyLabel(tr(title), page))
            line = CaptionLabel(tr(body), page)
            line.setWordWrap(True)
            box.addWidget(line)
        box.addStretch(1)
        return page

    def _show(self, index: int):
        last = self.stack.count() - 1
        self._index = max(0, min(last, index))
        self.stack.setCurrentIndex(self._index)
        self.step_label.setText(tr("第 {0} / {1} 步").format(self._index + 1, last + 1))
        self.back_btn.setEnabled(self._index > 0)
        self.yesButton.setText(tr("开始使用") if self._index == last else tr("下一步"))
        self.hint.setText((
            tr("先把游戏目录和下载源定下来。"),
            tr("版本都会装在这个目录里；下载源决定从哪儿拉文件。"),
            tr("这两项只影响以后新建的版本，已经装好的不受影响。"),
            tr("最后几句，都是容易错过的地方。"),
        )[self._index])

    def accept(self):
        """「下一步」也走这儿（MessageBoxBase 的确定键直连 accept）。"""
        if self._index < self.stack.count() - 1:
            self._show(self._index + 1)
            return
        super().accept()

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, tr("选择游戏目录"), self.game_dir.text())
        if path:
            self.game_dir.setText(path)

    # ------------------------------------------------------------------ 落盘
    def apply(self):
        src = {tr("自动（官方慢则 BMCLAPI）"): "auto", tr("仅官方"): "official",
               tr("仅 BMCLAPI"): "bmclapi"}
        data = self.backend.get_settings()
        data.update({
            "download_source": src.get(self.src.currentText(), "auto"),
            "default_memory_mb": self.memory.value(),
            "default_isolation": self._iso_keys.get(self.iso.currentText(), "all"),
            "first_run": False,
        })
        self.backend.save_settings(data)
        path = self.game_dir.text().strip()
        if not path:
            return
        try:
            self.backend.set_game_dir(path)
        except Exception as exc:  # noqa: BLE001
            # 目录不可写必须拦下来说清楚：静默关掉向导会让用户以为设好了，
            # 其实实例还落在旧目录。
            from qfluentwidgets import MessageBox
            MessageBox(
                tr("游戏目录没能设置"),
                f"{path}\n\n{exc}\n\n" + tr("已保留原来的目录，可到「设置」里重新选择。"),
                self.parent() or self,
            ).exec()

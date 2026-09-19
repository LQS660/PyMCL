# -*- coding: utf-8 -*-
"""窗口背景层：静态图片与 mp4 动态壁纸。

旧实现把背景图当 QSS 的 border-image 贴在 stackedWidget 上，只盖得住右侧
内容区——侧栏就算调成半透明，透出来的也只是窗口底色。这里换成压在所有
兄弟控件最下面的一张画布，整个窗口都归它画，侧栏半透明才真能透出壁纸。

视频只接 QVideoSink 拿帧、自己 drawImage，不用 QVideoWidget：后者在
Windows 上可能要一个原生窗口句柄，原生子窗口永远浮在非原生兄弟之上，
半透明侧栏和悬浮下载条就全被它盖掉了。
"""

from __future__ import annotations

import os
import weakref

from PySide6.QtCore import (
    QElapsedTimer, QEvent, QPoint, QRect, QRectF, Qt, QUrl, Signal,
)
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QWidget

VIDEO_SUFFIXES = (".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif")
IMAGE_GLOBS = " ".join("*" + s for s in IMAGE_SUFFIXES)
VIDEO_GLOBS = " ".join("*" + s for s in VIDEO_SUFFIXES)

# 动态壁纸最快约 33fps。背景一动，压在它上面的透明页面树整片跟着重绘，
# 再快也只是白烧 CPU。
_MIN_FRAME_MS = 30
# 一帧从拿到图到贴完屏的预算。合成 + 整棵树重绘超过它，就把出帧间隔往后退，
# 让 GUI 线程留出处理输入的余地：壁纸掉几帧没人看得出来，界面卡一下人人都知道。
_FRAME_BUDGET_MS = 12
_MAX_FRAME_MS = 100


def is_video(path: str) -> bool:
    return os.path.splitext(str(path or ""))[1].lower() in VIDEO_SUFFIXES


def is_wallpaper(path: str) -> bool:
    suffix = os.path.splitext(str(path or ""))[1].lower()
    return suffix in VIDEO_SUFFIXES or suffix in IMAGE_SUFFIXES


class WallpaperPlaylist:
    """文件夹轮播：顺序播记着走到哪儿，随机播不连着抽同一张。

    每次换下一张都重扫一遍文件夹（就一次 scandir）：用户往里丢新图、
    删掉当前这张，下一轮自然就跟上了，不用重启也不用手动刷新。
    """

    def __init__(self):
        self._folder = ""
        self._shuffle = False
        self._files: list[str] = []
        self._current = ""

    def set_folder(self, folder: str, shuffle: bool) -> bool:
        """换文件夹 / 换播放顺序。返回这个文件夹里有没有能播的。"""
        folder = str(folder or "").strip()
        self._shuffle = bool(shuffle)
        if folder != self._folder:
            self._folder = folder
            self._current = ""
        self._scan()
        return bool(self._files)

    def _scan(self):
        if not self._folder or not os.path.isdir(self._folder):
            self._files = []
            return
        try:
            names = sorted(os.listdir(self._folder))
        except OSError:
            self._files = []
            return
        # normpath：文件夹可能是用户手敲的 `D:/壁纸`，拼出来就是 `D:/壁纸\a.png`
        # 这种混合分隔符。自己比对「当前这张还在不在表里」时会对不上。
        paths = (os.path.normpath(os.path.join(self._folder, n))
                 for n in names if is_wallpaper(n))
        self._files = [p for p in paths if os.path.isfile(p)]

    def current(self) -> str:
        """当前这张。还没挑过、或者原来那张被删了，就挑一张新的。"""
        if self._current and os.path.isfile(self._current):
            return self._current
        return self.advance()

    def advance(self) -> str:
        """下一张；文件夹空了返回空串。"""
        self._scan()
        if not self._files:
            self._current = ""
            return ""
        if len(self._files) == 1:
            self._current = self._files[0]
            return self._current
        if self._shuffle:
            import random
            pick = self._current
            while pick == self._current:
                pick = random.choice(self._files)
        else:
            try:
                pick = self._files[(self._files.index(self._current) + 1) % len(self._files)]
            except ValueError:  # 当前这张不在表里（被删了 / 刚换文件夹）
                pick = self._files[0]
        self._current = pick
        return pick


class BackgroundLayer(QWidget):
    """铺在窗口最底层的壁纸画布。鼠标穿透，不参与布局，几何由主窗口给。"""

    # 解码线程 → GUI 线程的过帧通道。过去的是已经拷贝出来的 QImage，
    # 不是 QVideoFrame，理由见 _grab_frame。
    _frame_ready = Signal(QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pclBackground")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        # 自己把整块矩形铺满（成品图里已经压好遮罩），Qt 就不必先在底下
        # 清一遍窗口底色，也能把这一层从上层控件的重绘区里减掉。
        # 没图可画时要撤掉，否则会留下一片没人画的脏矩形。
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.error = ""            # 壁纸没起来的原因，设置页拿它提示用户
        self._source = ""
        self._still = QImage()     # 静态壁纸原图
        self._frame = QImage()     # 最近一帧视频
        self._cache = QPixmap()    # 成品：按当前尺寸铺满 + 模糊 + 遮罩
        self._cache_key = None
        self._gen = 0              # 画面内容换一次加一，缓存靠它失效
        self._surfaces = weakref.WeakSet()  # 借了壁纸当底的页面
        self._filtered = weakref.WeakSet()  # 装过事件钩子的页面（借过就一直挂着，见 _paint_lent_backdrop）
        self._adopting = False     # 正在铺刷子，挡住自己触发的 PaletteChange
        self._player = None
        self._sink = None
        self._want_play = True
        self._clock = QElapsedTimer()   # GUI 线程：量这一拍花了多久
        self._gate = QElapsedTimer()    # 解码线程：距上一帧转换过了多久
        self._pace = _MIN_FRAME_MS  # 当前出帧间隔，按上一帧的真实开销调
        self._frame_ready.connect(self._on_frame)
        self._blur = 0             # 模糊半径 px
        self._dim = 0              # 遮罩浓度 %
        self._dim_color = "#FFFFFF"

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def source(self) -> str:
        return self._source

    def is_playing_video(self) -> bool:
        return self._player is not None

    def has_content(self) -> bool:
        return not self._frame.isNull() or not self._still.isNull()

    def set_source(self, path: str) -> bool:
        """换壁纸。返回这条路径是否被接受（视频要等首帧才画得出东西）。"""
        path = str(path or "").strip()
        if path == self._source:
            return not self.error
        self._stop_video()
        self._source = path
        self._still = QImage()
        self._frame = QImage()
        self._invalidate()
        self.error = ""
        if not path:
            self.update()
            return False
        if not os.path.isfile(path):
            self.error = f"文件不存在: {path}"
        elif is_video(path):
            self._start_video(path)
        else:
            img = QImage(path)
            if img.isNull():
                self.error = f"图片读不出来: {path}"
            else:
                self._still = img
        # 上面那次 _invalidate 是在清空旧图时做的，这一次是为新读进来的图：
        # 借出去的页面得拿到新壁纸的裁片，否则换壁纸后它还顶着上一张。
        self._invalidate()
        self.update()
        return not self.error

    def set_effects(self, blur: int, dim: int, dim_color: str):
        """可读性处理：blur=模糊半径 px，dim=遮罩浓度 %，dim_color 用主题底色。

        遮罩刷的是主题底色而不是黑色：浅色主题要的是把壁纸提亮压淡，
        深色主题才是压暗，一律刷黑的话浅色主题下深色文字反而更糊。
        """
        blur, dim = max(0, int(blur)), max(0, min(100, int(dim)))
        if (blur, dim, dim_color) == (self._blur, self._dim, self._dim_color):
            return
        self._blur, self._dim, self._dim_color = blur, dim, dim_color
        self._invalidate()
        self.update()

    def set_playing(self, playing: bool):
        """窗口失焦 / 最小化 / 隐藏时暂停动态壁纸，别让它在后台空转。"""
        self._want_play = bool(playing)
        player = self._player
        if player is None:
            return
        try:
            player.play() if self._want_play else player.pause()
        except RuntimeError:
            self._player = self._sink = None

    def stop(self):
        """主窗口关闭时收掉播放器，别把解码线程留到进程退出。"""
        self._stop_video()

    # ------------------------------------------------------------------
    # 视频
    # ------------------------------------------------------------------
    def _start_video(self, path: str):
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
        except ImportError as exc:
            self.error = f"这套 PySide6 没带 QtMultimedia，放不了视频壁纸: {exc}"
            return
        sink = QVideoSink(self)
        player = QMediaPlayer(self)
        player.setVideoSink(sink)
        # 不挂 QAudioOutput 就是天然静音：壁纸不该出声
        try:
            player.setLoops(QMediaPlayer.Loops.Infinite)
        except (AttributeError, TypeError):
            player.mediaStatusChanged.connect(self._on_media_status)
        # DirectConnection：这个槽要跑在发帧的那个线程上，见 _grab_frame
        sink.videoFrameChanged.connect(self._grab_frame, Qt.DirectConnection)
        player.errorOccurred.connect(self._on_player_error)
        self._sink, self._player = sink, player
        self._clock.restart()
        self._gate.restart()
        player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        if self._want_play:
            player.play()

    def _stop_video(self):
        player, sink = self._player, self._sink
        self._player = self._sink = None
        # 先摘掉直连的取帧槽。Qt 会等解码线程手头这一次 _grab_frame 走完再放行，
        # 之后就不会再有帧打进来；留着的话，下面 deleteLater 到真析构之间的那段
        # 时间里还能被调进来。
        if sink is not None:
            try:
                sink.videoFrameChanged.disconnect(self._grab_frame)
            except (RuntimeError, TypeError):
                pass
        for obj in (player, sink):
            if obj is None:
                continue
            try:
                if obj is player:
                    obj.stop()
                obj.deleteLater()
            except RuntimeError:
                pass

    def _grab_frame(self, frame):
        """解码线程上就地把帧拷成 QImage，再抛给 GUI 线程。

        这一步挪不到主线程去做。videoFrameChanged 是 FFmpeg 的渲染线程发的，
        按自动连接就成了排队投递：等主线程轮到这一帧，它背后那块后备缓冲
        （硬解时是显卡那边的纹理）早就不归我们管了，某些驱动上 toImage()
        当场读到野内存，进程直接 access violation 退出，日志里只留一行
        「Windows fatal exception: access violation」指着这里。就地转成
        QImage 是一次深拷贝，拷完那份内存跟解码器再无关系，怎么排队都安全。

        节流也放在这儿：要丢的帧就别花钱转。1080p 一帧转换是毫秒级的，
        30fps 全转再丢等于白占一个核。
        """
        if self._player is None or not self._want_play or not frame.isValid():
            return
        # 节流：来多少帧画多少帧会把整棵透明页面树拖下水。间隔是自适应的，
        # 见 _pace：上一帧合成 + 重绘花得越久，下一帧等得越久。
        if self._gate.isValid() and self._gate.elapsed() < self._pace:
            return
        self._gate.restart()
        try:
            img = frame.toImage()
        except Exception:  # noqa: BLE001 — 一帧转砸了不该把整条壁纸链拖死
            return
        if not img.isNull():
            self._frame_ready.emit(img)

    def _on_frame(self, img: QImage):
        # 播放器已经收掉了：换成静态图那一刻队列里还压着的帧别再盖上来
        if self._player is None or img.isNull():
            return
        # 看不见就不合成：最小化、切到别的窗口、壁纸层被藏起来时，这一帧
        # 走完全套缩放 + 整棵树重绘，屏幕上一个像素都不会变
        if not self.isVisible():
            return
        self._clock.restart()
        if not self._accept_frame(img):
            return
        self.update()
        # 这一拍的成本：合成（_backdrop）+ 这一次 update 触发的重绘都算在里面
        spent = self._clock.elapsed()
        if spent > _FRAME_BUDGET_MS:
            self._pace = min(_MAX_FRAME_MS, max(self._pace, int(spent * 2)))
        elif self._pace > _MIN_FRAME_MS:
            self._pace = max(_MIN_FRAME_MS, self._pace - 5)

    def _accept_frame(self, img: QImage) -> bool:
        """收下一帧解码图：缩到层尺寸、让成品图作废。返回这一帧收没收下。

        没走 _invalidate 是因为帧这条路跟「换壁纸 / 改参数」不一样：视频从来
        不外借（见 adopt_surface），每帧再遍历一遍借出去的那几块是白跑；
        成品图那块 QPixmap 也留着不丢，下一帧直接往里重画，省掉一次整幅分配。
        """
        img = self._shrink_to_layer(img)
        if img.isNull():
            return False
        self._frame = img
        self._gen += 1
        self._cache_key = None
        return True

    def _shrink_to_layer(self, img: QImage) -> QImage:
        """把解码出来的帧就地缩到够铺满这一层就行的尺寸。

        1080p 的片子铺 960x720 的窗口，每帧多扛着 3 倍像素走完「模糊 → 平滑
        缩放 → 裁切」整条链，纯属白烧；而且必须复制一份——toImage() 可能直接
        指着帧缓冲，回调一返回解码器就把那块内存收回去复用了，留到 paintEvent
        再读就是读野内存（本机实测直接段错误退出）。缩放本身产出的就是新缓冲，
        一步同时办了这两件事。

        视频这条链一律用 FastTransformation：30fps 下平滑缩放的那点细节差别
        看不出来，耗时却是两三倍。
        """
        if img.isNull():
            return img
        size = self.size()
        if size.width() <= 0 or size.height() <= 0:
            return img.copy()
        # 只在明显偏大时缩：等大或更小的帧再缩一次只会糊
        if img.width() < size.width() * 1.2 and img.height() < size.height() * 1.2:
            return img.copy()
        return img.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.FastTransformation)

    def _on_media_status(self, status):
        """setLoops 不可用时的兜底循环（老 Qt）。"""
        from PySide6.QtMultimedia import QMediaPlayer
        player = self._player
        if player is not None and status == QMediaPlayer.MediaStatus.EndOfMedia:
            player.setPosition(0)
            player.play()

    def _on_player_error(self, _error, message: str = ""):
        self.error = str(message or "视频解码失败（系统可能缺 H.264 解码器）")

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._invalidate()

    def _invalidate(self):
        """画面内容/尺寸/参数变了：成品图作废，下一次重绘再算。"""
        self._gen += 1
        self._cache = QPixmap()
        self._cache_key = None
        self.refresh_surfaces()

    # ------------------------------------------------------------------
    # 把壁纸借给页面当不透明底
    # ------------------------------------------------------------------
    def adopt_surface(self, widget) -> bool:
        """让 widget 拿「它自己那一块壁纸」当底，返回有没有接管成功。

        为什么要这么绕：壁纸铺在整窗最底下，页面表面被刷成透明，于是窗口
        任何一次重绘都得把整棵树自下而上重新合成一遍——实测开壁纸后 90 帧
        要走 6100 次 paint，不开只要 1700 次，鼠标扫过一颗按钮也是整窗重画。
        改成把同一块壁纸裁给页面自己当不透明底：画出来一模一样，但 Qt 知道
        这块矩形被填满了，重绘就停在这儿，下面的壁纸层和上面的整棵子树都不
        用再跟着动。

        动态壁纸不接管：它每帧都在变，接管只是白多一次整幅拷贝。
        """
        if widget is None:
            return False
        # 先挂上钩子再说：页面刚构造时往往还没布局，这一刻裁不出对得上的片，
        # 等它 Show / Resize 了再借一次。不挂就永远等不到第二次机会。
        self._surfaces.add(widget)
        if widget not in self._filtered:
            self._filtered.add(widget)
            widget.installEventFilter(self)
        crop = None if self._player is not None else self._crop_for(widget)
        if crop is None:
            self._unlend(widget)
            return False
        # setPalette 自己会再发一次 PaletteChange，挡住这一轮免得打转
        self._adopting = True
        try:
            pal = widget.palette()
            pal.setBrush(QPalette.ColorRole.Window, QBrush(crop))
            widget.setPalette(pal)
            widget.setAutoFillBackground(True)
            widget.setAttribute(Qt.WA_OpaquePaintEvent, True)
            widget.setProperty("pymclLentWallpaper", True)
            widget.update()
        finally:
            self._adopting = False
        return True

    def release_surface(self, widget):
        """不再借了（换回纯色壁纸）：不再跟着重裁，底交还给调用方。

        这里**不动调色板**：纯色模式下页面的底是 paint_theme_surfaces 刚
        刷好的实色 Theme.bg，在这儿顺手清成透明会把它变回非不透明控件，
        整棵树又得每帧重画一遍（实测 51ms → 518ms 的那一下）。
        事件钩子也**留着**：页面还标着 WA_OpaquePaintEvent，Qt 不会替它铺
        调色板底，那一笔仍由 _paint_lent_backdrop 补——这时刷子已经是实色
        Theme.bg，不补的话页面底下残留的是上一张壁纸。
        """
        if widget is None or widget not in self._surfaces:
            return
        self._surfaces.discard(widget)
        try:
            widget.setProperty("pymclLentWallpaper", False)
        except RuntimeError:
            pass

    def _unlend(self, widget):
        """借过但这一刻借不成（动态壁纸 / 几何还没就位）：底还原成全透明，
        由壁纸层自己画——画面照旧对，只是回到「整棵树重新合成」那条慢路。"""
        try:
            if not widget.property("pymclLentWallpaper"):
                return
            pal = widget.palette()
            pal.setBrush(QPalette.ColorRole.Window, QBrush(QColor(0, 0, 0, 0)))
            widget.setPalette(pal)
            widget.setAutoFillBackground(False)
            widget.setAttribute(Qt.WA_OpaquePaintEvent, False)
            widget.setProperty("pymclLentWallpaper", False)
            widget.update()
        except RuntimeError:
            pass

    def refresh_surfaces(self):
        """壁纸内容/尺寸变了：把借出去的那几块重裁一遍，别留旧画面。"""
        for widget in list(getattr(self, "_surfaces", ())):
            try:
                self.adopt_surface(widget)
            except RuntimeError:
                self._surfaces.discard(widget)

    _WATCHED = (QEvent.Resize, QEvent.Move, QEvent.Show,
                QEvent.PaletteChange, QEvent.StyleChange)

    def eventFilter(self, obj, event):
        """借出去那块一有风吹草动就重借一次；每次重绘先替它铺底。

        Resize / Move / Show：裁片得跟着走，否则页面上那块壁纸跟侧栏旁边的
        接不上缝。PaletteChange / StyleChange：主题重刷、样式表重新 polish
        都会把调色板连同我们铺的刷子一起抹掉——不补回来就会悄悄退回「整棵树
        每帧重新合成」的慢路，而且画面上看不出来，只有帧率知道。
        Paint：见 _paint_lent_backdrop。
        """
        et = event.type()
        if et == QEvent.Paint:
            self._paint_lent_backdrop(obj, event)
            return False
        if et in self._WATCHED and not self._adopting and obj in self._surfaces:
            self.adopt_surface(obj)
        return False

    @staticmethod
    def _paint_lent_backdrop(widget, event):
        """标了 WA_OpaquePaintEvent 的页面根，在它自己的 paintEvent 之前把底铺上。

        Qt 只给没标不透明的控件走 paintBackground——autoFillBackground 的调色板
        刷子就是在那一步铺的。adopt_surface 把裁片挂进调色板又标了不透明，等于
        告诉 Qt「这块我自己画」，可页面根本不会画：借出去那块就是一片没人画的
        黑，切回纯色后残留的是上一张壁纸，顶上滑过的提示条还会留拖影。这里在
        Paint 事件送到控件之前补上这一笔：借着壁纸时刷子是裁片，还回去后是
        paint_theme_surfaces 刷好的实色 Theme.bg，两种情况一句 fillRect 都对。
        """
        try:
            if not widget.testAttribute(Qt.WA_OpaquePaintEvent):
                return
            brush = widget.palette().brush(QPalette.ColorRole.Window)
        except RuntimeError:
            return
        if brush.style() == Qt.NoBrush:
            return
        painter = QPainter(widget)
        painter.fillRect(event.rect(), brush)
        painter.end()

    def _crop_for(self, widget):
        """widget 盖住的那块壁纸（窗口坐标）。露到层外就返回 None，不接管。"""
        host = self.parentWidget()
        if host is None or not widget.isVisibleTo(host):
            return None
        size = widget.size()
        if size.width() <= 0 or size.height() <= 0:
            return None
        pix = self._backdrop()
        if pix is None:
            return None
        rect = QRect(widget.mapTo(host, QPoint(0, 0)), size)
        if not pix.rect().contains(rect):
            return None
        return pix.copy(rect)

    def paintEvent(self, event):
        if self.width() <= 0 or self.height() <= 0:
            return
        # 只画脏区。整层跟窗口一样大，而绝大多数重绘是鼠标扫过一个按钮
        # 带起来的一小块——无视 event.rect() 整张贴一遍就是白烧。
        rect = event.rect().intersected(self.rect())
        if rect.isEmpty():
            return
        # 成品图在建 QPainter 之前备好：_backdrop 会翻 WA_OpaquePaintEvent，
        # 别在画笔已经架上之后动这个属性
        pix = self._backdrop()
        if pix is None:
            return
        QPainter(self).drawPixmap(rect.topLeft(), pix, rect)

    def _blit(self, painter, pos, rect):
        """把成品图上 rect 那一块 1:1 贴到 painter 的 pos 处。

        给左上角 + 源矩形，走的是直贴；写成 drawPixmap(rect, pix, rect)
        会拐进带缩放的那条路，实测单帧从 0.15ms 涨到 0.41ms。
        """
        pix = self._backdrop()
        if pix is not None:
            painter.drawPixmap(pos, pix, rect)

    def _backdrop(self):
        """整层的成品图：铺满 + 模糊 + 遮罩，一次算好反复贴。

        按「画面内容 + 尺寸 + 参数」缓存，只有新帧到达或尺寸/模糊/遮罩变了才真算。
        视频壁纸若每次 paintEvent 都把当前帧重新 _softened 一遍，因为重绘频率
        远高于出帧频率（鼠标扫过一个按钮就是一次），30fps 的片子会被重算上百次。
        """
        size = self.size()
        key = (self._gen, size.width(), size.height(),
               self._blur, self._dim, self._dim_color)
        if key == self._cache_key and not self._cache.isNull():
            return self._cache
        src = self._frame if not self._frame.isNull() else self._still
        if src.isNull():
            self.setAttribute(Qt.WA_OpaquePaintEvent, False)
            return None
        # 视频那条链走快速缩放：帧在 _shrink_to_layer 里已经缩到接近这个尺寸，
        # 再上平滑插值只是每帧多花几毫秒，看不出差别。开了模糊是例外——那时
        # 源图被 _softened 缩得很小，放回来还用最近邻就是一格一格的马赛克。
        video_fast = self._player is not None and self._blur <= 0
        src = self._softened(src)
        # 缩放、裁切、遮罩合成一趟画完，落在一块留着复用的 QPixmap 上。
        # 以前是「缩一张 → 裁一张 → 转成 QPixmap → 再蒙一层」，一秒三十遍
        # 就是每秒三次整幅分配 ×30 加一次格式转换 ×30，全给了垃圾回收。
        if self._cache.isNull() or self._cache.size() != size:
            # 从 RGB32 转出来的 QPixmap 没有 alpha 通道，贴屏时是直接拷贝而不是
            # 混合；QPixmap(size) 自带一条用不上的 alpha，白白让每次重绘都走
            # 混合那条路。成品图本来就不透明（遮罩已经压进去了）。
            self._cache = QPixmap.fromImage(QImage(size, QImage.Format_RGB32))
        pix = self._cache
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, not video_fast)
        painter.drawImage(self._cover_rect(src.size(), size), src, QRectF(src.rect()))
        if self._dim > 0:
            # 遮罩直接压进成品图：省掉每次重绘一次全幅 fillRect，
            # 也让这一层整块不透明（下面那句才站得住）
            color = QColor(self._dim_color)
            color.setAlphaF(self._dim / 100)
            painter.fillRect(pix.rect(), color)
        painter.end()
        self._cache_key = key
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        return pix

    @staticmethod
    def _cover_rect(src, dest) -> QRectF:
        """保比例铺满 dest 的目标矩形（居中，溢出的那一边由 QPainter 裁掉）。

        两个方向都取到不小于 dest：浮点算出来差个千分之一像素，右边或下边
        就会留下一条没画到的缝，而缝里是上一帧的残影。
        """
        scale = max(dest.width() / max(1, src.width()),
                    dest.height() / max(1, src.height()))
        w = max(float(dest.width()), src.width() * scale)
        h = max(float(dest.height()), src.height() * scale)
        return QRectF((dest.width() - w) / 2, (dest.height() - h) / 2, w, h)

    def _softened(self, img: QImage) -> QImage:
        """缩下去再放回来当模糊用。

        真高斯模糊要 QGraphicsBlurEffect 把整张图渲一遍，动态壁纸 30fps
        就是 30 次离屏渲染；两次平滑缩放拿到的观感差不多，还更便宜。
        """
        if self._blur <= 0 or img.isNull():
            return img
        k = 1 + self._blur / 3
        w = max(2, int(img.width() / k))
        h = max(2, int(img.height() / k))
        return img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    def _still_pixmap(self) -> QPixmap:
        """当前尺寸下裁好的成品图。静态与视频共用 _backdrop 那条缓存。"""
        return self._backdrop() or QPixmap()

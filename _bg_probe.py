# -*- coding: utf-8 -*-
"""壁纸探针：静态图 / mp4 动态壁纸 / 侧栏半透明 / 撤销与恢复默认。"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mclauncher import feedback as _fb  # noqa: E402
_fb.start_heartbeat = lambda *a, **k: None
_fb.stop_heartbeat = lambda *a, **k: None

# 探针从头到尾都在换壁纸、推历史栈，每一下都落 config。写的要是用户那份
# config.json，中途崩一次或被 kill 掉，启动器的真实设置就留在探针的中间态上
# （壁纸指着一个待删的临时文件那种）。整份配置改指到临时目录：
# 起点还是用户的真实设置，但写只写临时那份。
from mclauncher import config as _config  # noqa: E402
_probe_home = tempfile.mkdtemp(prefix="pymcl-bgprobe-")
_config.CONFIG_FILE = Path(_probe_home) / "config.json"
_config.CONFIG.save()

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402

app = QApplication([])

FAILS = []


def check(cond, msg):
    tag = "ok" if cond else "FAIL"
    print(f"[{tag}] {msg}")
    if not cond:
        FAILS.append(msg)


def surface_ok(page, want_transparent: bool) -> bool:
    """不在眼前的页面按设计只挂 _pymcl_theme_stale，切过去那一刻才补刷。"""
    if getattr(page, "_pymcl_theme_stale", False):
        return True
    return ("transparent" in page.styleSheet()) is want_transparent


tmp_img = os.path.abspath("_bg_probe_tmp.png").replace("\\", "/")
img = QImage(64, 64, QImage.Format_RGB32)
img.fill(0xFF3C7A3C)
img.save(tmp_img)
tmp_mp4 = os.path.abspath("_bg_probe_tmp.mp4").replace("\\", "/")
open(tmp_mp4, "wb").write(b"\x00" * 64)  # 只测路由，解不解得开不归这儿管
# 轮播用的文件夹：三张图 + 一个该被忽略的杂项文件
tmp_dir = os.path.abspath("_bg_probe_dir").replace("\\", "/")
os.makedirs(tmp_dir, exist_ok=True)
dir_files = []
for i, color in enumerate((0xFF804020, 0xFF204080, 0xFF208040)):
    one = QImage(32, 32, QImage.Format_RGB32)
    one.fill(color)
    path = f"{tmp_dir}/wall{i}.png"
    one.save(path)
    dir_files.append(os.path.normpath(path))  # 播放列表回的是 normpath 过的
open(f"{tmp_dir}/readme.txt", "w", encoding="utf-8").write("not a wallpaper")

from app.main_window import MainWindow  # noqa: E402
from app.pcl_chrome import Theme, rgba  # noqa: E402
from app.background import is_video  # noqa: E402

win = MainWindow()
try:
    win.backend.save_settings({"ui_background": "", "ui_sidebar_opacity": 100,
                               "ui_background_blur": 0, "ui_background_dim": 0,
                               "ui_background_folder": ""})
    win.apply_theme()

    # 1) 无壁纸：标记关闭、stacked 纯色、页面不透明、背景层藏着
    check(Theme.background_active is False, "默认无图时 background_active=False")
    check("transparent" not in win.stackedWidget.styleSheet(), "默认 stacked 铺纯色")
    check(not win.stackedWidget.property("isTransparent"), "默认 isTransparent=False")
    check(win._bg_layer.isHidden(), "默认背景层隐藏")
    for key, page in win._pages.items():
        check(surface_ok(page, False), f"无图时页面实底: {key}")

    # 2) 静态图：标记打开、背景层接管、stacked 与页面透明
    win.backend.save_settings({"ui_background": tmp_img})
    win.apply_theme()
    check(Theme.background_active is True, "设图后 background_active=True")
    # stacked 的透明走 Fluent 自己的 StackedWidget[isTransparent=true] 规则，
    # 不是自己 setStyleSheet —— 那份会被 DirtyStyleSheetWatcher 刷回去
    check(bool(win.stackedWidget.property("isTransparent")), "stacked 翻到 isTransparent")
    check("background-color" not in win.stackedWidget.styleSheet(),
          "stacked 自带的实色样式表清掉了")
    check(not win._bg_layer.isHidden(), "背景层显示出来")
    check(win._bg_layer.source() == tmp_img, "背景层拿到图片路径")
    check(win._bg_layer.has_content(), "背景层真读到了图")
    check(not win._bg_layer.error, f"静态图无报错: {win._bg_layer.error}")
    for key, page in win._pages.items():
        check(surface_ok(page, True), f"页面表面透明: {key}")
        # 禁的是「在透明 QSS 底下垫一层**实色**」，不是填充本身：那样壁纸会被
        # 整块盖掉。背景层把页面盖住的那块壁纸裁下来借给它当不透明底（挂
        # pymclLentWallpaper 标记）画出来一模一样，只是让 Qt 知道这块矩形被填
        # 满了、重绘可以停在这层——那一档要放行。普通实色填充仍然一律挡下。
        check(not page.autoFillBackground() or page.property("pymclLentWallpaper"),
              f"页面底下没垫实色: {key}")
    check("transparent" in win.more_section.styleSheet(), "more 分区根透明")
    # 挂了待刷标记的页面，切过去那一刻必须真的补上透明
    win.switchTo("tasks")
    check("transparent" in win.tasks_page.styleSheet(), "待刷页面切过去后补上透明")
    win.switchTo("launch")

    # 3) 侧边栏半透明：QSS 落到 rgba，满值时回退成 #RRGGBB
    check(is_video(tmp_mp4) and not is_video(tmp_img), "按扩展名分流图片/视频")
    check("rgba(" not in win.side.styleSheet(), "100% 时侧栏仍是实色")
    win.backend.save_settings({"ui_sidebar_opacity": 60})
    win.apply_theme()
    check(Theme.sidebar_opacity == 60, "Theme.sidebar_opacity 跟着配置走")
    check("rgba(" in win.side.styleSheet(), "60% 时侧栏 QSS 用 rgba")
    check(rgba("#242424", 60) == "rgba(36, 36, 36, 0.600)", "rgba() 换算正确")
    check(rgba("#242424", 100) == "#242424", "满值不生成 rgba")
    btn = win.side.button("launch")
    check("rgba(" in btn.styleSheet(), "导航按钮高亮底也跟着透")
    check("rgba(" in win.titleBar.styleSheet(), "标题栏跟侧栏同一个不透明度")
    win.backend.save_settings({"ui_sidebar_opacity": 5})
    check(win.backend.get_setting("ui_sidebar_opacity") == 30, "不透明度夹在 30 以上")

    # 4) 可读性处理：模糊 + 遮罩落到背景层，越界值夹回范围内
    win.backend.save_settings({"ui_sidebar_opacity": 60, "ui_background": tmp_img,
                               "ui_background_blur": 18, "ui_background_dim": 45})
    win.apply_theme()
    layer = win._bg_layer
    check((layer._blur, layer._dim) == (18, 45), "模糊/遮罩传到背景层")
    check(layer._dim_color == Theme.bg, "遮罩刷的是主题底色")
    win.backend.save_settings({"ui_background_blur": 999, "ui_background_dim": 999})
    check(win.backend.get_setting("ui_background_blur") == 40, "模糊夹在 40 以内")
    check(win.backend.get_setting("ui_background_dim") == 80, "遮罩夹在 80 以内")
    win.backend.save_settings({"ui_background_blur": 0, "ui_background_dim": 0})
    win.apply_theme()

    # 5) mp4：走视频分支（拿不到帧也不许崩），暂停/恢复可控
    win.backend.save_settings({"ui_background": tmp_mp4})
    win.apply_theme()
    check(Theme.background_active is True, "mp4 也算壁纸生效")
    check(win._bg_layer.source() == tmp_mp4, "背景层拿到视频路径")
    check(win._bg_layer.is_playing_video() or bool(win._bg_layer.error),
          "要么起了播放器，要么明确报错")
    win._bg_layer.set_playing(False)
    win._bg_layer.set_playing(True)
    check(True, "暂停/恢复不抛异常")

    # 6) 撤销：一路退回 mp4 之前的静态图，再退回空
    check(win.backend.can_undo_background(), "有历史可撤销")
    check(win.backend.undo_background()["image"] == tmp_img, "撤销退回上一张静态图")
    win.apply_theme()
    check(win._bg_layer.source() == tmp_img, "撤销后背景层跟着换回来")
    check(win.backend.undo_background()["image"] == "", "再撤销退回纯色")
    win.apply_theme()
    check(Theme.background_active is False, "退回纯色后 background_active=False")

    # 7) 恢复默认：清回纯色，并且这一步本身还能撤销
    win.backend.save_settings({"ui_background": tmp_img})
    check(win.backend.reset_background()["image"] == "", "恢复默认清回纯色")
    check(win.backend.get_setting("ui_background") == "", "落盘也清空了")
    check(win.backend.undo_background()["image"] == tmp_img, "恢复默认这一步可撤销")

    # 8) 文件夹轮播：顺序走一圈、随机不连抽同一张、清文件夹连撤销一起退
    win.backend.save_settings({"ui_background": "", "ui_background_folder": tmp_dir,
                               "ui_background_shuffle": False,
                               "ui_background_interval": 7})
    win.apply_theme()
    check(Theme.background_active is True, "文件夹轮播也算壁纸生效")
    check(win._bg_layer.source() in dir_files, "轮播从文件夹里挑了一张")
    check(win._wall_timer.isActive() and win._wall_timer.interval() == 7 * 60_000,
          "轮播定时器按 7 分钟起来了")
    first = win._bg_layer.source()
    win.next_wallpaper()
    check(win._bg_layer.source() != first, "「下一张」真的换了")
    seen = {first, win._bg_layer.source()}
    for _ in range(len(dir_files) * 2):
        win.next_wallpaper()
        seen.add(win._bg_layer.source())
    check(seen == set(dir_files), f"顺序轮播走遍全部 {len(dir_files)} 张")
    win.backend.save_settings({"ui_background_shuffle": True})
    win.apply_theme()
    picks = []
    for _ in range(12):
        win.next_wallpaper()
        picks.append(win._bg_layer.source())
    check(all(a != b for a, b in zip(picks, picks[1:])), "随机轮播不连抽同一张")
    check(set(picks) <= set(dir_files), "随机抽的也都在文件夹里")
    # 文件夹优先于单图
    win.backend.save_settings({"ui_background": tmp_img})
    win.apply_theme()
    check(win._bg_layer.source() in dir_files, "有文件夹时单图让位")
    # 恢复默认把文件夹一起清掉，撤销能把这一整组退回来
    win.backend.reset_background()
    win.apply_theme()
    check(win.backend.get_setting("ui_background_folder") == "", "恢复默认连文件夹一起清")
    check(Theme.background_active is False, "清完回到纯色")
    back = win.backend.undo_background()
    check(back["folder"] == tmp_dir and back["image"] == tmp_img,
          "撤销把单图和文件夹一起退回来")
    win.backend.save_settings({"ui_background": "", "ui_background_folder": ""})
    win.apply_theme()
    check(not win._wall_timer.isActive(), "清掉文件夹后定时器停了")

    # 7) 坏路径：回退纯色，不崩
    win.backend.save_settings({"ui_background": "Z:/no/such/file.mp4"})
    win.apply_theme()
    check(Theme.background_active is False, "坏路径回退纯色")
    for key, page in win._pages.items():
        check(surface_ok(page, False), f"坏路径时页面恢复实底: {key}")

    # 8) 设置页控件在位且联动
    sp = win.settings_page
    check(hasattr(sp, "bg_pick") and sp.bg_pick.isEnabled(), "设置页有「选择文件」")
    check(hasattr(sp, "bg_undo_btn") and hasattr(sp, "bg_reset_btn"), "设置页有复原按钮")
    check(sp.side_alpha.minimum() == 30 and sp.side_alpha.maximum() == 100,
          "不透明度滑块范围 30–100")
    sp.bg_edit.setText(tmp_img)
    sp._on_bg_committed()
    check(win.backend.get_setting("ui_background") == tmp_img, "_on_bg_committed 落盘")
    check(sp.bg_undo_btn.isEnabled(), "有历史时撤销按钮可点")
    sp._reset_background()
    check(win.backend.get_setting("ui_background") == "", "设置页「恢复默认」清空壁纸")
    sp.refresh_from_config()
    check(sp.bg_edit.text() == "", "refresh_from_config 同步回控件")
finally:
    for f in (tmp_img, tmp_mp4):
        if os.path.isfile(f):
            os.remove(f)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    shutil.rmtree(_probe_home, ignore_errors=True)

print("BG PROBE", "FAILED" if FAILS else "OK", f"({len(FAILS)} failures)")
# 同 _bg_visual.py：判结果看上面那行 BG PROBE，退出码偶尔会被 Qt 拆窗口时的崩溃盖掉。
# 别用 os._exit() / win.close() / 收尾 processEvents() 去修，那三条都会把进程卡死。
sys.exit(1 if FAILS else 0)

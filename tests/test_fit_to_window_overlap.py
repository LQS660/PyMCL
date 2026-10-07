# -*- coding: utf-8 -*-
"""「适应窗口」不许产出重叠版式，且两端对同一份文档给出同一个结果。

`fit_to_window` 逐卡抬到最小尺寸却不动邻居：等比缩放结果比某张卡的最小尺寸
还小时，`max(mw / cw, …)` 把它抬起来，比例位置不变 → 成片重叠。实测默认窗口
1320×840 上排好的 300 份无重叠布局，窗口缩到 1260 再点「适应窗口」23% 变重叠，
缩到 1220 时 100%。而这是持久化操作（`_touch(structural=True)` 立即落盘），
重叠版式会写进 ui_layout，eziapp 打开也是同一份重叠。

这里守四件事：
  1. 抬完必须再分离：任何输入下 fit_to_window 的结果都不重叠；
  2. 画布确实塞不下时**不写重叠**（拒绝并保持原样）；
  3. 卡片本体下限含标题栏 40px，与 eziapp `cardMinPx` 同口径；
  4. 两端（Qt `_card_min_px` vs eziapp `CARD_MIN_SIZE + HEADER_PX`）数值一致。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect  # noqa: E402

from app import dashboard  # noqa: E402
from app.dashboard import (  # noqa: E402
    HEADER_PX, _card_min_px, _clamp_rect, _rects_valid, _separate_rects,
)
from mclauncher import ui_layout as lm  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EZ = ROOT / "eziapp" / "src" / "layout_geom.ts"
TOL = 2


def _overlap_count(rects: list[QRect]) -> int:
    n = 0
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            ox = min(a.x() + a.width(), b.x() + b.width()) - max(a.x(), b.x())
            oy = min(a.y() + a.height(), b.y() + b.height()) - max(a.y(), b.y())
            if ox > TOL and oy > TOL:
                n += 1
    return n


def _layout_pool(n: int = 60) -> list[lm.LayoutDoc]:
    """一批在默认画布上互不重叠的布局（findFreeSpot 同款步进扫描构造）。"""
    import random

    rng = random.Random(20260911)
    types = list(lm.CARD_MIN_SIZE)
    out: list[lm.LayoutDoc] = []
    cw, ch = 1080, 692
    for _ in range(n):
        doc = lm.LayoutDoc(grid=8)
        rects: list[QRect] = []
        for i in range(2 + rng.randrange(5)):
            t = rng.choice(types)
            mw, mh = _card_min_px(t)
            w = max(mw, int(cw * (0.12 + rng.random() * 0.35)))
            h = max(mh, int(ch * (0.12 + rng.random() * 0.35)))
            spot = None
            for yy in range(8, max(9, ch - h - 8), 24):
                for xx in range(8, max(9, cw - w - 8), 24):
                    cand = QRect(xx, yy, w, h)
                    if not any(cand.intersects(o.adjusted(-8, -8, 8, 8)) for o in rects):
                        spot = cand
                        break
                if spot is not None:
                    break
            if spot is None:
                continue
            rects.append(spot)
            item = lm.LayoutItem(t, 0, 0, 0.1, 0.1, item_id=f"{t}-{i}")
            item.set_geometry_px(spot.x(), spot.y(), spot.width(), spot.height(), (cw, ch))
            doc.items.append(item)
        if len(doc.items) >= 2 and _overlap_count(rects) == 0:
            out.append(doc)
    return out


def _fit(doc: lm.LayoutDoc, cw: int, ch: int) -> tuple[bool, list[QRect]]:
    """跑一次 `DashboardCanvas.fit_to_window` 的几何核心（模块级 `_fit_rects`）。

    只调画布的纯几何部分：`_rebuild` / `_touch` 要真窗口与宿主页，而缺陷就在
    这段几何里。返回 (是否落盘, 结果矩形)。
    """
    vis = doc.visible_items()
    if not vis:
        return True, []
    rects = dashboard._fit_rects(vis, cw, ch)
    if rects is None:
        return False, []
    return True, rects


class FitToWindowOverlapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = _layout_pool()
        assert len(cls.pool) >= 20, f"样本太少：{len(cls.pool)}"

    def test_no_overlap_at_default_and_narrow_canvas(self):
        """缺陷区间：画布宽 ≤ 1040（窗口 ≤ 1280）时旧算法开始重叠。"""
        for cw, ch in ((1080, 692), (1040, 667), (1020, 654), (1000, 641),
                       (980, 628), (940, 612), (740, 560)):
            bad = 0
            for doc in self.pool:
                ok, rects = _fit(doc, cw, ch)
                if ok and _overlap_count(rects) > 0:
                    bad += 1
            self.assertEqual(0, bad, f"画布 {cw}×{ch} 上 {bad}/{len(self.pool)} 份布局重叠")

    def test_refusal_never_writes_overlap(self):
        """塞不下时返回 False（调用方保持原样），绝不写重叠。"""
        for cw, ch in ((660, 456), (500, 412), (400, 340)):
            for doc in self.pool:
                ok, rects = _fit(doc, cw, ch)
                if ok:
                    self.assertEqual(0, _overlap_count(rects),
                                     f"画布 {cw}×{ch} 声称成功却重叠")

    def test_separator_unit(self):
        r = [QRect(0, 0, 200, 200), QRect(100, 100, 200, 200)]
        self.assertTrue(_separate_rects(r, [(100, 100)] * 2, 400, 400))
        self.assertEqual(0, _overlap_count(r))
        # 两张满画布：推不开，必须报 False 而不是硬塞
        r = [QRect(0, 0, 400, 400), QRect(0, 0, 400, 400)]
        self.assertFalse(_separate_rects(r, [(100, 100)] * 2, 400, 400))


class MinSizeParityTests(unittest.TestCase):
    def test_card_min_px_includes_header(self):
        for t, (mw, mh) in lm.CARD_MIN_SIZE.items():
            self.assertEqual((mw, mh + HEADER_PX), _card_min_px(t), t)
        self.assertEqual((200, 120 + HEADER_PX), _card_min_px("__unknown__"))

    def test_header_px_matches_eziapp(self):
        src = EZ.read_text(encoding="utf-8")
        m = re.search(r"export const HEADER_PX = (\d+)", src)
        self.assertIsNotNone(m, "eziapp 里找不到 HEADER_PX")
        self.assertEqual(HEADER_PX, int(m.group(1)),
                         "两端标题栏高度不一致，同一份文档缩放下限会差这么多")

    def test_card_min_table_matches_eziapp(self):
        """CARD_MIN_SIZE 数值表两端必须逐项一致（文档互读）。"""
        src = EZ.read_text(encoding="utf-8")
        block = src.split("export const CARD_MIN_SIZE", 1)[1].split("};", 1)[0]
        got = {k: (int(a), int(b))
               for k, a, b in re.findall(r"(\w+):\s*\[(\d+),\s*(\d+)\]", block)}
        self.assertEqual({k: tuple(v) for k, v in lm.CARD_MIN_SIZE.items()}, got)


class EziappFitParityTests(unittest.TestCase):
    """两端对同一份文档的适应结果一致（跑真 TS，不是复刻）。"""

    @classmethod
    def setUpClass(cls):
        cls.pool = _layout_pool()

    def test_eziapp_refuses_and_agrees(self):
        node = _node()
        if node is None:
            self.skipTest("没有 node，跳过跨端比对")
        cases = []
        for doc in self.pool[:12]:
            cases.append({"grid": doc.grid, "items": [
                {"id": it.id, "type": it.type, "x": it.x, "y": it.y, "w": it.w, "h": it.h}
                for it in doc.items
            ]})
        sizes = [[1080, 692], [1000, 641], [740, 560], [500, 412]]
        script = _EZ_SCRIPT.replace("__CASES__", json.dumps(cases)).replace(
            "__SIZES__", json.dumps(sizes))
        r = subprocess.run([node, "--input-type=module", "-e", script],
                           capture_output=True, text=True, cwd=str(ROOT / "eziapp"),
                           timeout=120)
        self.assertEqual(0, r.returncode, r.stderr[-2000:])
        data = json.loads(r.stdout.strip().splitlines()[-1])
        # 像素级比对只在产品可达的画布上做（最小窗口 980×650 → 画布约 740×560）。
        # 更小的画布两边都只能把卡片压到画布本身那么大，取整差异会被放大到几十
        # 像素——那种尺寸下"版式"已经没有意义，只要求两端同样拒绝/同样不重叠。
        parity_min_w = 740
        for row in data:
            cw, ch = row["cw"], row["ch"]
            doc = self.pool[row["idx"]]
            ok, rects = _fit(doc, cw, ch)
            self.assertEqual(ok, row["ok"],
                             f"idx={row['idx']} 画布 {cw}×{ch}：Qt 落盘={ok} eziapp={row['ok']}")
            if not ok:
                continue
            # 两端都要无重叠
            self.assertEqual(0, _overlap_count(rects), f"Qt 侧重叠 idx={row['idx']}")
            if cw < parity_min_w:
                continue
            for qt_r, js_r in zip(rects, row["rects"]):
                for a, b in ((qt_r.x(), js_r["x"]), (qt_r.y(), js_r["y"]),
                             (qt_r.width(), js_r["w"]), (qt_r.height(), js_r["h"])):
                    self.assertLessEqual(abs(a - b), 3,
                                         f"idx={row['idx']} {cw}×{ch} Qt={a} eziapp={b}")


def _node() -> str | None:
    import shutil
    return shutil.which("node")


_EZ_SCRIPT = r"""
import { fitToWindow } from './src/layout_geom.ts';
const cases = __CASES__;
const sizes = __SIZES__;
const out = [];
cases.forEach((c, idx) => {
  for (const [cw, ch] of sizes) {
    const doc = { version: 1, grid: c.grid, items: c.items.map((it) => ({ ...it, z: 0, hidden: false, settings: {} })) };
    const ok = fitToWindow(doc, cw, ch);
    out.push({ idx, cw, ch, ok, rects: doc.items.map((it) => ({
      x: Math.round(it.x * cw), y: Math.round(it.y * ch),
      w: Math.max(1, Math.round(it.w * cw)), h: Math.max(1, Math.round(it.h * ch)),
    })) });
  }
});
console.log(JSON.stringify(out));
"""


if __name__ == "__main__":
    unittest.main()

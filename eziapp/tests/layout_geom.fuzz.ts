/**
 * 启动页画布几何层的随机拖拽模糊测试（对齐 Qt 侧 _resize_fuzz.py / _resize_link_smoke.py 的思路）。
 *
 * 画布交互里最容易回归的是「拖着拖着卡片叠上了」——这类 bug 只在某条特定的
 * 拖动路径上出现，靠手点碰不到。这里不起浏览器，直接对 src/layout_geom.ts 的
 * 纯几何函数灌随机操作，每一步都查三条不变量：
 *
 *   1. 任何卡片都不出画布；
 *   2. 任何卡片都不小于自己的最小尺寸；
 *   3. 联动缩放不产生**新的**重叠（整卡拖动允许叠放，与 Qt 一致，故只对缩放查）。
 *
 * 跑法（Node 22+ 直接吃 TS）：
 *   node eziapp/tests/layout_geom.fuzz.ts [seed] [iterations]
 */

import {
  CARD_MIN_SIZE, DIRS, type CardGeom, type Dir, type LayoutDoc, type Rect,
  cardMinPx, defaultDoc, dragTo, findFreeSpot, fitToWindow, linkFollowers,
  newItem, placeAll, resizeBy, resizeLinked, setGeometryPx, visibleItems,
} from '../src/layout_geom.ts';

// 贴边/取整允许的误差：resizeBy 走 Math.round，联动那侧也有一次取整
const TOL = 2;
const GRIDS = [0, 4, 8, 16, 24];
const SIZES: [number, number][] = [[1400, 900], [1280, 820], [1180, 760], [1600, 1000]];
const ALL_TYPES = Object.keys(CARD_MIN_SIZE);

interface Card { id: string; type: string; rect: Rect; min: [number, number] }

const failures: string[] = [];
let checks = 0;
/** 第一条失败时把整盘状态打出来，光看一行报错没法复盘是谁把谁挤了。 */
let scene: (() => string) | null = null;

function fail(msg: string) {
  failures.push(msg);
  if (failures.length === 1 && scene) console.error(`  现场：\n${scene()}`);
  if (failures.length <= 8) console.error(`  ✗ ${msg}`);
}
function check(cond: boolean, msg: string) {
  checks++;
  if (!cond) fail(msg);
}
const fmt = (r: Rect) => `(${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.w)}×${Math.round(r.h)})`;

/** 固定种子的 PRNG：挂了能用同一个 seed 原样重放。 */
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ----------------------------------------------------------------------
// 不变量
// ----------------------------------------------------------------------
function overlapArea(a: Rect, b: Rect): [number, number] {
  return [
    Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x),
    Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y),
  ];
}
/** 当前重叠到的卡片对（超过 TOL 才算，贴边取整不算）。 */
function overlapPairs(cards: Card[]): Set<string> {
  const out = new Set<string>();
  for (let i = 0; i < cards.length; i++) {
    for (let j = i + 1; j < cards.length; j++) {
      const [ox, oy] = overlapArea(cards[i].rect, cards[j].rect);
      if (ox > TOL && oy > TOL) out.add(`${cards[i].id}|${cards[j].id}`);
    }
  }
  return out;
}
function checkBoundsAndMin(cards: Card[], cw: number, ch: number, where: string) {
  for (const c of cards) {
    const r = c.rect;
    check(r.x >= -TOL && r.y >= -TOL && r.x + r.w <= cw + TOL && r.y + r.h <= ch + TOL,
      `${where}: ${c.id} 出画布 ${fmt(r)} 画布 ${cw}×${ch}`);
    // 画布本身比卡片最小尺寸还小的时候，卡片只能缩到画布那么大
    check(r.w >= Math.min(c.min[0], cw) - TOL && r.h >= Math.min(c.min[1], ch) - TOL,
      `${where}: ${c.id} 低于最小尺寸 ${fmt(r)} < ${c.min[0]}×${c.min[1]}`);
  }
}

// ----------------------------------------------------------------------
// 场景构造
// ----------------------------------------------------------------------
function cardsFromDoc(doc: LayoutDoc, cw: number, ch: number): Card[] {
  const items = visibleItems(doc);
  const placed = placeAll(items, cw, ch);
  return items.map((it) => ({
    id: it.id, type: it.type, rect: placed.get(it.id)!, min: cardMinPx(it.type),
  }));
}

/**
 * 一半用内置默认布局（四卡贴合，最容易触发联动），一半用随机摆开的 3~7 张卡。
 * 随机那批落点走 findFreeSpot：构造上就不重叠，而它 8px 的外扩留出的缝正好
 * 落在 LINK_GAP_MAX 里，联动分支照样吃得到。
 */
function makeLayout(rng: () => number, cw: number, ch: number): Card[] {
  if (rng() < 0.5) return cardsFromDoc(defaultDoc(), cw, ch);
  const cards: Card[] = [];
  const want = 3 + Math.floor(rng() * 5);
  for (let i = 0; i < want; i++) {
    const type = ALL_TYPES[Math.floor(rng() * ALL_TYPES.length)];
    const spot = findFreeSpot(type, 0.14 + rng() * 0.3, 0.14 + rng() * 0.32, cw, ch, cards.map((c) => c.rect));
    const clash = cards.some((c) => {
      const [ox, oy] = overlapArea(spot, c.rect);
      return ox > TOL && oy > TOL;
    });
    if (clash) continue; // 画布塞满了，findFreeSpot 退回左上角，这张不要
    cards.push({ id: `${type}-${i}`, type, rect: spot, min: cardMinPx(type) });
  }
  return cards.length >= 2 ? cards : cardsFromDoc(defaultDoc(), cw, ch);
}

const geom = (c: Card): CardGeom => ({ id: c.id, rect: { ...c.rect }, min: c.min });

/** 完整走一次手柄手势：锁定跟随者 → 逐帧 resizeBy + resizeLinked → 松手写回。 */
function doResize(cards: Card[], card: Card, dir: Dir, dx: number, dy: number,
                  grid: number, cw: number, ch: number) {
  const start: Rect = { ...card.rect };
  const me: CardGeom = { id: card.id, rect: start, min: card.min };
  const others = cards.filter((c) => c !== card);
  const F = linkFollowers(me, others.map(geom));
  const byId = new Map(others.map((c) => [c.id, c]));
  // 手势里有好几帧，逐帧推进（跟真实指针一样，中间帧也要满足不变量）
  const steps = 4;
  for (let s = 1; s <= steps; s++) {
    const want = resizeBy(dir, start, (dx * s) / steps, (dy * s) / steps, card.min, grid, cw, ch);
    const res = resizeLinked(me, others.map(geom), dir, want, F, cw, ch);
    card.rect = res.active;
    res.moved.forEach((r, id) => {
      const c = byId.get(id);
      if (c) c.rect = r;
    });
  }
}

// ----------------------------------------------------------------------
// 1. 随机缩放：三条不变量
// ----------------------------------------------------------------------
function fuzzResize(rng: () => number, rounds: number) {
  let ops = 0;
  for (let round = 0; round < rounds; round++) {
    const [cw, ch] = SIZES[Math.floor(rng() * SIZES.length)];
    const grid = GRIDS[Math.floor(rng() * GRIDS.length)];
    const cards = makeLayout(rng, cw, ch);
    const shot = () => cards.map((c) => `${c.id} ${fmt(c.rect)} min ${c.min[0]}×${c.min[1]}`).join('  ');
    let before = shot();
    let op = '（起手）';
    scene = () => `    画布 ${cw}×${ch} grid=${grid}\n    动作前 ${before}\n    动作   ${op}\n    动作后 ${shot()}`;
    const seen = overlapPairs(cards);
    check(seen.size === 0, `起手布局就重叠了：${[...seen].join(' ')}（${cw}×${ch}）`);
    checkBoundsAndMin(cards, cw, ch, '起手');
    for (let i = 0; i < 30; i++) {
      const card = cards[Math.floor(rng() * cards.length)];
      const dir = DIRS[Math.floor(rng() * DIRS.length)];
      const dx = Math.round((rng() * 2 - 1) * 460);
      const dy = Math.round((rng() * 2 - 1) * 340);
      before = shot();
      op = `${card.id}.${dir} (${dx},${dy})`;
      doResize(cards, card, dir, dx, dy, grid, cw, ch);
      ops++;
      checkBoundsAndMin(cards, cw, ch, `缩放 ${card.id}.${dir} (${dx},${dy})`);
      const now = overlapPairs(cards);
      for (const pair of now) {
        if (!seen.has(pair)) {
          fail(`缩放 ${card.id}.${dir} (${dx},${dy}) grid=${grid} ${cw}×${ch} 产生新重叠：${pair}`);
          seen.add(pair); // 同一对只报一次，后面的操作继续查别的
        }
      }
    }
  }
  console.log(`  随机缩放 ${ops} 次`);
}

// ----------------------------------------------------------------------
// 2. 随机整卡拖动：不出画布、尺寸不变（叠放是允许的，与 Qt 一致）
// ----------------------------------------------------------------------
function fuzzDrag(rng: () => number, rounds: number) {
  let ops = 0;
  for (let round = 0; round < rounds; round++) {
    const [cw, ch] = SIZES[Math.floor(rng() * SIZES.length)];
    const grid = GRIDS[Math.floor(rng() * GRIDS.length)];
    const cards = makeLayout(rng, cw, ch);
    for (let i = 0; i < 30; i++) {
      const card = cards[Math.floor(rng() * cards.length)];
      const before = { ...card.rect };
      const tx = Math.round((rng() * 2 - 1) * cw * 1.2);
      const ty = Math.round((rng() * 2 - 1) * ch * 1.2);
      card.rect = dragTo(card.rect, tx, ty, grid, cw, ch);
      ops++;
      check(card.rect.w === before.w && card.rect.h === before.h,
        `拖动改了尺寸：${fmt(before)} → ${fmt(card.rect)}`);
      checkBoundsAndMin(cards, cw, ch, `拖动 ${card.id} → (${tx},${ty})`);
      // 落盘再读回（比例坐标往返）不该把卡片挪出画布
      const item = newItem(card.type, 0, 0, 0.1, 0.1);
      setGeometryPx(item, card.rect, cw, ch);
      const back = placeAll([item], cw, ch).get(item.id)!;
      check(Math.abs(back.x - card.rect.x) <= TOL && Math.abs(back.y - card.rect.y) <= TOL
        && Math.abs(back.w - card.rect.w) <= TOL && Math.abs(back.h - card.rect.h) <= TOL,
        `比例坐标往返失真：${fmt(card.rect)} → ${fmt(back)}`);
    }
  }
  console.log(`  随机拖动 ${ops} 次`);
}

// ----------------------------------------------------------------------
// 3. 适应窗口：铺满但不出界、不低于最小尺寸
// ----------------------------------------------------------------------
function fuzzFit(rng: () => number, rounds: number) {
  for (let round = 0; round < rounds; round++) {
    const [cw, ch] = SIZES[Math.floor(rng() * SIZES.length)];
    const doc = defaultDoc();
    for (const it of doc.items) {
      it.x = rng() * 0.6;
      it.y = rng() * 0.6;
      it.w = 0.12 + rng() * 0.3;
      it.h = 0.12 + rng() * 0.3;
    }
    fitToWindow(doc, cw, ch);
    const cards = cardsFromDoc(doc, cw, ch);
    checkBoundsAndMin(cards, cw, ch, '适应窗口');
  }
  console.log(`  适应窗口 ${rounds} 次`);
}

// ----------------------------------------------------------------------
// 4. 定点联动场景：与 Qt 侧 _resize_link_smoke.py 逐条对齐
// ----------------------------------------------------------------------
function near(a: number, b: number, tol = 3) { return Math.abs(a - b) <= tol; }

function scenarios() {
  const cw = 900;
  const ch = 600;
  const mk = (id: string, x: number, y: number, w: number, h: number, min: [number, number] = [180, 170]): Card =>
    ({ id, type: 'notes', rect: { x, y, w, h }, min });

  // 左 1/3 + 右 2/3 共享一条竖边：左卡拉宽，右卡让位
  let left = mk('left', 0, 0, 300, 600);
  let right = mk('right', 300, 0, 600, 600);
  let cards = [left, right];
  doResize(cards, left, 'e', 300, 0, 0, cw, ch);
  check(near(right.rect.x, 600) && near(right.rect.w, 300),
    `联动.右卡让位 right=${fmt(right.rect)}`);
  check(near(left.rect.w, 600), `联动.左卡变宽 left=${fmt(left.rect)}`);

  // 反向拖回：右卡补位
  doResize(cards, left, 'e', -375, 0, 0, cw, ch);
  check(near(right.rect.x, 225) && near(right.rect.w, 675),
    `联动.右卡补位 right=${fmt(right.rect)}`);

  // 邻居最小宽度保护：右卡最小 500，左卡最多推到 400
  left = mk('left', 0, 0, 300, 600);
  right = mk('right', 300, 0, 600, 600, [500, 170]);
  cards = [left, right];
  doResize(cards, left, 'e', 450, 0, 0, cw, ch);
  check(near(left.rect.x + left.rect.w, 400) && near(right.rect.x, 400),
    `联动.邻居最小宽 edge=${left.rect.x + left.rect.w} right=${fmt(right.rect)}`);

  // 不贴边的远卡不参与联动
  const solo = mk('solo', 90, 60, 270, 180);
  const far = mk('far', 630, 420, 225, 150);
  cards = [solo, far];
  doResize(cards, solo, 'e', 120, 0, 0, cw, ch);
  check(near(solo.rect.w, 390) && near(far.rect.x, 630),
    `联动.远卡不动 solo=${fmt(solo.rect)} far=${fmt(far.rect)}`);

  // 带缝（默认布局那种栏间缝）：缝宽保持，右缘顶到画布边
  left = mk('left', 0, 0, 288, 600);
  right = mk('right', 306, 0, 594, 600);
  cards = [left, right];
  const gap = right.rect.x - (left.rect.x + left.rect.w);
  doResize(cards, left, 'e', 90, 0, 0, cw, ch);
  check(near(right.rect.x - (left.rect.x + left.rect.w), gap)
    && near(right.rect.x + right.rect.w, 900),
    `联动.保持原缝 gap=${gap} now=${right.rect.x - (left.rect.x + left.rect.w)} right=${fmt(right.rect)}`);

  // 纵向：上卡变高，下卡让位
  const top = mk('top', 0, 0, 900, 180);
  const bottom = mk('bottom', 0, 180, 900, 420);
  cards = [top, bottom];
  doResize(cards, top, 's', 0, 60, 0, cw, ch);
  check(near(bottom.rect.y, 240) && near(bottom.rect.h, 360),
    `联动.下卡让位 bottom=${fmt(bottom.rect)}`);

  console.log('  定点联动场景 7 条');
}

// ----------------------------------------------------------------------
const seed = Number(process.argv[2]) || 20260911;
const rounds = Number(process.argv[3]) || 120;
const rng = mulberry32(seed);

console.log(`layout_geom 模糊测试  seed=${seed} rounds=${rounds}`);
scenarios();
fuzzResize(rng, rounds);
fuzzDrag(rng, rounds);
fuzzFit(rng, rounds);

console.log(`\n断言 ${checks} 条，失败 ${failures.length} 条`);
if (failures.length) {
  if (failures.length > 8) console.error(`  …另有 ${failures.length - 8} 条失败未列出`);
  console.error(`FAILED（复现：node eziapp/tests/layout_geom.fuzz.ts ${seed} ${rounds}）`);
  process.exit(1);
}
console.log('ALL PASS');

/**
 * 启动页自定义布局：数据模型 + 纯几何逻辑（不碰 DOM）。
 *
 * 与 Python 侧 mclauncher/ui_layout.py（Qt 版 app/dashboard.py 也用它）逐条对齐：
 * 文档格式、比例坐标、吸附、八向缩放、邻卡联动、找空位、适应窗口。
 * 这一层独立出来是为了能在 node 里跑随机拖拽模糊测试，不必起浏览器。
 */

export const LAYOUT_VERSION = 1;
export const GRID_CHOICES = [0, 4, 8, 16, 24];
export const DEFAULT_PROFILE = '';

/** 每种卡片的最小尺寸（像素，正文部分；卡片本体再加标题栏 40px）。 */
export const CARD_MIN_SIZE: Record<string, [number, number]> = {
  // 横幅 150→125，与 Python 侧 mclauncher/ui_layout.py 对齐：横幅里已经没有
  // 启动按钮/进度条了，只剩渐变 Hero（量出来最矮 148）；留 150 的话矮窗口下
  // 150+40 的下限会顶过比例高度，把下面那张卡压掉一截。两端不一起改，同一份
  // 布局文档在两边缩放的下限就不一样了。
  banner: [340, 125],
  config: [330, 300],
  log: [260, 180],
  news: [220, 180],
  quick: [220, 150],
  notes: [180, 130],
  playtime: [220, 130],
  tasks: [220, 130],
  skin: [160, 200],
};
export const FALLBACK_MIN: [number, number] = [200, 120];
/** 标题栏高度：卡片本体最小高 = 正文最小高 + 它（对齐 Qt DashboardCard.setMinimumSize）。 */
export const HEADER_PX = 40;

/** 新增卡片时各类型的默认几何（画布比例）。 */
// 跟 Qt 版 app/dashboard.py 的 _ADD_DEFAULT 一字不差：两端读的是同一份布局文档，
// 新卡默认落点不一致就是「Qt 加的卡在网页版压着横幅」这类以后很难查的 bug。
export const ADD_DEFAULT: Record<string, [number, number, number, number]> = {
  banner: [0.0, 0.0, 1.0, 0.24],
  config: [0.0, 0.32, 0.34, 0.66],
  log: [0.36, 0.32, 0.4, 0.66],
  // 新闻这一栏矮一截（0.66→0.52）：它是右下角唯一会跟启动坞抢地方的卡，
  // 坞就浮在那个角上。停在坞上沿之前收住，加回来的新闻卡才不被压着。
  news: [0.78, 0.32, 0.22, 0.52],
  quick: [0.32, 0.32, 0.34, 0.3],
  notes: [0.32, 0.34, 0.28, 0.26],
  playtime: [0.32, 0.36, 0.32, 0.22],
  tasks: [0.32, 0.36, 0.32, 0.22],
  skin: [0.4, 0.3, 0.18, 0.4],
};

export interface Rect { x: number; y: number; w: number; h: number }
export type Dir = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';
export const DIRS: Dir[] = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'];

export interface LayoutItem {
  id: string;
  type: string;
  x: number; y: number; w: number; h: number;
  z: number;
  hidden: boolean;
  settings: Record<string, unknown>;
}

export interface LayoutDoc {
  version: number;
  grid: number;
  items: LayoutItem[];
}

export function minSizeFor(type: string): [number, number] {
  return CARD_MIN_SIZE[type] || FALLBACK_MIN;
}

/** 卡片本体（含标题栏）的最小尺寸。 */
export function cardMinPx(type: string): [number, number] {
  const [mw, mh] = minSizeFor(type);
  return [mw, mh + HEADER_PX];
}

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);
const num = (v: unknown, fallback: number) => {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
};

let idSeq = 0;
export function newItem(type: string, x: number, y: number, w: number, h: number,
                        opts: Partial<Pick<LayoutItem, 'id' | 'z' | 'hidden' | 'settings'>> = {}): LayoutItem {
  return {
    id: opts.id || `${type}-${(Date.now() + (idSeq++)) % 100000000}`,
    type: String(type),
    x: clamp01(x), y: clamp01(y),
    w: Math.max(0.04, Math.min(1, w)), h: Math.max(0.04, Math.min(1, h)),
    z: Math.trunc(opts.z || 0),
    hidden: !!opts.hidden,
    settings: { ...(opts.settings || {}) },
  };
}

export function itemFromDict(raw: unknown): LayoutItem {
  const d = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  return newItem(
    String(d.type || 'notes'),
    num(d.x, 0), num(d.y, 0), num(d.w, 0.3) || 0.3, num(d.h, 0.3) || 0.3,
    {
      id: String(d.id || ''), z: num(d.z, 0), hidden: !!d.hidden,
      settings: (d.settings && typeof d.settings === 'object' ? d.settings : {}) as Record<string, unknown>,
    },
  );
}

/**
 * 出厂布局，跟 Qt 版 mclauncher/ui_layout.py 的 default_doc() 一致：横幅通栏 + 左侧
 * 启动配置，其余留空。实时日志和新闻不在出厂版式里，想要的人在「编辑布局 →
 * 添加卡片」里加回来（两种类型仍在 CARD_MIN_SIZE 白名单内）。空出来的右半边留给
 * 启动页右下角的启动坞，那块空着坞才一张卡都不压。
 *
 * 横幅 0.30 而不是 0.26：0.26 在矮窗口里换算出来比横幅卡的最小高（165）还小，
 * 会被下限顶出去、压住下面那张卡。
 */
export function defaultDoc(): LayoutDoc {
  return {
    version: LAYOUT_VERSION,
    grid: 8,
    items: [
      newItem('banner', 0.0, 0.0, 1.0, 0.30, { id: 'banner-main', z: 0 }),
      newItem('config', 0.0, 0.315, 0.315, 0.685, { id: 'config-main', z: 1 }),
    ],
  };
}

/** 宽松解析（读配置用）：结构不对 / 没有卡片 → 默认布局。 */
export function docFromDict(raw: unknown): LayoutDoc {
  if (!raw || typeof raw !== 'object') return defaultDoc();
  const d = raw as Record<string, unknown>;
  const grid = Math.max(0, Math.trunc(num(d.grid, 8)));
  const items = Array.isArray(d.items)
    ? d.items.filter((r) => r && typeof r === 'object').map(itemFromDict)
    : [];
  if (!items.length) return defaultDoc();
  const doc = { version: LAYOUT_VERSION, grid, items };
  normalize(doc);
  return doc;
}

/** 严格解析（导入文件用）：结构不对返回 null；未知卡片类型丢弃。 */
export function parseImportedDoc(raw: unknown): LayoutDoc | null {
  if (!raw || typeof raw !== 'object') return null;
  const d = raw as Record<string, unknown>;
  if (!Array.isArray(d.items) || !d.items.length) return null;
  const doc = docFromDict(d);
  doc.items = doc.items.filter((it) => it.type in CARD_MIN_SIZE);
  return doc.items.length ? doc : null;
}

/** 修 id 重复 / z 序空洞；每次落盘前调用。 */
export function normalize(doc: LayoutDoc): LayoutDoc {
  const seen = new Set<string>();
  doc.items.forEach((it, i) => {
    const base = it.id || `${it.type}-${i}`;
    let nid = base;
    let n = 2;
    while (seen.has(nid)) nid = `${base}-${n++}`;
    it.id = nid;
    seen.add(nid);
  });
  [...doc.items].sort((a, b) => a.z - b.z).forEach((it, z) => { it.z = z; });
  return doc;
}

export function toDict(doc: LayoutDoc): LayoutDoc {
  normalize(doc);
  return {
    version: LAYOUT_VERSION,
    grid: doc.grid,
    items: doc.items.map((it) => ({
      id: it.id, type: it.type,
      x: round5(it.x), y: round5(it.y), w: round5(it.w), h: round5(it.h),
      z: it.z, hidden: it.hidden, settings: it.settings,
    })),
  };
}
const round5 = (v: number) => Math.round(v * 100000) / 100000;

export function cloneDoc(doc: LayoutDoc): LayoutDoc {
  return docFromDict(JSON.parse(JSON.stringify(toDict(doc))));
}

export function nextZ(doc: LayoutDoc): number {
  return doc.items.reduce((m, it) => Math.max(m, it.z), -1) + 1;
}

export function visibleItems(doc: LayoutDoc): LayoutItem[] {
  return [...doc.items].sort((a, b) => a.z - b.z).filter((it) => !it.hidden);
}

// ----------------------------------------------------------------------
// 比例 ↔ 像素
// ----------------------------------------------------------------------
export function geometryPx(item: LayoutItem, cw: number, ch: number): Rect {
  return {
    x: Math.round(item.x * cw),
    y: Math.round(item.y * ch),
    w: Math.max(1, Math.round(item.w * cw)),
    h: Math.max(1, Math.round(item.h * ch)),
  };
}

export function setGeometryPx(item: LayoutItem, r: Rect, cw: number, ch: number) {
  cw = Math.max(1, cw);
  ch = Math.max(1, ch);
  const w = Math.max(1, Math.min(r.w, cw));
  const h = Math.max(1, Math.min(r.h, ch));
  const x = Math.max(0, Math.min(r.x, cw - w));
  const y = Math.max(0, Math.min(r.y, ch - h));
  item.x = clamp01(x / cw);
  item.y = clamp01(y / ch);
  item.w = Math.max(0.01, Math.min(1, w / cw));
  item.h = Math.max(0.01, Math.min(1, h / ch));
}

/** 构建后 / 画布尺寸变化时：按文档比例算出每张卡的像素几何，卡住最小值、贴边不越界。 */
export function placeAll(items: LayoutItem[], cw: number, ch: number): Map<string, Rect> {
  cw = Math.max(1, cw);
  ch = Math.max(1, ch);
  const out = new Map<string, Rect>();
  for (const it of items) {
    const [mw, mh] = cardMinPx(it.type);
    const g = geometryPx(it, cw, ch);
    const w = Math.max(g.w, mw);
    const h = Math.max(g.h, mh);
    out.set(it.id, {
      x: Math.max(0, Math.min(g.x, Math.max(0, cw - w))),
      y: Math.max(0, Math.min(g.y, Math.max(0, ch - h))),
      w, h,
    });
  }
  return out;
}

// ----------------------------------------------------------------------
// 交互几何
// ----------------------------------------------------------------------
export function snap(v: number, grid: number): number {
  return grid > 0 ? Math.round(v / grid) * grid : v;
}

/** 整卡拖动：目标左上角吸附后钳在画布内。 */
export function dragTo(size: Rect, x: number, y: number, grid: number, cw: number, ch: number): Rect {
  const sx = snap(x, grid);
  const sy = snap(y, grid);
  return {
    x: Math.max(0, Math.min(sx, cw - size.w)),
    y: Math.max(0, Math.min(sy, ch - size.h)),
    w: size.w, h: size.h,
  };
}

/**
 * 单卡缩放：从手势起点矩形 + 鼠标位移算出想要的新矩形（未联动）。
 * 对齐 Qt DashboardCard._resize_by 前半段：拖哪条边就钳哪条边，向下/右
 * 扩到画布底时缩尺寸，不让锚定的顶/左边被悄悄推走。
 */
export function resizeBy(dir: Dir, start: Rect, dx: number, dy: number,
                         min: [number, number], grid: number, cw: number, ch: number): Rect {
  const [mw, mh] = min;
  const { x: x0, y: y0, w: w0, h: h0 } = start;
  let x = x0, y = y0, w = w0, h = h0;
  if (dir.includes('e')) w = snap(w0 + dx, grid);
  if (dir.includes('s')) h = snap(h0 + dy, grid);
  if (dir.includes('w')) w = snap(w0 - dx, grid);
  if (dir.includes('n')) h = snap(h0 - dy, grid);
  w = Math.max(mw, Math.min(w, cw));
  h = Math.max(mh, Math.min(h, ch));
  if (dir.includes('w')) x = x0 + (w0 - w);
  if (dir.includes('n')) y = y0 + (h0 - h);
  if (dir.includes('e') && x + w > cw) w = Math.max(mw, cw - x);
  if (dir.includes('w') && x < 0) { x = 0; w = Math.max(mw, x0 + w0); }
  if (dir.includes('s') && y + h > ch) h = Math.max(mh, ch - y);
  if (dir.includes('n') && y < 0) { y = 0; h = Math.max(mh, y0 + h0); }
  x = Math.max(0, Math.min(x, cw - w));
  y = Math.max(0, Math.min(y, ch - h));
  return { x, y, w, h };
}

/** 联动参与者：卡片 id、当前矩形、本体最小尺寸。 */
export interface CardGeom { id: string; rect: Rect; min: [number, number] }

interface Follower { id: string; gap: number; anchor: number; r0: Rect; min: [number, number] }
export interface Followers { e: Follower[]; w: Follower[]; s: Follower[]; n: Follower[] }

// 判定“贴着被拖边”的缝隙范围（px）：0=贴边，负=略有重叠；上限覆盖默认布局 12px 的栏间缝。
export const LINK_GAP_MAX = 28;
export const LINK_OVERLAP_MAX = 8;

const ovV = (a: Rect, b: Rect) => a.y < b.y + b.h && a.y + a.h > b.y; // 纵向有重叠段（左右关系）
const ovH = (a: Rect, b: Rect) => a.x < b.x + b.w && a.x + a.w > b.x; // 横向有重叠段（上下关系）

/**
 * 把被拖的那条边夹进 [lo, hi]。两端会打架：一端是被拖卡自己的最小尺寸，另一端是
 * 邻居/障碍物让出的极限，空间不够时两个条件同时满足不了。`keep` 指的是被拖卡
 * 最小尺寸在哪一端——冲突时让它赢，否则手上这张卡会被悄悄压到比最小尺寸还小，
 * 而 CSS 的 min-width/min-height 又会把它撑回去，看起来就是它压住了邻居。
 */
function clampEdge(v: number, lo: number, hi: number, keep: 'lo' | 'hi'): number {
  return keep === 'lo'
    ? Math.min(Math.max(v, lo), Math.max(lo, hi))
    : Math.max(Math.min(v, hi), Math.min(lo, hi));
}

/**
 * 手势开始时锁定跟随者：贴着被拖卡片四条边的邻居、原缝、固定不动的锚缘、起始矩形。
 * 整个手势内不重算——每帧重算会因邻居已跟随移动、缝隙变大而“掉链子”。
 */
export function linkFollowers(active: CardGeom, others: CardGeom[]): Followers {
  const old = active.rect;
  const f: Followers = { e: [], w: [], s: [], n: [] };
  for (const c of others) {
    if (c.id === active.id) continue;
    const r = c.rect;
    const inRange = (gap: number) => gap >= -LINK_OVERLAP_MAX && gap <= LINK_GAP_MAX;
    let gap = r.x - (old.x + old.w);            // 右侧邻居（贴我的右边）
    if (inRange(gap) && ovV(old, r)) f.e.push({ id: c.id, gap, anchor: r.x + r.w, r0: { ...r }, min: c.min });
    gap = old.x - (r.x + r.w);                  // 左侧邻居
    if (inRange(gap) && ovV(old, r)) f.w.push({ id: c.id, gap, anchor: r.x, r0: { ...r }, min: c.min });
    gap = r.y - (old.y + old.h);                // 下方邻居
    if (inRange(gap) && ovH(old, r)) f.s.push({ id: c.id, gap, anchor: r.y + r.h, r0: { ...r }, min: c.min });
    gap = old.y - (r.y + r.h);                  // 上方邻居
    if (inRange(gap) && ovH(old, r)) f.n.push({ id: c.id, gap, anchor: r.y, r0: { ...r }, min: c.min });
  }
  return f;
}

export interface LinkedResult { active: Rect; moved: Map<string, Rect> }

/**
 * 联动缩放（对齐 Qt DashboardCanvas._resize_linked）：与被拖动边贴合的相邻卡片
 * 跟随让位/补位，保持原缝；跟随者被推挤时撞到任何非跟随卡片就停，所有参与者
 * 都不小于各自最小尺寸，过程中永不产生新的重叠。
 *
 * @param active   被拖卡片（rect = 手势起点矩形 old）
 * @param others   其余卡片的**当前**矩形（跟随者在手势中会变，阻碍物不变）
 * @param want     resizeBy 算出的目标矩形
 * @param F        linkFollowers 在手势开始时锁定的结果
 */
export function resizeLinked(active: CardGeom, others: CardGeom[], dir: Dir,
                             want: Rect, F: Followers, cw: number, ch: number): LinkedResult {
  const old = active.rect;
  let { x, y, w, h } = want;
  cw = Math.max(1, cw);
  ch = Math.max(1, ch);
  const byId = new Map(others.map((c) => [c.id, c]));
  const moved = new Map<string, Rect>();
  const cur = (id: string): Rect => moved.get(id) || byId.get(id)!.rect;
  const blockers = (side: Follower[]) => {
    const fset = new Set(side.map((f) => f.id));
    return others.filter((c) => c.id !== active.id && !fset.has(c.id));
  };

  if (dir.includes('e')) {
    let edge = x + w;
    const fols = F.e;
    let lo = x + active.min[0];
    let hi = cw;
    for (const f of fols) {
      hi = Math.min(hi, f.anchor - f.gap - f.min[0]);
      for (const b of blockers(fols)) {           // 跟随者左移撞到它左侧的卡就停
        const br = cur(b.id);
        if (br.x + br.w <= f.r0.x + LINK_GAP_MAX && ovV(f.r0, br)) lo = Math.max(lo, br.x + br.w - f.gap);
      }
    }
    for (const b of blockers(fols)) {             // 被拖卡拉宽压不到右侧非跟随卡
      const br = cur(b.id);
      if (br.x >= old.x + old.w - LINK_OVERLAP_MAX && (ovV(old, br) || ovV(want, br))) hi = Math.min(hi, br.x);
    }
    edge = Math.max(0, clampEdge(edge, lo, hi, 'lo'));
    for (const f of fols) {
      const c = cur(f.id);
      moved.set(f.id, { x: edge + f.gap, y: c.y, w: Math.max(1, f.anchor - edge - f.gap), h: c.h });
    }
    w = edge - x;
  }
  if (dir.includes('w')) {
    let edge = x;
    const fols = F.w;
    let lo = 0;
    let hi = old.x + old.w - active.min[0];
    for (const f of fols) {
      lo = Math.max(lo, f.anchor + f.min[0] + f.gap);
      for (const b of blockers(fols)) {           // 跟随者右移撞到它右侧的卡就停
        const br = cur(b.id);
        if (br.x >= f.r0.x + f.r0.w - LINK_GAP_MAX && ovV(f.r0, br)) hi = Math.min(hi, br.x + f.gap);
      }
    }
    for (const b of blockers(fols)) {             // 被拖卡拉宽压不到左侧非跟随卡
      const br = cur(b.id);
      if (br.x + br.w <= old.x + LINK_OVERLAP_MAX && (ovV(old, br) || ovV(want, br))) lo = Math.max(lo, br.x + br.w);
    }
    edge = Math.min(cw, clampEdge(edge, lo, hi, 'hi'));
    for (const f of fols) {
      const c = cur(f.id);
      moved.set(f.id, { x: c.x, y: c.y, w: Math.max(1, edge - f.gap - f.anchor), h: c.h });
    }
    w = old.x + old.w - edge;
    x = edge;
  }
  if (dir.includes('s')) {
    let edge = y + h;
    const fols = F.s;
    let lo = y + active.min[1];
    let hi = ch;
    for (const f of fols) {
      hi = Math.min(hi, f.anchor - f.gap - f.min[1]);
      for (const b of blockers(fols)) {           // 跟随者上移撞到它上方的卡就停
        const br = cur(b.id);
        if (br.y + br.h <= f.r0.y + LINK_GAP_MAX && ovH(f.r0, br)) lo = Math.max(lo, br.y + br.h - f.gap);
      }
    }
    // 横向压没压上，按 e/w 两支已经定下来的实际宽度算：用 want 的话，角上手柄
    // （se/sw…）那一下会拿「想要的宽度」去判，横向明明被邻居顶住没长出去，
    // 纵向却按长出去的样子提前刹车。
    for (const b of blockers(fols)) {             // 被拖卡拉长压不到下方非跟随卡
      const br = cur(b.id);
      if (br.y >= old.y + old.h - LINK_OVERLAP_MAX && (ovH(old, br) || ovH({ x, y, w, h }, br))) hi = Math.min(hi, br.y);
    }
    edge = Math.max(0, clampEdge(edge, lo, hi, 'lo'));
    for (const f of fols) {
      const c = cur(f.id);
      moved.set(f.id, { x: c.x, y: edge + f.gap, w: c.w, h: Math.max(1, f.anchor - edge - f.gap) });
    }
    h = edge - y;
  }
  if (dir.includes('n')) {
    let edge = y;
    const fols = F.n;
    let lo = 0;
    let hi = old.y + old.h - active.min[1];
    for (const f of fols) {
      lo = Math.max(lo, f.anchor + f.min[1] + f.gap);
      for (const b of blockers(fols)) {           // 跟随者下移撞到它下方的卡就停
        const br = cur(b.id);
        if (br.y >= f.r0.y + f.r0.h - LINK_GAP_MAX && ovH(f.r0, br)) hi = Math.min(hi, br.y + f.gap);
      }
    }
    for (const b of blockers(fols)) {             // 被拖卡拉长压不到上方非跟随卡
      const br = cur(b.id);
      if (br.y + br.h <= old.y + LINK_OVERLAP_MAX && (ovH(old, br) || ovH({ x, y, w, h }, br))) lo = Math.max(lo, br.y + br.h);
    }
    edge = Math.min(ch, clampEdge(edge, lo, hi, 'hi'));
    for (const f of fols) {
      const c = cur(f.id);
      moved.set(f.id, { x: c.x, y: c.y, w: c.w, h: Math.max(1, edge - f.gap - f.anchor) });
    }
    h = old.y + old.h - edge;
    y = edge;
  }

  x = Math.max(0, Math.min(x, cw - w));
  y = Math.max(0, Math.min(y, ch - h));
  return { active: { x, y, w, h }, moved };
}

const intersects = (a: Rect, b: Rect) =>
  a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;

/**
 * 新卡片落点：从左上角按 24px 步进扫，找第一个与现有卡片（外扩 8px）都不相交的位置。
 * ADD_DEFAULT 里的 x/y 只作参考，落点总是扫出来的第一个空位（对齐 Qt _find_free_spot）。
 *
 * 下限用 cardMinPx 而不是正文最小值：这里量的是卡片本体矩形，少算标题栏那 40px
 * 的话，画布偏小时新卡会落成一个比自己最小高度还矮的位置，CSS 的 min-height 把它
 * 撑回去就正好压住下面那张。
 */
export function findFreeSpot(type: string, fw: number, fh: number,
                             cw: number, ch: number, existing: Rect[]): Rect {
  cw = Math.max(1, cw);
  ch = Math.max(1, ch);
  const [mw, mh] = cardMinPx(type);
  let w = Math.max(mw, Math.trunc(fw * cw));
  let h = Math.max(mh, Math.trunc(fh * ch));
  w = Math.min(w, cw - 16);
  h = Math.min(h, ch - 16);
  const padded = existing.map((r) => ({ x: r.x - 8, y: r.y - 8, w: r.w + 16, h: r.h + 16 }));
  const step = 24;
  for (let yy = 8; yy < Math.max(9, ch - h - 8); yy += step) {
    for (let xx = 8; xx < Math.max(9, cw - w - 8); xx += step) {
      const cand = { x: xx, y: yy, w, h };
      if (!padded.some((r) => intersects(cand, r))) return cand;
    }
  }
  return { x: 8, y: 8, w, h };
}

/** 把可见卡片的联合包围盒等比放大到铺满画布（留 12px 边距）。就地改 doc。 */
export function fitToWindow(doc: LayoutDoc, cw: number, ch: number) {
  cw = Math.max(1, cw);
  ch = Math.max(1, ch);
  const vis = visibleItems(doc);
  if (!vis.length) return;
  const bx0 = Math.min(...vis.map((it) => it.x));
  const by0 = Math.min(...vis.map((it) => it.y));
  const bx1 = Math.max(...vis.map((it) => it.x + it.w));
  const by1 = Math.max(...vis.map((it) => it.y + it.h));
  const bw = Math.max(1e-4, bx1 - bx0);
  const bh = Math.max(1e-4, by1 - by0);
  const mx = 12 / cw;
  const my = 12 / ch;
  const sx = (1 - 2 * mx) / bw;
  const sy = (1 - 2 * my) / bh;
  for (const it of vis) {
    const [mw, mh] = cardMinPx(it.type); // 同 findFreeSpot：量的是卡片本体，含标题栏
    it.x = mx + (it.x - bx0) * sx;
    it.y = my + (it.y - by0) * sy;
    it.w = Math.max(mw / cw, it.w * sx);
    it.h = Math.max(mh / ch, it.h * sy);
  }
}

/** 两矩形是否有正面积重叠（模糊测试断言用；允许 tol 像素的贴边误差）。 */
export function overlaps(a: Rect, b: Rect, tol = 0): boolean {
  return a.x + tol < b.x + b.w && a.x + a.w > b.x + tol && a.y + tol < b.y + b.h && a.y + a.h > b.y + tol;
}

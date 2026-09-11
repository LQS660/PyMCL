/**
 * 自由布局画布：启动页可自定义 UI 的核心（对齐 Qt 版 app/dashboard.py）。
 *
 * DashboardCanvas 是一个绝对定位容器，子项 DashboardCard 按布局文档
 * （layout_geom.LayoutDoc）中的画布比例摆放。支持：
 *
 * - 查看模式：卡片正常交互，右上角悬浮「编辑布局」入口；
 * - 编辑模式：整卡拖动、8 向手柄缩放、网格吸附（可调/可关）、邻卡联动、
 *   顶层置前、选中/删除卡片（Delete）、恢复上一步（Ctrl+Z）、添加卡片
 *   （调色板）、适应窗口、重置布局；
 * - 所有改动经 onChange 回调通知宿主页持久化（结构改动立即，几何改动 300ms 防抖）。
 *
 * 卡片类型由外部注册表提供（见 pages/launch.ts），画布只负责框架行为，不关心卡片内容。
 * Qt 里为拦鼠标/画点阵/防最小尺寸钉死写的那些胶水（_Shield / _grid_pixmap / QScrollArea）
 * 在 DOM 里分别是 pointer-events:none、一张 radial-gradient 背景、overflow:auto。
 */

import {
  ADD_DEFAULT, GRID_CHOICES, type Dir, DIRS, type LayoutDoc, type LayoutItem, type Rect,
  cardMinPx, cloneDoc, defaultDoc, dragTo, findFreeSpot, fitToWindow, linkFollowers,
  newItem, nextZ, normalize, placeAll, resizeBy, resizeLinked, setGeometryPx, toDict,
  visibleItems,
} from './layout_geom';
import { dismissOverlay, toast } from './ui';

export interface CardSpec {
  key: string;
  title: string;
  /** 标题栏左侧的小图标（文字/emoji）。 */
  icon: string;
  /** 调色板里的一行说明。 */
  desc: string;
  /** 单例：全画布只能有一张（绑定页面逻辑）。 */
  single?: boolean;
  /** 是否常驻标题栏（false = 仅编辑时显示）。默认 true。 */
  chrome?: boolean;
  /** 正文是否留内边距。横幅那种铺满渐变的传 false。默认 true。 */
  padded?: boolean;
  makeBody: (card: DashboardCard, item: LayoutItem) => HTMLElement;
  onSettings?: (canvas: DashboardCanvas, card: DashboardCard, item: LayoutItem) => void;
  /** 卡片被移除 / 画布重建时对正文做什么：单例缓存的传空函数保留控件状态。 */
  onRemoved?: (body: HTMLElement, item: LayoutItem) => void;
}

const CURSORS: Record<Dir, string> = {
  n: 'ns-resize', s: 'ns-resize', e: 'ew-resize', w: 'ew-resize',
  ne: 'nesw-resize', sw: 'nesw-resize', nw: 'nwse-resize', se: 'nwse-resize',
};

/** 撤销栈上限：每一步是一份完整布局文档（几百字节），50 步足够一次编辑用。 */
const HISTORY_MAX = 50;

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls = '', text = ''): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text) node.textContent = text;
  return node;
}

export class DashboardCard {
  readonly el: HTMLElement;
  readonly header: HTMLElement;
  readonly titleEl: HTMLElement;
  readonly settingsBtn: HTMLButtonElement;
  readonly removeBtn: HTMLButtonElement;
  readonly bodyHost: HTMLElement;
  readonly grips: HTMLElement[] = [];
  body: HTMLElement | null = null;
  /** 正文可选的刷新钩子（makeBody 里挂上）。 */
  refresh: (() => void) | null = null;
  rect: Rect = { x: 0, y: 0, w: 1, h: 1 };
  /** 本体（含标题栏）最小尺寸。 */
  readonly min: [number, number];

  constructor(readonly canvas: DashboardCanvas, public item: LayoutItem, readonly spec: CardSpec) {
    this.min = cardMinPx(item.type);
    this.el = el('div', 'dash-card');
    this.el.dataset.type = item.type;
    this.el.style.minWidth = `${this.min[0]}px`;
    this.el.style.minHeight = `${this.min[1]}px`;

    // ---- 标题栏 ----
    this.header = el('div', 'dash-card-head');
    const icon = el('span', 'dash-card-icon', spec.icon);
    this.titleEl = el('span', 'dash-card-title', spec.title);
    this.settingsBtn = el('button', 'dash-card-tool', '⚙');
    this.settingsBtn.type = 'button';
    this.settingsBtn.title = '卡片设置';
    this.settingsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      spec.onSettings?.(canvas, this, this.item);
    });
    this.removeBtn = el('button', 'dash-card-tool danger', '✕');
    this.removeBtn.type = 'button';
    this.removeBtn.title = '移除此卡片';
    this.removeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      canvas.removeCard(this);
    });
    this.header.append(icon, this.titleEl, this.settingsBtn, this.removeBtn);
    this.el.appendChild(this.header);

    // ---- 正文宿主：overflow:auto，正文的内在最小尺寸不会把卡片钉死 ----
    this.bodyHost = el('div', 'dash-card-body' + (spec.padded === false ? ' bare' : ''));
    this.el.appendChild(this.bodyHost);
    const body = spec.makeBody(this, item);
    if (body) {
      this.body = body;
      this.bodyHost.appendChild(body);
    }

    // ---- 编辑态配件：8 个手柄 ----
    for (const d of DIRS) {
      const g = el('div', `dash-grip dash-grip-${d}`);
      g.style.cursor = CURSORS[d];
      g.addEventListener('pointerdown', (e) => canvas.beginResize(this, d, e));
      this.grips.push(g);
      this.el.appendChild(g);
    }

    // 编辑态整卡拖动：正文已 pointer-events:none，落到卡片本体上的就是拖动；
    // 标题栏里的按钮和手柄自己处理，不当拖动。
    this.el.addEventListener('pointerdown', (e) => {
      if (!canvas.editing) return;
      const t = e.target as HTMLElement | null;
      if (t?.closest('.dash-card-tool, .dash-grip')) return; // 手柄的 pointerdown 自己处理
      canvas.beginDrag(this, e);
    });
    this.setEditMode(canvas.editing);
  }

  applyRect(r: Rect) {
    this.rect = r;
    const s = this.el.style;
    s.left = `${r.x}px`;
    s.top = `${r.y}px`;
    s.width = `${r.w}px`;
    s.height = `${r.h}px`;
  }

  applyZ() {
    this.el.style.zIndex = String(this.item.z + 1);
  }

  setTitle(text: string) {
    this.titleEl.textContent = text;
  }

  setEditMode(on: boolean) {
    this.el.classList.toggle('editing', on);
    this.header.style.display = (on || this.spec.chrome !== false) ? '' : 'none';
    this.removeBtn.style.display = on ? '' : 'none';
    this.settingsBtn.style.display = (on && this.spec.onSettings) ? '' : 'none';
  }
}

export class DashboardCanvas {
  readonly el: HTMLElement;
  private readonly gridLayer: HTMLElement;
  private readonly toolbar: HTMLElement;
  private readonly gridSelect: HTMLSelectElement;
  private readonly editFab: HTMLButtonElement;
  private readonly deleteBtn: HTMLButtonElement;
  private readonly undoBtn: HTMLButtonElement;
  doc: LayoutDoc = defaultDoc();
  cards: DashboardCard[] = [];
  editing = false;
  /** 编辑态里当前选中的卡片：工具条的「删除」和 Delete 键都对它下手。 */
  selected: DashboardCard | null = null;
  /** 撤销栈：每一步是动手之前的整份文档，删掉的卡片靠它原样回来。 */
  private history: LayoutDoc[] = [];
  /** 布局有变化：structural=true 立即；几何改动经 300ms 防抖再来一次。宿主页负责落盘。 */
  onChange: ((structural: boolean) => void) | null = null;
  private persistTimer = 0;
  private readonly ro: ResizeObserver | null;

  constructor(readonly registry: Record<string, CardSpec>, host: HTMLElement) {
    this.el = el('div', 'dash-canvas');
    this.gridLayer = el('div', 'dash-grid');
    this.el.appendChild(this.gridLayer);

    // 编辑模式工具条
    this.toolbar = el('div', 'dash-toolbar');
    const addBtn = el('button', 'btn btn-sm', '＋ 添加卡片');
    addBtn.type = 'button';
    addBtn.addEventListener('click', () => this.openPalette());
    this.deleteBtn = el('button', 'btn btn-sm', '🗑 删除');
    this.deleteBtn.type = 'button';
    this.deleteBtn.title = '删除选中的卡片（选中后按 Delete 也行）';
    this.deleteBtn.addEventListener('click', () => this.deleteSelected());
    this.undoBtn = el('button', 'btn btn-sm', '↶ 恢复');
    this.undoBtn.type = 'button';
    this.undoBtn.title = '恢复上一步（Ctrl+Z）：删掉的卡片、挪动过的位置都能撤回来';
    this.undoBtn.addEventListener('click', () => this.undo());
    const gridLabel = el('span', 'dash-toolbar-label', '吸附');
    this.gridSelect = el('select', 'select dash-grid-select');
    for (const v of GRID_CHOICES) {
      const o = el('option', '', v === 0 ? '自由' : `${v}px`);
      o.value = String(v);
      this.gridSelect.appendChild(o);
    }
    this.gridSelect.addEventListener('change', () => {
      this.pushHistory();
      this.doc.grid = parseInt(this.gridSelect.value, 10) || 0;
      this.paintGrid();
      this.touch(true);
    });
    const fitBtn = el('button', 'btn btn-sm', '适应窗口');
    fitBtn.type = 'button';
    fitBtn.addEventListener('click', () => this.fitToWindow());
    const resetBtn = el('button', 'btn btn-sm', '重置布局');
    resetBtn.type = 'button';
    resetBtn.addEventListener('click', () => this.resetLayout());
    const doneBtn = el('button', 'btn btn-sm btn-primary', '✓ 完成');
    doneBtn.type = 'button';
    doneBtn.addEventListener('click', () => this.setEditMode(false));
    this.toolbar.append(addBtn, this.deleteBtn, this.undoBtn, gridLabel, this.gridSelect, fitBtn, resetBtn, doneBtn);
    this.el.appendChild(this.toolbar);
    this.syncToolbar();

    // 点画布空白处取消选中（点在卡片上时卡片自己的处理已经把它选起来了）
    this.el.addEventListener('pointerdown', (e) => {
      if (!this.editing) return;
      const t = e.target as HTMLElement | null;
      if (t === this.el || t === this.gridLayer) this.select(null);
    });

    // 查看模式：右上角悬浮入口
    this.editFab = el('button', 'dash-edit-fab', '✎ 编辑布局');
    this.editFab.type = 'button';
    this.editFab.title = '自由调整启动页布局：拖动、缩放、增删卡片';
    this.editFab.addEventListener('click', () => this.setEditMode(true));
    this.el.appendChild(this.editFab);

    host.appendChild(this.el);
    // 比例布局：画布尺寸变化时按文档比例重摆，窗口缩放布局自适应
    this.ro = typeof ResizeObserver === 'function'
      ? new ResizeObserver(() => this.applyGeometry())
      : null;
    this.ro?.observe(this.el);
  }

  get width() { return Math.max(1, this.el.clientWidth); }
  get height() { return Math.max(1, this.el.clientHeight); }

  destroy() {
    this.ro?.disconnect();
    document.removeEventListener('keydown', this.onKeyDown);
    if (this.persistTimer) clearTimeout(this.persistTimer);
    this.persistTimer = 0;
    this.el.remove();
  }

  // ------------------------------------------------------------------
  // 选中 / 删除 / 恢复
  // ------------------------------------------------------------------
  /** 编辑态里选中一张卡（传 null 取消选中）。 */
  select(card: DashboardCard | null) {
    if (this.selected === card) return;
    this.selected?.el.classList.remove('selected');
    this.selected = card && this.cards.includes(card) ? card : null;
    this.selected?.el.classList.add('selected');
    this.syncToolbar();
  }

  deleteSelected() {
    // 按钮不置灰、改成给一句提示：置灰的按钮说不清「要先选一张」，
    // 而选中这件事本身是要教给人的
    if (!this.selected) {
      toast('先点一下要删除的卡片，再按「删除」（或直接按 Delete）', 'info');
      return;
    }
    this.removeCard(this.selected);
  }

  /** 动手之前存一份：删卡、加卡、适应窗口、重置、改吸附、每一次拖动/缩放。 */
  pushHistory() {
    this.history.push(this.snapshot());
    if (this.history.length > HISTORY_MAX) this.history.shift();
    this.syncToolbar();
  }

  /** 手势用：前后真的变了才记一步，光点一下不该占掉一次撤销。 */
  private commitHistory(before: LayoutDoc) {
    if (JSON.stringify(toDict(before)) === JSON.stringify(this.currentDoc())) return;
    this.history.push(before);
    if (this.history.length > HISTORY_MAX) this.history.shift();
    this.syncToolbar();
  }

  /** 恢复上一步。返回是否真的退了一步（栈空时 false）。 */
  undo(): boolean {
    const prev = this.history.pop();
    if (!prev) return false;
    this.select(null);
    this.buildFromDoc(prev);
    this.touch(true);
    this.syncToolbar();
    return true;
  }

  private syncToolbar() {
    this.deleteBtn.classList.toggle('dash-tool-idle', !this.selected);
    this.undoBtn.disabled = !this.history.length;
  }

  /** 编辑态的键盘操作；焦点在输入控件里时一律不拦。 */
  private readonly onKeyDown = (e: KeyboardEvent) => {
    if (!this.editing) return;
    // 调色板/对话框开着时键盘归它：否则 Esc 会从它背后把编辑态关掉，
    // Delete 也会删到看不见的那张卡上
    if (document.querySelector('.modal-overlay')) return;
    const t = e.target as HTMLElement | null;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'z') {
      e.preventDefault();
      this.undo();
      return;
    }
    if ((e.key === 'Delete' || e.key === 'Backspace') && this.selected) {
      e.preventDefault();
      this.deleteSelected();
      return;
    }
    if (e.key === 'Escape') {
      // 有选中先取消选中，没选中才退出编辑——免得一下子全退掉
      if (this.selected) this.select(null);
      else this.setEditMode(false);
    }
  };

  // ------------------------------------------------------------------
  // 构建 / 重建
  // ------------------------------------------------------------------
  registryOrder(): string[] {
    return Object.keys(this.registry);
  }

  buildFromDoc(doc: LayoutDoc) {
    this.doc = doc;
    this.rebuild();
  }

  private rebuild() {
    // 卡片对象整批换新，选中状态按 item.id 认回去（认不回就当没选）
    const selectedId = this.selected?.item.id || '';
    this.selected = null;
    for (const card of this.cards) {
      const body = card.body;
      if (body) {
        body.remove();
        try { card.spec.onRemoved?.(body, card.item); } catch { /* ignore */ }
      }
      card.el.remove();
    }
    this.cards = [];
    for (const item of visibleItems(this.doc)) {
      const spec = this.registry[item.type];
      if (!spec) continue; // 不认识的类型（别的前端存的）跳过，保留在文档里
      const card = new DashboardCard(this, item, spec);
      this.cards.push(card);
      card.applyZ();
      this.el.appendChild(card.el);
    }
    this.applyGeometry();
    this.syncGridSelect();
    this.paintGrid();
    this.select(this.cards.find((c) => c.item.id === selectedId) || null);
    this.syncToolbar(); // 选中被整批换掉时 select() 会提前返回，按钮状态得自己补一次
  }

  /** 按文档比例重摆全部卡片（构建后 / 画布尺寸变化时调用）。 */
  applyGeometry() {
    const placed = placeAll(this.cards.map((c) => c.item), this.width, this.height);
    for (const card of this.cards) {
      const r = placed.get(card.item.id);
      if (r) card.applyRect(r);
    }
  }

  private syncGridSelect() {
    this.gridSelect.value = String(this.doc.grid);
    if (this.gridSelect.value !== String(this.doc.grid)) this.gridSelect.value = '0';
  }

  private paintGrid() {
    const g = this.doc.grid;
    if (g > 0) {
      this.gridLayer.style.backgroundSize = `${g}px ${g}px`;
      this.gridLayer.style.backgroundPosition = `${g / 2}px ${g / 2}px`;
      this.gridLayer.style.display = '';
    } else {
      this.gridLayer.style.display = 'none';
    }
  }

  // ------------------------------------------------------------------
  // 编辑模式
  // ------------------------------------------------------------------
  setEditMode(on: boolean) {
    if (this.editing === on) return;
    this.editing = on;
    this.el.classList.toggle('editing', on);
    for (const card of this.cards) card.setEditMode(on);
    if (on) {
      document.addEventListener('keydown', this.onKeyDown);
    } else {
      document.removeEventListener('keydown', this.onKeyDown);
      this.select(null);
      // 撤销栈特意留着：退出编辑后才反应过来「刚才那张不该删」是常事，
      // 再点进来还能按「恢复」退回去（整页卸载时随画布一起丢）。
    }
  }

  private openPalette() {
    const overlay = el('div', 'modal-overlay');
    const modal = el('div', 'modal dash-palette');
    modal.appendChild(el('div', 'modal-title', '添加卡片'));
    modal.appendChild(el('p', 'dash-palette-hint', '点击要添加到布局的卡片：'));
    const list = el('div', 'dash-palette-list');
    const usedSingle = new Set(this.cards.filter((c) => c.spec.single).map((c) => c.item.type));
    let any = false;
    for (const key of this.registryOrder()) {
      const spec = this.registry[key];
      if (spec.single && usedSingle.has(key)) continue;
      any = true;
      const row = el('button', 'dash-palette-row');
      row.type = 'button';
      row.append(el('span', 'dash-card-icon', spec.icon), el('span', '', spec.desc));
      row.addEventListener('click', () => {
        dismissOverlay(overlay);
        this.addCard(key);
      });
      list.appendChild(row);
    }
    if (!any) list.appendChild(el('div', 'empty-state', '所有卡片都已在布局里'));
    modal.appendChild(list);
    const actions = el('div', 'modal-actions');
    const close = el('button', 'btn', '关闭');
    close.type = 'button';
    close.addEventListener('click', () => dismissOverlay(overlay));
    actions.appendChild(close);
    modal.appendChild(actions);
    overlay.appendChild(modal);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) dismissOverlay(overlay); });
    document.body.appendChild(overlay);
  }

  // ------------------------------------------------------------------
  // 增删 / 排布
  // ------------------------------------------------------------------
  addCard(type: string): DashboardCard | null {
    const spec = this.registry[type];
    if (!spec) return null;
    if (spec.single && this.cards.some((c) => c.item.type === type)) return null;
    this.pushHistory();
    const [, , fw, fh] = ADD_DEFAULT[type] || [0.3, 0.3, 0.3, 0.26];
    const cw = this.width;
    const ch = this.height;
    const spot = findFreeSpot(type, fw, fh, cw, ch, this.cards.map((c) => c.rect));
    const item = newItem(type, 0, 0, 0.1, 0.1, { z: nextZ(this.doc) });
    setGeometryPx(item, spot, cw, ch);
    this.doc.items.push(item);
    const card = new DashboardCard(this, item, spec);
    this.cards.push(card);
    card.applyRect(spot);
    card.applyZ();
    card.el.classList.add('entering');
    card.el.addEventListener('animationend', () => card.el.classList.remove('entering'), { once: true });
    this.el.appendChild(card.el);
    this.select(card);   // 刚添的这张直接选中：位置不合适可以立刻删掉重来
    this.touch(true);
    return card;
  }

  removeCard(card: DashboardCard) {
    const i = this.cards.indexOf(card);
    if (i < 0) return;
    this.pushHistory();          // 删之前存一份，「恢复」就能把这张原样放回来
    if (this.selected === card) this.select(null);
    this.cards.splice(i, 1);
    const body = card.body;
    if (body) {
      body.remove();
      try { card.spec.onRemoved?.(body, card.item); } catch { /* ignore */ }
    }
    this.doc.items = this.doc.items.filter((it) => it !== card.item);
    card.el.classList.add('leaving');
    const drop = () => card.el.remove();
    card.el.addEventListener('animationend', drop, { once: true });
    setTimeout(drop, 220); // 动效关掉时 animationend 不会来
    this.touch(true);
  }

  fitToWindow() {
    this.pushHistory();
    fitToWindow(this.doc, this.width, this.height);
    this.rebuild();
    this.touch(true);
  }

  resetLayout() {
    this.pushHistory();          // 重置也能退回来，不必怕手抖点到
    this.buildFromDoc(defaultDoc());
    this.touch(true);
  }

  currentDoc(): LayoutDoc {
    normalize(this.doc);
    return toDict(this.doc);
  }

  snapshot(): LayoutDoc {
    return cloneDoc(this.doc);
  }

  refreshCards() {
    for (const card of this.cards) {
      try { card.refresh?.(); } catch { /* ignore */ }
    }
  }

  /** 布局变化：结构改动立即广播，几何改动防抖合并；最终都会再发一次。 */
  touch(structural = false) {
    if (structural) this.onChange?.(true);
    if (this.persistTimer) clearTimeout(this.persistTimer);
    this.persistTimer = window.setTimeout(() => {
      this.persistTimer = 0;
      this.onChange?.(false);
    }, 300);
  }

  private takeTop(card: DashboardCard) {
    card.item.z = nextZ(this.doc);
    card.applyZ();
  }

  // ------------------------------------------------------------------
  // 交互：整卡拖动 / 手柄缩放（Pointer Events + 指针捕获）
  // ------------------------------------------------------------------
  beginDrag(card: DashboardCard, ev: PointerEvent) {
    if (!this.editing || ev.button !== 0) return;
    ev.preventDefault();
    this.select(card);
    const before = this.snapshot();
    const host = this.el.getBoundingClientRect();
    const anchor = { x: ev.clientX - host.left - card.rect.x, y: ev.clientY - host.top - card.rect.y };
    const cw = this.width;
    const ch = this.height;
    this.takeTop(card);
    card.el.classList.add('dragging');
    let frame = 0;
    let last: PointerEvent = ev;
    const apply = () => {
      frame = 0;
      card.applyRect(dragTo(card.rect,
        last.clientX - host.left - anchor.x, last.clientY - host.top - anchor.y,
        this.doc.grid, cw, ch));
    };
    const move = (e: PointerEvent) => {
      last = e;
      if (!frame) frame = requestAnimationFrame(apply);
    };
    const up = () => {
      card.el.removeEventListener('pointermove', move);
      card.el.removeEventListener('pointerup', up);
      card.el.removeEventListener('pointercancel', up);
      if (frame) cancelAnimationFrame(frame);
      apply();
      card.el.classList.remove('dragging');
      setGeometryPx(card.item, card.rect, cw, ch);
      this.commitHistory(before);
      this.touch(false);
    };
    try { card.el.setPointerCapture(ev.pointerId); } catch { /* 触控板等不支持时退回冒泡 */ }
    card.el.addEventListener('pointermove', move);
    card.el.addEventListener('pointerup', up);
    card.el.addEventListener('pointercancel', up);
  }

  beginResize(card: DashboardCard, dir: Dir, ev: PointerEvent) {
    if (!this.editing || ev.button !== 0) return;
    ev.preventDefault();
    ev.stopPropagation();       // 手柄自己吃掉，卡片那层不当整卡拖动
    this.select(card);
    const before = this.snapshot();
    const grip = ev.currentTarget as HTMLElement;
    const start: Rect = { ...card.rect };
    const sx = ev.clientX;
    const sy = ev.clientY;
    const cw = this.width;
    const ch = this.height;
    const me = { id: card.item.id, rect: start, min: card.min };
    const geom = (c: DashboardCard) => ({ id: c.item.id, rect: { ...c.rect }, min: c.min });
    // 跟随者在手势开始时锁定，整个手势内不重算
    const F = linkFollowers(me, this.cards.filter((c) => c !== card).map(geom));
    const byId = new Map(this.cards.map((c) => [c.item.id, c]));
    const touched = new Set<DashboardCard>();
    this.takeTop(card);
    card.el.classList.add('dragging');
    let frame = 0;
    let last: PointerEvent = ev;
    const apply = () => {
      frame = 0;
      const want = resizeBy(dir, start, last.clientX - sx, last.clientY - sy, card.min, this.doc.grid, cw, ch);
      const others = this.cards.filter((c) => c !== card).map(geom);
      const res = resizeLinked(me, others, dir, want, F, cw, ch);
      card.applyRect(res.active);
      res.moved.forEach((r, id) => {
        const c = byId.get(id);
        if (c) { c.applyRect(r); touched.add(c); }
      });
    };
    const move = (e: PointerEvent) => {
      last = e;
      if (!frame) frame = requestAnimationFrame(apply);
    };
    const up = () => {
      grip.removeEventListener('pointermove', move);
      grip.removeEventListener('pointerup', up);
      grip.removeEventListener('pointercancel', up);
      if (frame) cancelAnimationFrame(frame);
      apply();
      card.el.classList.remove('dragging');
      setGeometryPx(card.item, card.rect, cw, ch);
      // 松手时把联动过的邻居几何一并写回布局文档（否则下次重摆会弹回）
      for (const c of touched) setGeometryPx(c.item, c.rect, cw, ch);
      this.commitHistory(before);
      this.touch(false);
    };
    try { grip.setPointerCapture(ev.pointerId); } catch { /* ignore */ }
    grip.addEventListener('pointermove', move);
    grip.addEventListener('pointerup', up);
    grip.addEventListener('pointercancel', up);
  }
}

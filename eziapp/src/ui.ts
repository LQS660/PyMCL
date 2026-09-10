// UI 通用组件与工具函数
import { bridge } from './bridge';
import { store } from './store';
import { motionOk } from './motion';
import { escapeHtml } from './pages/common';

// 页面清理注册表
const pageCleanups: (() => void)[] = [];

export function registerPageCleanup(fn: () => void) {
  pageCleanups.push(fn);
  return fn;
}

export function clearPageCleanups() {
  while (pageCleanups.length) {
    const fn = pageCleanups.pop();
    if (!fn) continue;
    try { fn(); } catch { /* ignore */ }
  }
}

export function applyTheme(dark: boolean) {
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
}

function mixHex(hex: string, amount: number): string {
  const raw = hex.replace('#', '').trim();
  const n = raw.length === 3 ? raw.split('').map((c) => c + c).join('') : raw;
  if (!/^[0-9a-fA-F]{6}$/.test(n)) return hex;
  const r = parseInt(n.slice(0, 2), 16);
  const g = parseInt(n.slice(2, 4), 16);
  const b = parseInt(n.slice(4, 6), 16);
  const t = amount >= 0 ? 255 : 0;
  const p = Math.abs(amount);
  const ch = (v: number) => Math.round(v + (t - v) * p).toString(16).padStart(2, '0');
  return `#${ch(r)}${ch(g)}${ch(b)}`;
}

function bgCss(path: string): string {
  if (!path) return '';
  if (/^(https?:|data:|file:)/i.test(path)) return path;
  const normalized = path.replace(/\\/g, '/');
  return `file:///${normalized.replace(/^\/+/, '')}`;
}

export function applyAppearance(settings: Record<string, unknown> | null | undefined) {
  const s = settings || {};
  applyTheme(!!s.ui_dark);
  const color = String(s.theme_color || '#2E9B6B').trim();
  const accent = color.startsWith('#') ? color : `#${color}`;
  const root = document.documentElement;
  root.style.setProperty('--primary', accent);
  root.style.setProperty('--primary-hover', mixHex(accent, -0.12));
  root.style.setProperty('--primary-light', mixHex(accent, 0.86));
  root.dataset.motion = s.ui_motion === false ? 'off' : 'on';
  const bg = String(s.ui_background || '').trim();
  document.body.style.backgroundImage = bg ? `linear-gradient(var(--bg-wash), var(--bg-wash)), url("${bgCss(bg)}")` : '';
  document.body.classList.toggle('has-bg', !!bg);
  const width = Number(s.ui_sidebar_width);
  if (width >= 140 && width <= 320) root.style.setProperty('--sidebar-width', `${width}px`);
}

function pickFlyColor(text: string): string {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) >>> 0;
  const palette = ['#2E9B6B', '#4C8BF5', '#E8862E', '#9B59B6', '#E74C3C', '#1ABC9C'];
  return palette[h % palette.length];
}

function bezier(p0: { x: number; y: number }, pc: { x: number; y: number }, p1: { x: number; y: number }, t: number) {
  const u = 1 - t;
  return {
    x: u * u * p0.x + 2 * u * t * pc.x + t * t * p1.x,
    y: u * u * p0.y + 2 * u * t * pc.y + t * t * p1.y,
  };
}

/** 飞入侧栏「下载任务」：与 Qt/WinUI 对齐。返回 Promise，落地后 resolve。 */
export function flyToTasks(source: Element | null | undefined, text = '', color?: string): Promise<void> {
  return new Promise((resolve) => {
    const settings = store.mergedSettings() as any;
    if (settings.ui_fly_animation === false || !motionOk()) {
      resolve();
      return;
    }
    const target = document.querySelector('.nav-item[data-page="tasks"]') as HTMLElement | null;
    if (!source || !target) {
      resolve();
      return;
    }
    const sRect = (source as Element).getBoundingClientRect();
    const tRect = target.getBoundingClientRect();
    const start = { x: sRect.left + sRect.width / 2, y: sRect.top + sRect.height / 2 };
    const end = { x: tRect.left + tRect.width / 2, y: tRect.top + tRect.height / 2 };
    const dist = Math.hypot(end.x - start.x, end.y - start.y);
    const arc = Math.max(48, Math.min(150, dist * 0.35));
    const control = {
      x: Math.max(8, Math.min(window.innerWidth - 8, (start.x + end.x) / 2)),
      y: Math.max(8, Math.min(window.innerHeight - 8, Math.min(start.y, end.y) - arc)),
    };
    const duration = Math.max(200, Math.min(1200, Number(settings.ui_fly_duration_ms) || 620));
    const letter = (String(text || '').trim().slice(0, 1) || '↓').toUpperCase();
    const ball = document.createElement('div');
    ball.className = 'fly-ball';
    ball.textContent = letter;
    ball.style.background = color || pickFlyColor(String(text || ''));
    document.body.appendChild(ball);

    // 尺寸固定 44px，逐帧只写 transform 和 opacity——这两个属性合成器能自己处理，
    // 不回主线程排版。以前每帧改 width/height/left/top/font-size，五个属性全都
    // 触发重排，一次飞行就是几十次整页 layout。
    const BALL = 44;
    const t0 = performance.now();
    const tick = (now: number) => {
      const raw = Math.min(1, (now - t0) / duration);
      // InOutCubic
      const t = raw < 0.5 ? 4 * raw * raw * raw : 1 - Math.pow(-2 * raw + 2, 3) / 2;
      const p = bezier(start, control, end, t);
      const scale = (BALL + (14 - BALL) * t) / BALL;
      ball.style.transform = `translate3d(${p.x - BALL / 2}px, ${p.y - BALL / 2}px, 0) scale(${scale})`;
      ball.style.opacity = String(t < 0.75 ? 1 : Math.max(0, (1 - t) / 0.25));
      if (raw < 1) {
        requestAnimationFrame(tick);
        return;
      }
      ball.remove();
      const ripple = document.createElement('div');
      ripple.className = 'fly-ripple';
      ripple.style.left = `${end.x}px`;
      ripple.style.top = `${end.y}px`;
      ripple.style.borderColor = color || pickFlyColor(String(text || ''));
      document.body.appendChild(ripple);
      setTimeout(() => ripple.remove(), 420);
      const badge = document.getElementById('task-badge');
      if (badge) {
        badge.classList.add('fly-pulse');
        setTimeout(() => badge.classList.remove('fly-pulse'), 280);
      }
      resolve();
    };
    requestAnimationFrame(tick);
  });
}

// Toast 通知
const TOAST_ICONS = { info: 'ℹ', success: '✓', error: '✕', warning: '⚠' } as const;
export function toast(message: string, type: 'info' | 'success' | 'error' | 'warning' = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icon = document.createElement('span');
  icon.className = 'toast-icon';
  icon.textContent = TOAST_ICONS[type];
  const text = document.createElement('span');
  text.textContent = message;
  el.append(icon, text);
  container.appendChild(el);
  // 堆叠上限：最多的场合是连续安装，旧的不如新的重要
  while (container.children.length > 5) container.firstElementChild?.remove();

  let timer = 0;
  const dismiss = () => {
    el.classList.add('leaving');
    el.addEventListener('animationend', () => el.remove(), { once: true });
  };
  const arm = () => { timer = window.setTimeout(dismiss, duration); };
  // 鼠标停上去就别让它跑了——报错信息经常还没读完就自己滑走了
  el.addEventListener('pointerenter', () => { clearTimeout(timer); el.classList.add('held'); }, { passive: true });
  el.addEventListener('pointerleave', () => { el.classList.remove('held'); arm(); }, { passive: true });
  arm();
}

/** 模态退场动画后再移除。 */
export function dismissOverlay(overlay: HTMLElement) {
  if (!overlay.isConnected) return;
  overlay.classList.add('leaving');
  setTimeout(() => overlay.remove(), 170);
}

export interface MenuItem {
  label: string;
  danger?: boolean;
  onClick: () => void;
}

/** 轻量弹出菜单：锚定到某个元素下方，点外面或选完即关。 */
export function showContextMenu(anchor: HTMLElement, items: MenuItem[]) {
  document.querySelectorAll('.ctx-menu').forEach((m) => m.remove());
  const menu = document.createElement('div');
  menu.className = 'ctx-menu';
  for (const item of items) {
    const btn = document.createElement('button');
    btn.className = `ctx-menu-item${item.danger ? ' danger' : ''}`;
    btn.textContent = item.label;
    btn.addEventListener('click', () => { menu.remove(); item.onClick(); });
    menu.appendChild(btn);
  }
  document.body.appendChild(menu);
  const rect = anchor.getBoundingClientRect();
  menu.style.position = 'fixed';
  menu.style.left = `${Math.min(rect.left, window.innerWidth - menu.offsetWidth - 8)}px`;
  const below = rect.bottom + 4;
  menu.style.top = `${below + menu.offsetHeight > window.innerHeight - 8 ? Math.max(8, rect.top - menu.offsetHeight - 4) : below}px`;
  const off = (e: MouseEvent) => {
    if (!menu.contains(e.target as Node)) {
      menu.remove();
      document.removeEventListener('pointerdown', off);
    }
  };
  setTimeout(() => document.addEventListener('pointerdown', off), 0);
}

// 确认弹窗
export function confirmDialog(title: string, message: string): Promise<boolean> {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal">
        <div class="modal-title" id="confirm-title"></div>
        <p style="font-size:13px;color:var(--text-secondary);margin-bottom:16px" id="confirm-msg"></p>
        <div class="modal-actions">
          <button class="btn" id="confirm-cancel">取消</button>
          <button class="btn btn-danger" id="confirm-ok">确认</button>
        </div>
      </div>
    `;
    overlay.querySelector('#confirm-title')!.textContent = title;
    overlay.querySelector('#confirm-msg')!.textContent = message;
    document.body.appendChild(overlay);
    overlay.querySelector('#confirm-ok')!.addEventListener('click', () => { dismissOverlay(overlay); resolve(true); });
    overlay.querySelector('#confirm-cancel')!.addEventListener('click', () => { dismissOverlay(overlay); resolve(false); });
    overlay.addEventListener('click', e => { if (e.target === overlay) { dismissOverlay(overlay); resolve(false); } });
  });
}

export interface FormField {
  id: string;
  label: string;
  type?: 'text' | 'number' | 'password' | 'select' | 'textarea' | 'checkbox';
  value?: string | number | boolean;
  placeholder?: string;
  options?: { value: string; label: string }[];
}

export function formDialog(title: string, fields: FormField[]): Promise<Record<string, string> | null> {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal" style="max-width:560px">
        <div class="modal-title"></div>
        <div class="form-stack" id="form-fields"></div>
        <div class="modal-actions">
          <button class="btn" id="form-cancel">取消</button>
          <button class="btn btn-primary" id="form-ok">确认</button>
        </div>
      </div>`;
    overlay.querySelector('.modal-title')!.textContent = title;
    const host = overlay.querySelector('#form-fields')!;
    for (const field of fields) {
      const wrap = document.createElement('div');
      wrap.className = 'form-group';
      if (field.type === 'checkbox') {
        wrap.innerHTML = `<label class="check-row"><input type="checkbox" id="f-${field.id}" ${field.value ? 'checked' : ''}><span></span></label>`;
        wrap.querySelector('span')!.textContent = field.label;
      } else if (field.type === 'select') {
        wrap.innerHTML = `<label class="form-label"></label><select class="select" id="f-${field.id}" style="width:100%"></select>`;
        wrap.querySelector('label')!.textContent = field.label;
        const sel = wrap.querySelector('select')!;
        for (const opt of field.options || []) {
          const o = document.createElement('option');
          o.value = opt.value;
          o.textContent = opt.label;
          if (String(field.value ?? '') === opt.value) o.selected = true;
          sel.appendChild(o);
        }
      } else if (field.type === 'textarea') {
        wrap.innerHTML = `<label class="form-label"></label><textarea class="input" id="f-${field.id}" style="width:100%;min-height:72px"></textarea>`;
        wrap.querySelector('label')!.textContent = field.label;
        const ta = wrap.querySelector('textarea')!;
        ta.placeholder = field.placeholder || '';
        ta.value = String(field.value ?? '');
      } else {
        wrap.innerHTML = `<label class="form-label"></label><input class="input" id="f-${field.id}" style="width:100%">`;
        wrap.querySelector('label')!.textContent = field.label;
        const input = wrap.querySelector('input')!;
        input.type = field.type || 'text';
        input.placeholder = field.placeholder || '';
        input.value = String(field.value ?? '');
      }
      host.appendChild(wrap);
    }
    const collect = () => {
      const out: Record<string, string> = {};
      for (const field of fields) {
        const el = overlay.querySelector(`#f-${field.id}`) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
        out[field.id] = field.type === 'checkbox' ? String((el as HTMLInputElement).checked) : el.value;
      }
      return out;
    };
    const close = (v: Record<string, string> | null) => { dismissOverlay(overlay); resolve(v); };
    overlay.querySelector('#form-ok')!.addEventListener('click', () => close(collect()));
    overlay.querySelector('#form-cancel')!.addEventListener('click', () => close(null));
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(null); });
    document.body.appendChild(overlay);
    (overlay.querySelector('input,select,textarea') as HTMLElement | null)?.focus();
  });
}

// 输入弹窗
export function inputDialog(title: string, placeholder = '', value = ''): Promise<string | null> {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal">
        <div class="modal-title" id="dialog-title"></div>
        <div class="form-group">
          <input class="input" id="dialog-input" style="width:100%">
        </div>
        <div class="modal-actions">
          <button class="btn" id="dialog-cancel">取消</button>
          <button class="btn btn-primary" id="dialog-ok">确认</button>
        </div>
      </div>
    `;
    overlay.querySelector('#dialog-title')!.textContent = title;
    const input = overlay.querySelector('#dialog-input') as HTMLInputElement;
    // 用 DOM 属性赋值而不是拼 value="..."：改名对话框传进来的就是旧实例名，
    // 引号一闭合就能往 <input> 上挂 onfocus，而下一行正好 focus()。
    input.placeholder = placeholder;
    input.value = value;
    document.body.appendChild(overlay);
    input.focus();
    input.select();
    overlay.querySelector('#dialog-ok')!.addEventListener('click', () => { dismissOverlay(overlay); resolve(input.value); });
    overlay.querySelector('#dialog-cancel')!.addEventListener('click', () => { dismissOverlay(overlay); resolve(null); });
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { dismissOverlay(overlay); resolve(input.value); }
      if (e.key === 'Escape') { dismissOverlay(overlay); resolve(null); }
    });
    overlay.addEventListener('click', e => { if (e.target === overlay) { dismissOverlay(overlay); resolve(null); } });
  });
}

// 加载指示器：骨架屏比转圈更能撑住布局，也不会让页面看起来卡住
export function showLoading(container: HTMLElement) {
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:12px;max-width:1100px">
      <div class="skeleton" style="height:96px"></div>
      <div class="skeleton" style="height:64px;animation-delay:90ms"></div>
      <div class="skeleton" style="height:64px;animation-delay:180ms"></div>
      <div class="skeleton" style="height:64px;animation-delay:270ms"></div>
    </div>`;
}

/** 骨架屏占位：rows=列表行，cards=卡片网格。比转圈更能撑住版面。 */
export function showSkeleton(container: HTMLElement, kind: 'rows' | 'cards' = 'rows', count = 4) {
  if (kind === 'cards') {
    container.innerHTML = `<div class="grid-list">${'<div class="skeleton" style="height:132px"></div>'.repeat(count)}</div>`;
    return;
  }
  container.innerHTML = `<div style="display:flex;flex-direction:column;gap:10px">${(
    '<div class="skel-row"><div class="skeleton skel-thumb"></div>' +
    '<div style="flex:1;display:flex;flex-direction:column;gap:8px;justify-content:center">' +
    '<div class="skeleton skel-line" style="width:38%"></div>' +
    '<div class="skeleton skel-line" style="width:64%"></div></div></div>'
  ).repeat(count)}</div>`;
}

// 空状态
export function showEmpty(container: HTMLElement, message: string, icon = '📭') {
  container.innerHTML = `
    <div class="empty-state">
      <div class="empty-state-icon">${escapeHtml(icon)}</div>
      <div>${escapeHtml(message)}</div>
    </div>
  `;
}

// 错误状态
export function showError(container: HTMLElement, message: string, onRetry?: () => void) {
  container.innerHTML = `
    <div class="empty-state">
      <div class="empty-state-icon">⚠️</div>
      <div style="color:var(--danger)">${escapeHtml(message)}</div>
      ${onRetry ? '<button class="btn btn-primary" id="retry-btn">重试</button>' : ''}
    </div>
  `;
  if (onRetry) {
    container.querySelector('#retry-btn')?.addEventListener('click', onRetry);
  }
}

// 初始化桥接生命周期（带自动重试）
export function initBridgeLifecycle(onReady: () => void) {
  const statusEl = document.getElementById('bridge-status');
  let retryCount = 0;
  let connected = false;

  function updateStatus(text: string) {
    if (statusEl) statusEl.textContent = '桥接: ' + text;
  }

  /**
   * 退避重试 5 次后放弃。以前放弃就彻底完了——状态栏停在「未连接」，
   * 界面上没有任何重来的入口，用户把 bridge 起好了也只能重开整个应用。
   * 现在把状态栏变成可点的手动重连。
   */
  function offerManualRetry() {
    updateStatus('未连接（点此重连）');
    if (!statusEl) return;
    statusEl.style.cursor = 'pointer';
    statusEl.title = '点击重新连接 Python 桥接服务';
    statusEl.addEventListener('click', () => {
      if (connected) return;
      retryCount = 0;
      statusEl.style.cursor = '';
      statusEl.title = '';
      tryConnect();
    }, { once: true });
  }

  async function tryConnect() {
    if (connected) return;
    updateStatus('连接中...');
    try {
      const health = await bridge.call('get_settings');
      if (health !== undefined) {
        connected = true;
        store.bridgeConnected = true;
        updateStatus('已连接');
        bridge.connectEvents();
        onReady();
        return;
      }
    } catch { /* 重试 */ }
    retryCount++;
    if (retryCount < 5) {
      const delay = Math.min(1000 * Math.pow(2, retryCount - 1), 8000);
      updateStatus('重试中... (' + retryCount + '/5)');
      setTimeout(tryConnect, delay);
    } else {
      offerManualRetry();
      toast('无法连接到 Python 桥接服务，请确保 bridge 已启动，然后点右上角状态重连', 'error');
    }
  }

  setTimeout(tryConnect, 500);
}

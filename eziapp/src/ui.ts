// UI 通用组件与工具函数
import { bridge } from './bridge';
import { store } from './store';
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

function reducedMotion(): boolean {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
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
    const settings = (store.settings || {}) as any;
    if (settings.ui_fly_animation === false || reducedMotion()) {
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

    const t0 = performance.now();
    const tick = (now: number) => {
      const raw = Math.min(1, (now - t0) / duration);
      // InOutCubic
      const t = raw < 0.5 ? 4 * raw * raw * raw : 1 - Math.pow(-2 * raw + 2, 3) / 2;
      const p = bezier(start, control, end, t);
      const size = 44 + (14 - 44) * t;
      const opacity = t < 0.75 ? 1 : Math.max(0, (1 - t) / 0.25);
      ball.style.width = `${size}px`;
      ball.style.height = `${size}px`;
      ball.style.left = `${p.x - size / 2}px`;
      ball.style.top = `${p.y - size / 2}px`;
      ball.style.opacity = String(opacity);
      ball.style.borderRadius = `${10 + (size / 2 - 10) * t}px`;
      ball.style.fontSize = `${Math.max(8, size * 0.42)}px`;
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
export function toast(message: string, type: 'info' | 'success' | 'error' | 'warning' = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('leaving');
    setTimeout(() => el.remove(), 300);
  }, duration);
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
    overlay.querySelector('#confirm-ok')!.addEventListener('click', () => { overlay.remove(); resolve(true); });
    overlay.querySelector('#confirm-cancel')!.addEventListener('click', () => { overlay.remove(); resolve(false); });
    overlay.addEventListener('click', e => { if (e.target === overlay) { overlay.remove(); resolve(false); } });
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
    const close = (v: Record<string, string> | null) => { overlay.remove(); resolve(v); };
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
    overlay.querySelector('#dialog-ok')!.addEventListener('click', () => { overlay.remove(); resolve(input.value); });
    overlay.querySelector('#dialog-cancel')!.addEventListener('click', () => { overlay.remove(); resolve(null); });
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter') { overlay.remove(); resolve(input.value); }
      if (e.key === 'Escape') { overlay.remove(); resolve(null); }
    });
    overlay.addEventListener('click', e => { if (e.target === overlay) { overlay.remove(); resolve(null); } });
  });
}

export type PreflightItem = { level?: string; code?: string; title?: string; detail?: string };
export type CrashAction = { id?: string; label?: string; mods?: string[]; major?: number; version?: string; instance?: string; memory_mb?: number };

/** 启动预检：有 error 阻止；仅 warn 可继续。 */
export function preflightDialog(
  items: PreflightItem[],
): Promise<'block' | 'continue' | 'cancel'> {
  const errors = items.filter(i => i.level === 'error');
  const warns = items.filter(i => i.level === 'warn');
  if (!errors.length && !warns.length) return Promise.resolve('continue');

  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    const blocked = errors.length > 0;
    const rows = (blocked ? errors : warns)
      .map(i => `<div style="margin-bottom:10px"><strong>${escapeHtml(i.title || i.code || '')}</strong><div style="font-size:12px;color:var(--text-secondary);white-space:pre-wrap;margin-top:4px">${escapeHtml(i.detail || '')}</div></div>`)
      .join('');
    overlay.innerHTML = `
      <div class="modal" style="max-width:560px">
        <div class="modal-title" id="pf-title"></div>
        <div id="pf-body" style="max-height:360px;overflow:auto;margin-bottom:12px"></div>
        <div class="modal-actions" id="pf-actions"></div>
      </div>
    `;
    (overlay.querySelector('#pf-title') as HTMLElement).textContent = blocked ? '启动预检未通过' : '启动预检有警告';
    (overlay.querySelector('#pf-body') as HTMLElement).innerHTML = rows;
    const actions = overlay.querySelector('#pf-actions') as HTMLElement;
    if (blocked) {
      actions.innerHTML = `<button class="btn btn-primary" id="pf-ok">知道了</button>`;
      actions.querySelector('#pf-ok')!.addEventListener('click', () => { overlay.remove(); resolve('block'); });
    } else {
      actions.innerHTML = `
        <button class="btn" id="pf-cancel">取消</button>
        <button class="btn btn-primary" id="pf-go">继续启动</button>
      `;
      actions.querySelector('#pf-cancel')!.addEventListener('click', () => { overlay.remove(); resolve('cancel'); });
      actions.querySelector('#pf-go')!.addEventListener('click', () => { overlay.remove(); resolve('continue'); });
    }
    overlay.addEventListener('click', e => {
      if (e.target === overlay) { overlay.remove(); resolve(blocked ? 'block' : 'cancel'); }
    });
    document.body.appendChild(overlay);
  });
}

/** 崩溃报告 + 一键修复动作。返回 true 表示用户点了「重新启动」。 */
export function crashDialog(report: {
  title?: string; headline?: string; detail?: string; help?: string;
  actions?: CrashAction[]; task_id?: string;
  instance?: string; version?: string;
}): Promise<boolean> {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    const actions = Array.isArray(report.actions) ? report.actions : [];
    const canRelaunch = !!(report.instance && report.version);
    const actBtns = actions.map((a, i) =>
      `<button class="btn" data-act="${i}">${escapeHtml(a.label || a.id || '修复')}</button>`
    ).join('');
    overlay.innerHTML = `
      <div class="modal" style="max-width:640px">
        <div class="modal-title" id="cr-title"></div>
        <div id="cr-head" style="font-size:13px;margin-bottom:8px;font-weight:600"></div>
        <pre id="cr-detail" style="max-height:280px;overflow:auto;font-size:12px;white-space:pre-wrap;background:var(--bg-secondary,#f5f5f5);padding:10px;border-radius:8px;margin:0 0 10px"></pre>
        <div id="cr-help" style="font-size:12px;color:var(--text-secondary);margin-bottom:10px"></div>
        <div id="cr-acts" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px">${actBtns}</div>
        <div class="modal-actions">
          ${canRelaunch ? '<button class="btn" id="cr-relaunch">重新启动</button>' : ''}
          <button class="btn btn-primary" id="cr-ok">确定</button>
        </div>
      </div>
    `;
    (overlay.querySelector('#cr-title') as HTMLElement).textContent = report.title || 'Minecraft 出现错误';
    const head = overlay.querySelector('#cr-head') as HTMLElement;
    if (report.headline && report.headline !== report.title) head.textContent = report.headline;
    else head.style.display = 'none';
    (overlay.querySelector('#cr-detail') as HTMLElement).textContent = report.detail || '';
    (overlay.querySelector('#cr-help') as HTMLElement).textContent = report.help || '';
    overlay.querySelectorAll('[data-act]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const idx = Number((btn as HTMLElement).dataset.act);
        const action = actions[idx];
        if (!action) return;
        (btn as HTMLButtonElement).disabled = true;
        try {
          const result = await bridge.call<{ ok?: boolean; message?: string }>('apply_crash_action', {
            action, report,
          });
          if (result?.ok) {
            toast(result.message || '已处理', 'success');
            if (action.id === 'disable_mods') (btn as HTMLButtonElement).textContent = '已禁用';
          } else {
            toast(result?.message || '操作失败', 'error');
            (btn as HTMLButtonElement).disabled = false;
          }
        } catch (e: any) {
          toast(e?.message || '操作失败', 'error');
          (btn as HTMLButtonElement).disabled = false;
        }
      });
    });
    const close = (relaunch: boolean) => { overlay.remove(); resolve(relaunch); };
    overlay.querySelector('#cr-ok')!.addEventListener('click', () => close(false));
    overlay.querySelector('#cr-relaunch')?.addEventListener('click', () => close(true));
    overlay.addEventListener('click', e => { if (e.target === overlay) close(false); });
    document.body.appendChild(overlay);
  });
}

// 加载指示器
export function showLoading(container: HTMLElement) {
  container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;padding:48px;gap:12px"><div class="loading-spinner"></div><span>加载中...</span></div>';
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

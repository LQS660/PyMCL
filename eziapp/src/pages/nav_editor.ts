/**
 * 自定义侧栏对话框：排法 / 顺序 / 显隐 / 固定项 / 分区成员 / 宽度。
 *
 * 与 Qt 版 app/pages/layout_settings.py 的 SidebarEditorDialog + SectionEditorDialog
 * 同一套语义（含「分组排法下一级项排序不生效，顺序直接拖侧栏调」「每栏至少留一项」
 * 这两条），写回的也是同一批 ui_nav_* 键——两边改完，对面打开看到的是同一个侧栏。
 */

import { dismissOverlay, toast } from '../ui';
import {
  ALL_SUB_KEYS, DEFAULT_NAV_HIDDEN, DEFAULT_NAV_ORDER, DEFAULT_NAV_PINNED,
  DEFAULT_NAV_STYLE, NAV_SPECS, NAV_STYLE_GROUPED, NAV_STYLE_LABELS, SECTION_IDS,
  SUB_TITLES, TOP_KEYS, defaultNavPatch, groupedLayout, groupedLayoutPatch,
  mergeNavOrder, navStyle, pinnedFromConfig, sectionMembersFromConfig,
  type NavConfig, type NavStyle, type SectionId,
} from '../nav_model';

const SECTION_TITLES: Record<SectionId, string> = { download: '游戏栏', more: '更多栏' };

const escapeHtml = (text: string) => text.replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] || c));

interface EditorState {
  style: NavStyle;
  topOrder: string[];
  hidden: Set<string>;
  pinned: string[];
  members: Record<SectionId, string[]>;
  width: number;
  forceDefaults: boolean;
}

function initialState(cfg: NavConfig): EditorState {
  const stored = (Array.isArray(cfg.ui_nav_order) ? cfg.ui_nav_order : [])
    .map(String).filter((k) => (TOP_KEYS as readonly string[]).includes(k));
  const topOrder = [...stored];
  for (const key of TOP_KEYS) if (!topOrder.includes(key)) topOrder.push(key);
  const width = Number(cfg.ui_sidebar_width) || 232;
  return {
    style: navStyle(cfg),
    topOrder,
    hidden: new Set((Array.isArray(cfg.ui_nav_hidden) ? cfg.ui_nav_hidden : []).map(String)),
    pinned: pinnedFromConfig(cfg),
    members: sectionMembersFromConfig(cfg),
    width: Math.max(140, Math.min(320, width)),
    forceDefaults: false,
  };
}

function move<T>(list: T[], index: number, delta: number) {
  const to = index + delta;
  if (to < 0 || to >= list.length) return;
  [list[index], list[to]] = [list[to], list[index]];
}

function rowHtml(label: string, index: number, total: number, scope: string, extra = '',
                 sortable = true): string {
  // 分组档的固定项排不了序（顺序归各个分组管）：干脆不画箭头，
  // 比画两颗按了没反应的强
  const arrows = sortable ? `
    <button class="btn btn-sm" data-move="${scope}:${index}:-1"${index === 0 ? ' disabled' : ''}>↑</button>
    <button class="btn btn-sm" data-move="${scope}:${index}:1"${index === total - 1 ? ' disabled' : ''}>↓</button>` : '';
  return `<div class="nav-edit-row">${arrows}
    <span class="nav-edit-name">${escapeHtml(label)}</span>${extra}
  </div>`;
}

export function showSidebarEditor(cfg: NavConfig): Promise<Record<string, unknown> | null> {
  const state = initialState(cfg);
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal" style="max-width:620px">
        <div class="modal-title">自定义侧栏</div>
        <div class="nav-edit-body" id="nav-edit-body"></div>
        <div class="modal-actions">
          <button class="btn" id="nav-edit-reset">恢复默认侧栏</button>
          <button class="btn" id="nav-edit-cancel">取消</button>
          <button class="btn btn-primary" id="nav-edit-ok">确定</button>
        </div>
      </div>`;

    const body = overlay.querySelector<HTMLElement>('#nav-edit-body')!;

    const render = () => {
      const grouped = state.style === NAV_STYLE_GROUPED;
      const tops = state.topOrder.map((key, i) => rowHtml(
        NAV_SPECS[key]?.label || key, i, state.topOrder.length, 'top',
        `<label class="check-row"><input type="checkbox" data-hide="${key}"${state.hidden.has(key) ? '' : ' checked'}><span>显示</span></label>`,
      )).join('');
      const pins = state.pinned.length
        ? state.pinned.map((key, i) => rowHtml(
          SUB_TITLES[key] || key, i, state.pinned.length, 'pin',
          `<button class="btn btn-sm" data-unpin="${key}">取消固定</button>`, !grouped)).join('')
        : '<div class="nav-edit-empty">暂无固定项</div>';
      const sections = SECTION_IDS.map((sec) => {
        const keys = state.members[sec];
        const other: SectionId = sec === 'download' ? 'more' : 'download';
        const rows = keys.map((key, i) => rowHtml(
          SUB_TITLES[key] || key, i, keys.length, `sec:${sec}`,
          `<button class="btn btn-sm" data-pin="${key}">固定到侧栏</button>`
          + `<button class="btn btn-sm" data-swap="${sec}:${key}"${keys.length <= 1 ? ' disabled' : ''}>移到「${SECTION_TITLES[other].replace('栏', '')}」</button>`,
        )).join('') || '<div class="nav-edit-empty">这一栏空了</div>';
        return `<div class="nav-edit-group"><div class="nav-edit-head">${SECTION_TITLES[sec]}</div>${rows}</div>`;
      }).join('');
      body.innerHTML = `
        <div class="form-group">
          <label class="form-label">侧栏排法</label>
          <select class="select" id="nav-edit-style" style="width:100%">
            ${(Object.keys(NAV_STYLE_LABELS) as NavStyle[]).map((key) =>
              `<option value="${key}"${key === state.style ? ' selected' : ''}>${escapeHtml(NAV_STYLE_LABELS[key])}</option>`).join('')}
          </select>
          <div class="nav-edit-hint">${grouped
            ? '分组排法按「账户 / 游戏 / 通用」分组，下面那份一级项排序不生效（顺序直接拖侧栏调整）；勾掉的项照样不显示。'
            : '精简排法：一级项按下面的顺序排，固定的子页跟它们混排。'}</div>
        </div>
        <div class="nav-edit-group${grouped ? ' disabled' : ''}">
          <div class="nav-edit-head">一级项</div>${tops}
        </div>
        <div class="nav-edit-group">
          <div class="nav-edit-head">固定到侧栏的子页</div>${pins}
        </div>
        ${sections}
        <div class="form-group">
          <label class="form-label">侧栏宽度</label>
          <input class="input" id="nav-edit-width" type="number" min="140" max="320" value="${state.width}" style="width:120px">
        </div>`;
      bind();
    };

    const bind = () => {
      body.querySelector<HTMLSelectElement>('#nav-edit-style')?.addEventListener('change', (ev) => {
        state.style = (ev.target as HTMLSelectElement).value as NavStyle;
        render();
      });
      body.querySelector<HTMLInputElement>('#nav-edit-width')?.addEventListener('change', (ev) => {
        const raw = parseInt((ev.target as HTMLInputElement).value, 10);
        state.width = Math.max(140, Math.min(320, Number.isFinite(raw) ? raw : 232));
      });
      body.querySelectorAll<HTMLElement>('[data-move]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const [scope, idx, delta] = btn.dataset.move!.split(':').slice(-3);
          const list = scope === 'top' ? state.topOrder
            : scope === 'pin' ? state.pinned
              : state.members[scope as SectionId];
          move(list, Number(idx), Number(delta));
          render();
        });
      });
      body.querySelectorAll<HTMLInputElement>('[data-hide]').forEach((box) => {
        box.addEventListener('change', () => {
          const key = box.dataset.hide!;
          if (box.checked) state.hidden.delete(key);
          else state.hidden.add(key);
        });
      });
      body.querySelectorAll<HTMLElement>('[data-unpin]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const key = btn.dataset.unpin!;
          state.pinned = state.pinned.filter((k) => k !== key);
          const sec = SECTION_IDS.find((s) => state.members[s].includes(key));
          if (!sec) state.members.more.push(key);
          render();
        });
      });
      body.querySelectorAll<HTMLElement>('[data-pin]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const key = btn.dataset.pin!;
          const sec = SECTION_IDS.find((s) => state.members[s].includes(key));
          // 每栏至少留一项：移空的那栏点进去就是空壳（对齐 Qt _take_from_section）
          if (sec && state.members[sec].length <= 1) {
            toast('该分区只剩这一个子页，移走会变空栏', 'warning');
            return;
          }
          if (sec) state.members[sec] = state.members[sec].filter((k) => k !== key);
          if (!state.pinned.includes(key)) state.pinned.push(key);
          render();
        });
      });
      body.querySelectorAll<HTMLElement>('[data-swap]').forEach((btn) => {
        btn.addEventListener('click', () => {
          const [sec, key] = btn.dataset.swap!.split(':') as [SectionId, string];
          const other: SectionId = sec === 'download' ? 'more' : 'download';
          if (state.members[sec].length <= 1) return;
          state.members[sec] = state.members[sec].filter((k) => k !== key);
          state.members[other].push(key);
          render();
        });
      });
    };

    const close = (patch: Record<string, unknown> | null) => {
      dismissOverlay(overlay);
      resolve(patch);
    };

    overlay.querySelector('#nav-edit-reset')!.addEventListener('click', () => {
      state.style = DEFAULT_NAV_STYLE;
      state.topOrder = [...DEFAULT_NAV_ORDER.filter((k) => (TOP_KEYS as readonly string[]).includes(k))];
      for (const key of TOP_KEYS) if (!state.topOrder.includes(key)) state.topOrder.push(key);
      state.hidden = new Set(DEFAULT_NAV_HIDDEN);
      state.pinned = [...DEFAULT_NAV_PINNED];
      state.members = sectionMembersFromConfig({ ui_nav_pinned: state.pinned, ui_nav_style: 'compact' });
      state.width = 188;
      state.forceDefaults = true;
      render();
    });
    overlay.querySelector('#nav-edit-cancel')!.addEventListener('click', () => close(null));
    overlay.querySelector('#nav-edit-ok')!.addEventListener('click', () => {
      const patch = buildPatch(cfg, state);
      if (!patch) return;
      close(patch);
    });
    overlay.addEventListener('click', (ev) => { if (ev.target === overlay) close(null); });

    document.body.appendChild(overlay);
    render();
  });
}

function buildPatch(cfg: NavConfig, state: EditorState): Record<string, unknown> | null {
  if (state.forceDefaults) {
    return { ...defaultNavPatch(), ui_sidebar_width: state.width };
  }
  const hidden = [...state.hidden].sort();
  const patch: Record<string, unknown> = {
    ui_nav_style: state.style,
    ui_nav_hidden: hidden,
    ui_sidebar_width: state.width,
  };
  if (state.style === NAV_STYLE_GROUPED) {
    // 分组档的顺序归各组管，这里只落「哪些子页还在组里」：摘掉取消固定的，
    // 新固定的插在「更多」前面（对齐 Qt SidebarEditorDialog 与拖拽那条路）
    const kept = new Set(state.pinned);
    const groups = groupedLayout(cfg);
    for (const group of groups) {
      group.keys = group.keys.filter((k) => !ALL_SUB_KEYS.has(k) || kept.has(k));
    }
    for (const key of state.pinned) {
      if (groups.some((g) => g.keys.includes(key))) continue;
      const host = groups.find((g) => g.keys.includes('more')) ?? groups[groups.length - 1];
      const at = host.keys.indexOf('more');
      host.keys.splice(at < 0 ? host.keys.length : at, 0, key);
    }
    Object.assign(patch, groupedLayoutPatch(groups));
    patch.ui_section_members = {
      download: state.members.download.filter((k) => !kept.has(k)),
      more: state.members.more.filter((k) => !kept.has(k)),
    };
    return patch;
  }
  const visible = state.topOrder.filter((key) => !state.hidden.has(key));
  if (!visible.length) {
    toast('至少留一个一级项，否则侧栏空了没法导航', 'warning');
    return null;
  }
  if (SECTION_IDS.some((sec) => !state.members[sec].length)) {
    toast('每栏至少保留一个子页', 'warning');
    return null;
  }
  patch.ui_nav_order = mergeNavOrder(cfg, state.topOrder, state.pinned);
  patch.ui_nav_pinned = [...state.pinned];
  patch.ui_section_members = {
    download: state.members.download.filter((k) => !state.pinned.includes(k)),
    more: state.members.more.filter((k) => !state.pinned.includes(k)),
  };
  return patch;
}

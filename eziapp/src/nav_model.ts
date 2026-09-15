/**
 * 侧栏编排：数据模型 + 纯逻辑（不碰 DOM，可在 node 里直接跑）。
 *
 * 与 Python 侧 app/main_window.py 的这几个函数逐条对齐：
 * nav_style / section_members_from_config / pinned_from_config /
 * grouped_nav_items / nav_items_from_config / unpin_nav_config / ensure_default_nav。
 * 两端读写的是同一份 config.json 的 ui_nav_* 键，算法不一致就会出现
 * 「在 Qt 里排好的侧栏，网页版打开是另一套」这类只有用户能发现的偏差。
 *
 * 键名用 Qt 那一套（account / instance / version…），到页面路由那一步再
 * 映射成 eziapp 的 PageKey，见 PAGE_FOR_NAV_KEY。
 */

import type { PageKey } from './router';

export type NavStyle = 'compact' | 'grouped';
export type SectionId = 'download' | 'more';

/** get_settings 回来的那一份（只取侧栏用得上的键）。 */
export interface NavConfig {
  ui_nav_style?: unknown;
  ui_nav_order?: unknown;
  ui_nav_pinned?: unknown;
  ui_nav_hidden?: unknown;
  ui_nav_groups?: unknown;
  ui_nav_defaults?: unknown;
  ui_section_members?: unknown;
  [key: string]: unknown;
}

export const NAV_STYLE_COMPACT: NavStyle = 'compact';
export const NAV_STYLE_GROUPED: NavStyle = 'grouped';
export const NAV_STYLE_LABELS: Record<NavStyle, string> = {
  compact: '精简（启动 / 游戏 / 版本管理）',
  grouped: '分组（账户 / 游戏 / 通用）',
};

/** 分区默认成员（子页归属可由 ui_section_members 自定义：哪栏、栏内顺序）。 */
export const SUB_DEFAULT_MEMBERS: Record<SectionId, string[]> = {
  download: ['version', 'mod', 'modpack', 'datapack', 'resource', 'shader', 'world', 'java'],
  more: ['instance', 'mods', 'account', 'multiplayer', 'servers', 'playtime', 'feedback', 'settings'],
};
export const SECTION_IDS: SectionId[] = ['download', 'more'];
export const ALL_SUB_KEYS: ReadonlySet<string> = new Set(
  SECTION_IDS.flatMap((sec) => SUB_DEFAULT_MEMBERS[sec]));
export const TOP_KEYS = ['launch', 'download', 'ai', 'more', 'tasks'] as const;

/** 子页标题。instance 这个键只剩历史含义，打开的是版本管理。 */
export const SUB_TITLES: Record<string, string> = {
  version: '原版游戏', mod: 'Mod', modpack: '整合包', datapack: '数据包',
  resource: '资源包', shader: '光影包', world: '世界', java: 'Java',
  instance: '版本管理', mods: '模组', account: '账号', multiplayer: '联机',
  servers: '服务器', playtime: '时长', feedback: '反馈', settings: '设置',
};

/** 一级项的标题与图标名（图标名对应 main.ts 的 ICONS 表）。 */
export const NAV_SPECS: Record<string, { label: string; icon: string }> = {
  launch: { label: '启动', icon: 'launch' },
  download: { label: '游戏', icon: 'download' },
  ai: { label: 'AI 助手', icon: 'ai' },
  more: { label: '更多', icon: 'more' },
  tasks: { label: '下载任务', icon: 'tasks' },
};

/** 子页图标名。 */
export const SUB_ICONS: Record<string, string> = {
  version: 'grid', mod: 'mods', modpack: 'grid', datapack: 'grid',
  resource: 'grid', shader: 'grid', world: 'grid', java: 'java',
  instance: 'instances', mods: 'mods', account: 'accounts',
  multiplayer: 'multiplayer', servers: 'servers', playtime: 'playtime',
  feedback: 'feedback', settings: 'settings',
};

export const NAV_DEFAULTS_VERSION = '2026.09-ai-visible';
export const DEFAULT_NAV_ORDER = ['launch', 'download', 'instance', 'ai', 'more', 'settings', 'tasks'];
export const DEFAULT_NAV_PINNED = ['instance', 'settings'];
export const DEFAULT_NAV_HIDDEN: string[] = [];
/** 历史上的出厂三件套：老用户还照着上一版出厂样子用时也算「没动过」。 */
export const LEGACY_NAV_FACTORIES: Record<string, string[]>[] = [
  // 2026.09-grouped：AI 出厂藏着，精简序列里也没有它
  {
    ui_nav_order: ['launch', 'download', 'instance', 'more', 'settings', 'tasks'],
    ui_nav_pinned: ['instance', 'settings'],
    ui_nav_hidden: ['ai'],
  },
];
/** 这些键排在分隔线以下，靠侧栏底部。 */
export const BOTTOM_KEYS = ['ai', 'more', 'settings', 'tasks'];

export const GROUPED_NAV: [string, string[]][] = [
  ['账户', ['account']],
  ['游戏', ['launch', 'instance', 'download']],
  ['通用', ['settings', 'multiplayer', 'ai', 'more', 'tasks']],
];
/** 组里另用的名字：「游戏」组底下再写一项「游戏」会读成套娃。 */
export const GROUPED_LABELS: Record<string, string> = { download: '下载', multiplayer: '多人联机' };
export const DEFAULT_NAV_STYLE: NavStyle = NAV_STYLE_GROUPED;

export interface NavGroup { title: string; keys: string[] }

/** 侧栏一级键 / 子页键 → eziapp 路由页。 */
export const PAGE_FOR_NAV_KEY: Record<string, PageKey> = {
  launch: 'launch', download: 'downloads', ai: 'ai', more: 'more', tasks: 'tasks',
  version: 'vanilla', mod: 'mods-catalog', modpack: 'modpacks', datapack: 'datapacks',
  resource: 'resourcepacks', shader: 'shaders', world: 'worlds', java: 'java',
  instance: 'instances', mods: 'mods', account: 'accounts', multiplayer: 'multiplayer',
  servers: 'servers', playtime: 'playtime', feedback: 'feedback', settings: 'settings',
};

/** 反向表。tools 是 eziapp 独有的页，Qt 把工具并进了设置，高亮跟着设置走。 */
export const NAV_KEY_FOR_PAGE: Record<string, string> = (() => {
  const out: Record<string, string> = { tools: 'settings' };
  for (const [navKey, page] of Object.entries(PAGE_FOR_NAV_KEY)) out[page] = navKey;
  return out;
})();

export type NavEntry =
  | { kind: 'header'; label: string }
  | { kind: 'stretch' }
  | { kind: 'item'; key: string; page: PageKey; label: string; icon: string; top: boolean; draggable: boolean };

const strList = (raw: unknown): string[] =>
  (Array.isArray(raw) ? raw : []).filter((v): v is string => typeof v === 'string' && v !== '');

export function navStyle(cfg: NavConfig | null | undefined): NavStyle {
  const style = String(cfg?.ui_nav_style ?? '') as NavStyle;
  return style in NAV_STYLE_LABELS ? style : DEFAULT_NAV_STYLE;
}

export function navLabel(key: string): string {
  return NAV_SPECS[key]?.label ?? SUB_TITLES[key] ?? key;
}

export function navIcon(key: string): string {
  return NAV_SPECS[key]?.icon ?? SUB_ICONS[key] ?? 'grid';
}

/**
 * 读 ui_section_members：{download: [key…], more: [key…]}。
 * 非法键剔除、重复去重、漏掉的子页按默认归属补齐，顺序保留用户排列。
 */
export function sectionMembersFromConfig(cfg: NavConfig | null | undefined): Record<SectionId, string[]> {
  const pinned = new Set(pinnedFromConfig(cfg));
  const raw = (cfg?.ui_section_members ?? null) as Record<string, unknown> | null;
  const result = { download: [] as string[], more: [] as string[] };
  const seen = new Set<string>();
  for (const sec of SECTION_IDS) {
    for (const k of strList(raw && typeof raw === 'object' ? raw[sec] : null)) {
      // 固定到侧栏的子页不属于任何分区（拖出去 = 移动），
      // 配置里残留的成员记录也一并忽略
      if (ALL_SUB_KEYS.has(k) && !seen.has(k) && !pinned.has(k)) {
        seen.add(k);
        result[sec].push(k);
      }
    }
  }
  for (const sec of SECTION_IDS) {
    for (const k of SUB_DEFAULT_MEMBERS[sec]) {
      if (!seen.has(k) && !pinned.has(k)) {
        seen.add(k);
        result[sec].push(k);
      }
    }
  }
  return result;
}

export function defaultSectionFor(key: string): SectionId {
  for (const sec of SECTION_IDS) {
    if (SUB_DEFAULT_MEMBERS[sec].includes(key)) return sec;
  }
  return 'more';
}

/**
 * 分组排法的分组与成员：用户拖过就以 ui_nav_groups 为准，没动过用出厂的。
 * 一级键缺席要补回来——漏掉它就等于这一页在界面上彻底没了入口。
 */
export function groupedLayout(cfg: NavConfig | null | undefined): NavGroup[] {
  const raw = cfg?.ui_nav_groups;
  const groups: NavGroup[] = [];
  const seen = new Set<string>();
  if (Array.isArray(raw)) {
    for (const grp of raw) {
      if (!grp || typeof grp !== 'object') continue;
      const title = String((grp as NavGroup).title ?? '').trim();
      if (!title) continue;
      const keys = strList((grp as NavGroup).keys).filter((k) => {
        if (!(TOP_KEYS as readonly string[]).includes(k) && !ALL_SUB_KEYS.has(k)) return false;
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      });
      groups.push({ title, keys });
    }
  }
  if (!groups.some((g) => g.keys.length)) {
    return GROUPED_NAV.map(([title, keys]) => ({ title, keys: [...keys] }));
  }
  const missing = TOP_KEYS.filter((k) => !seen.has(k));
  if (missing.length) groups[groups.length - 1].keys.push(...missing);
  return groups;
}

/** 分组表写回配置用的那一份。 */
export function groupedLayoutPatch(groups: NavGroup[]): Record<string, unknown> {
  return { ui_nav_groups: groups.map((g) => ({ title: g.title, keys: [...g.keys] })) };
}

/** 把 key 挪到 target 的前/后（可跨组）。目标不在表里就原样不动。 */
export function moveWithinGroups(
  groups: NavGroup[], key: string, target: string, before: boolean,
): boolean {
  // 先确认目标存在再摘 key：反过来写的话，一次失败的拖拽就能让这一项消失
  if (key === target || !groups.some((g) => g.keys.includes(target))) return false;
  for (const group of groups) {
    const at = group.keys.indexOf(key);
    if (at >= 0) group.keys.splice(at, 1);
  }
  for (const group of groups) {
    const at = group.keys.indexOf(target);
    if (at >= 0) {
      group.keys.splice(at + (before ? 0 : 1), 0, key);
      return true;
    }
  }
  return false;
}

/** 固定到顶级侧栏的分区子页 key（拖拽固定，非法键过滤）。 */
export function pinnedFromConfig(cfg: NavConfig | null | undefined): string[] {
  const hidden = new Set(strList(cfg?.ui_nav_hidden));
  if (navStyle(cfg) === NAV_STYLE_GROUPED) {
    // 分组排法的固定项就是各组里的子页成员，ui_nav_pinned 在这一档不参与
    return groupedLayout(cfg)
      .flatMap((g) => g.keys)
      .filter((k) => ALL_SUB_KEYS.has(k) && !hidden.has(k));
  }
  const picked: string[] = [];
  const seen = new Set<string>();
  for (const k of strList(cfg?.ui_nav_pinned)) {
    if (ALL_SUB_KEYS.has(k) && !seen.has(k)) {
      seen.add(k);
      picked.push(k);
    }
  }
  return picked;
}

function itemEntry(key: string, label: string, draggable: boolean): NavEntry {
  const top = (TOP_KEYS as readonly string[]).includes(key);
  return {
    kind: 'item', key, page: PAGE_FOR_NAV_KEY[key] ?? 'launch',
    label, icon: navIcon(key), top, draggable,
  };
}

/** HMCL 式分组侧栏。隐藏项照 ui_nav_hidden 走，整组空了连标题一起不出。 */
export function groupedNavItems(cfg: NavConfig | null | undefined): NavEntry[] {
  const hidden = new Set(strList(cfg?.ui_nav_hidden));
  const items: NavEntry[] = [];
  for (const { title, keys } of groupedLayout(cfg)) {
    const visible = keys.filter((k) => !hidden.has(k));
    if (!visible.length) continue;
    items.push({ kind: 'header', label: title });
    for (const key of visible) {
      items.push(itemEntry(key, GROUPED_LABELS[key] ?? navLabel(key), false));
    }
  }
  return items;
}

/**
 * 生成侧栏条目：一级项与固定的分区子页按 ui_nav_order 混排。
 *
 * ui_nav_order 是完整序列（可同时含一级键和固定子页键）；没进序列的固定
 * 子页插在「更多」前（都不在则插在「下载任务」前 / 末尾），一级键缺失自动补到末尾。
 */
export function navItemsFromConfig(cfg: NavConfig | null | undefined): NavEntry[] {
  if (navStyle(cfg) === NAV_STYLE_GROUPED) return groupedNavItems(cfg);
  const raw = strList(cfg?.ui_nav_order);
  const pinned = pinnedFromConfig(cfg);
  const hidden = new Set(strList(cfg?.ui_nav_hidden));
  const order: string[] = [];
  for (const k of raw) {
    if ((TOP_KEYS as readonly string[]).includes(k) && !order.includes(k)) order.push(k);
    else if (pinned.includes(k) && !order.includes(k)) order.push(k);
  }
  for (const k of TOP_KEYS) if (!order.includes(k)) order.push(k);
  // 缺席的固定子页：插到锚点前
  const late = pinned.filter((k) => !order.includes(k));
  if (late.length) {
    const anchor = ['more', 'tasks'].find((a) => order.includes(a));
    if (anchor !== undefined) order.splice(order.indexOf(anchor), 0, ...late);
    else order.push(...late);
  }
  const visible = order.filter((k) => !((TOP_KEYS as readonly string[]).includes(k) && hidden.has(k)));
  // 分隔线插在第一个「底部键」之前，它和它后面的都被推到侧栏最下方
  let splitAt = visible.findIndex((k) => BOTTOM_KEYS.includes(k));
  if (splitAt <= 0) splitAt = -1;
  const items: NavEntry[] = [];
  visible.forEach((key, i) => {
    if (i === splitAt) items.push({ kind: 'stretch' });
    items.push(itemEntry(key, navLabel(key), true));
  });
  return items;
}

const NAV_FACTORY: Record<string, string[]> = {
  ui_nav_order: DEFAULT_NAV_ORDER,
  ui_nav_pinned: DEFAULT_NAV_PINNED,
  ui_nav_hidden: DEFAULT_NAV_HIDDEN,
};

/**
 * 侧栏还是**某一版**出厂那一套（没排过、没藏过、没另外固定过）。
 * 只跟当前版比是不够的：上一版出厂值同样是用户没动过的样子。
 */
export function navUntouched(cfg: NavConfig | null | undefined): boolean {
  const stored = Object.fromEntries(
    Object.keys(NAV_FACTORY).map((key) => [key, strList(cfg?.[key])]));
  return [NAV_FACTORY, ...LEGACY_NAV_FACTORIES].some((factory) =>
    Object.entries(factory).every(([key, value]) => {
      const seq = stored[key];
      return !seq.length || (seq.length === value.length && seq.every((v, i) => v === value[i]));
    }));
}

/** 出厂侧栏（「恢复默认侧栏」与首次写入都用它）。 */
export function defaultNavPatch(): Record<string, unknown> {
  return {
    ui_nav_order: [...DEFAULT_NAV_ORDER],
    ui_nav_pinned: [...DEFAULT_NAV_PINNED],
    ui_nav_hidden: [...DEFAULT_NAV_HIDDEN],
    ui_nav_style: DEFAULT_NAV_STYLE,
    ui_nav_defaults: NAV_DEFAULTS_VERSION,
    ui_nav_groups: null,
    ui_section_members: null,
  };
}

/** 侧栏上真点得进去的分区。被隐藏的分区等于不存在。 */
export function visibleSections(cfg: NavConfig | null | undefined): SectionId[] {
  const keys = new Set(navItemsFromConfig(cfg)
    .filter((it) => it.kind === 'item').map((it) => (it as { key: string }).key));
  return SECTION_IDS.filter((sec) => keys.has(sec));
}

/**
 * 取消固定并把子页写回某个分区，返回它**真正**落到的分区（null = 没做）。
 *
 * 对齐 Qt unpin_nav_config：落点只能是侧栏上点得进去的分区——放回一个被隐藏
 * 的分区，这一页在界面上就彻底消失了，侧栏没有它，也没有任何落点能把它拖回来。
 * 两个分区都藏着时把落点那个放出来，否则它落地即失踪。
 */
export function unpinNavConfig(
  cfg: NavConfig | null | undefined, key: string,
  backSection?: SectionId | null, index = -1,
): { patch: Record<string, unknown>; section: SectionId } | null {
  const pinned = pinnedFromConfig(cfg);
  if (!pinned.includes(key)) return null;
  const nextPinned = pinned.filter((k) => k !== key);
  const patch: Record<string, unknown> = {};
  let probe: NavConfig;
  if (navStyle(cfg) === NAV_STYLE_GROUPED) {
    // 分组档的固定项就是组成员，从组里摘掉才算取消固定
    const groups = groupedLayout(cfg);
    for (const group of groups) {
      const at = group.keys.indexOf(key);
      if (at >= 0) group.keys.splice(at, 1);
    }
    Object.assign(patch, groupedLayoutPatch(groups));
    probe = { ...(cfg || {}), ...patch };
  } else {
    patch.ui_nav_pinned = nextPinned;
    probe = { ...(cfg || {}), ui_nav_pinned: nextPinned };
  }
  // 固定项不属于任何分区，成员表必须在改完 pinned 之后再读
  const members = sectionMembersFromConfig(probe);
  let dest: SectionId = backSection && SECTION_IDS.includes(backSection)
    ? backSection
    // 没指定就回它现在的归属（用户在「自定义分区」里挪过的以那份为准）
    : SECTION_IDS.find((sec) => members[sec].includes(key)) ?? defaultSectionFor(key);
  let at = index;
  const visible = visibleSections(probe);
  if (!visible.includes(dest)) {
    if (visible.length) {
      dest = visible[0];
      at = -1; // 换了个家，原来那个落点位序没有意义
    } else {
      patch.ui_nav_hidden = strList(cfg?.ui_nav_hidden).filter((k) => k !== dest);
    }
  }
  const nextMembers: Record<SectionId, string[]> = {
    download: members.download.filter((k) => k !== key),
    more: members.more.filter((k) => k !== key),
  };
  const bucket = nextMembers[dest];
  bucket.splice(at >= 0 && at <= bucket.length ? at : bucket.length, 0, key);
  patch.ui_section_members = nextMembers;
  return { section: dest, patch };
}

/** 当前侧栏的可见序列（一级项 + 固定子页，按显示顺序）。 */
export function sidebarSequence(cfg: NavConfig | null | undefined): string[] {
  return navItemsFromConfig(cfg)
    .filter((it) => it.kind === 'item')
    .map((it) => (it as { key: string }).key);
}

/**
 * 把一整条侧栏序列写回配置（对齐 Qt _write_sidebar_sequence）。
 * ui_nav_order 存位置（一级键 + 固定子页的真实序列），ui_nav_pinned 只记哪些子页被固定。
 */
export function writeSidebarSequence(seq: string[]): Record<string, unknown> {
  const seen = new Set<string>();
  const clean = seq.filter((k) => {
    if (!(TOP_KEYS as readonly string[]).includes(k) && !ALL_SUB_KEYS.has(k)) return false;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  for (const k of TOP_KEYS) if (!clean.includes(k)) clean.push(k);
  return {
    ui_nav_order: clean,
    ui_nav_pinned: clean.filter((k) => ALL_SUB_KEYS.has(k)),
  };
}

/**
 * 侧栏内拖动排序：把 key 挪到 target 之前 / 之后（对齐 Qt _on_sidebar_reorder）。
 * 分组档挪的是 ui_nav_groups 里的成员（可跨组），精简档挪的是混合序列。
 */
export function reorderNavConfig(
  cfg: NavConfig | null | undefined, key: string, target: string, before: boolean,
): Record<string, unknown> | null {
  if (navStyle(cfg) === NAV_STYLE_GROUPED) {
    const groups = groupedLayout(cfg);
    return moveWithinGroups(groups, key, target, before) ? groupedLayoutPatch(groups) : null;
  }
  const seq = sidebarSequence(cfg);
  if (key === target || !seq.includes(key) || !seq.includes(target)) return null;
  seq.splice(seq.indexOf(key), 1);
  seq.splice(seq.indexOf(target) + (before ? 0 : 1), 0, key);
  return writeSidebarSequence(seq);
}

/**
 * 固定一个分区子页到侧栏（移动语义：原分区里不再显示）。
 *
 * 对齐 Qt _pin_nav_at / _take_from_section：分区只剩这一个子页时拒绝，
 * 移走会变空栏。返回 null = 没做，reason 说明为什么。
 */
export function pinNavConfig(
  cfg: NavConfig | null | undefined, key: string,
  target?: string | null, before = true,
): { patch: Record<string, unknown> } | { error: string } | null {
  if (!ALL_SUB_KEYS.has(key)) return null;
  if (pinnedFromConfig(cfg).includes(key)) return null;
  const members = sectionMembersFromConfig(cfg);
  const from = SECTION_IDS.find((sec) => members[sec].includes(key));
  if (from && members[from].length <= 1) {
    return { error: '该分区只剩这一个子页，移走会变空栏；先在「自定义分区」里补充其它子页' };
  }
  const patch: Record<string, unknown> = {};
  if (navStyle(cfg) === NAV_STYLE_GROUPED) {
    // 分组档没有独立的固定项列表：进侧栏 = 进某个组
    const groups = groupedLayout(cfg);
    const anchor = target && groups.some((g) => g.keys.includes(target)) ? target : 'more';
    const landed = moveWithinGroups(groups, key, anchor, anchor === target ? before : true);
    if (!landed) groups[groups.length - 1].keys.push(key);
    Object.assign(patch, groupedLayoutPatch(groups));
  } else {
    const seq = sidebarSequence(cfg);
    const anchor = target && seq.includes(target)
      ? target : (seq.includes('more') ? 'more' : null);
    if (anchor) seq.splice(seq.indexOf(anchor) + (anchor === target && !before ? 1 : 0), 0, key);
    else seq.push(key);
    Object.assign(patch, writeSidebarSequence(seq));
  }
  if (from) {
    patch.ui_section_members = {
      download: members.download.filter((k) => k !== key),
      more: members.more.filter((k) => k !== key),
    };
  }
  return { patch };
}

/**
 * 侧栏编辑器按「确定」时要写回的那一份。
 *
 * 对齐 Qt SidebarEditorDialog.accept：一级键换成对话框里的新顺序，固定子页
 * 保持它们当前在侧栏里的相对位置（不把用户拖出来的混排压扁）；一级项不能
 * 全部藏掉，至少留第一项。
 */
export function mergeNavOrder(
  cfg: NavConfig | null | undefined, topOrder: string[], pinned: string[],
): string[] {
  const current = navItemsFromConfig(cfg)
    .filter((it): it is Extract<NavEntry, { kind: 'item' }> => it.kind === 'item')
    .map((it) => it.key);
  const rest = [...topOrder];
  const merged: string[] = [];
  for (const k of current) {
    if (ALL_SUB_KEYS.has(k)) {
      if (pinned.includes(k)) merged.push(k);
    } else if (rest.length) {
      merged.push(rest.shift()!);
    }
  }
  merged.push(...rest);
  for (const k of pinned) if (!merged.includes(k)) merged.push(k);
  return merged;
}

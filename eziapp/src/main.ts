import './styles/main.css';
import { bridge, initBridge } from './bridge';
import { router, type PageKey } from './router';
import { store, type SettingsInfo } from './store';
import { initBridgeLifecycle, toast, clearPageCleanups, applyAppearance, showContextMenu } from './ui';
import { installRipple, pageSwap, pop } from './motion';
// 极小模块，静态引它不会把 dashboard chunk 拽进入口包（见 layout_bus 头注释）。
import { requestLayoutEdit } from './layout_bus';
// 侧栏编排的纯逻辑，与 Qt 版 app/main_window.py 同源，见 nav_model 头注释。
import {
  ALL_SUB_KEYS, NAV_KEY_FOR_PAGE, NAV_STYLE_GROUPED, PAGE_FOR_NAV_KEY, SECTION_IDS,
  SUB_TITLES, navItemsFromConfig, navStyle, pinNavConfig, reorderNavConfig,
  sectionMembersFromConfig, unpinNavConfig, type NavConfig, type NavEntry, type SectionId,
} from './nav_model';
// 只取类型：`import type` 会被编译掉，不会把 downloads chunk 拽进入口包。
import type { DownloadCategory } from './pages/downloads';

const app = document.getElementById('app')!;

/**
 * 侧栏图标用内联 SVG，不用字符。Unicode 那套里 ▶ ⚙ ☕ 这些在 Windows 上会被
 * 挑成彩色 emoji 字形，跟 ✦ ⋯ ☰ 这类纯文本字形混在一排，粗细和颜色都对不齐。
 * 统一成 1.5px 描边、跟随 currentColor 的 20x20 路径，一套到底。
 */
const ICONS: Record<string, string> = {
  brand: 'M10 2.8 16.6 6.6v7.6L10 18 3.4 14.2V6.6ZM3.4 6.6 10 10.4l6.6-3.8M10 10.4V18',
  launch: 'M7.4 4.8v10.4l8.2-5.2Z',
  download: 'M10 3.6v8.2M6.6 8.6 10 12l3.4-3.4M4.4 16.4h11.2',
  grid: 'M3.8 4.2h5.2v5.2H3.8ZM11 4.2h5.2v5.2H11ZM3.8 10.8h5.2V16H3.8ZM11 10.8h5.2V16H11Z',
  java: 'M5.4 7.2h8.2v4.2a4.1 4.1 0 0 1-8.2 0ZM13.6 8.2h1.4a1.8 1.8 0 0 1 0 3.6h-1.4M4.4 16.4h10.2',
  ai: 'M10 3 11.5 7.4 16 8.9l-4.5 1.5L10 14.8 8.5 10.4 4 8.9l4.5-1.5Z',
  instances: 'M10 3.4 16.4 6.6 10 9.8 3.6 6.6ZM3.6 10.2 10 13.4l6.4-3.2M3.6 13.6 10 16.8l6.4-3.2',
  mods: 'M4.2 5.6h11.6v8.8H4.2ZM4.2 10h11.6M8.2 5.6V10M12 10v4.4',
  accounts: 'M10 9.8a2.9 2.9 0 1 0 0-5.8 2.9 2.9 0 0 0 0 5.8ZM4.6 16.4a5.4 5.4 0 0 1 10.8 0',
  multiplayer: 'M10 3.4a6.6 6.6 0 1 0 0 13.2 6.6 6.6 0 0 0 0-13.2ZM3.4 10h13.2M10 3.4a9.4 6.6 0 0 1 0 13.2 9.4 6.6 0 0 1 0-13.2',
  servers: 'M4 4.6h12v4H4ZM4 11.4h12v4H4ZM6.3 6.6h1.4M6.3 13.4h1.4',
  playtime: 'M10 3.4a6.6 6.6 0 1 0 0 13.2 6.6 6.6 0 0 0 0-13.2ZM10 6.4v4l2.6 1.6',
  feedback: 'M3.8 4.8h12.4v8.4H9.4L6 16.2v-3H3.8Z',
  settings: 'M10 7.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6ZM10 2.8v2M10 15.2v2M2.8 10h2M15.2 10h2M4.9 4.9l1.4 1.4M13.7 13.7l1.4 1.4M15.1 4.9l-1.4 1.4M6.3 13.7l-1.4 1.4',
  tools: 'M13.3 3.8a3.9 3.9 0 0 0-5 4.9L4 13l3 3 4.3-4.3a3.9 3.9 0 0 0 4.9-5l-2.3 2.3-2.2-.6-.6-2.2Z',
  tasks: 'M4.2 6h11.6M4.2 10h11.6M4.2 14h7.6',
  // 三个点得画成真圆去填充：零长度线段靠 round cap 凑出来的点，在 17px 下
  // 小到几乎看不见，实测「更多」那一行就是空的。
  more: 'M4.7 10a1 1 0 1 1 2 0 1 1 0 1 1-2 0M9 10a1 1 0 1 1 2 0 1 1 0 1 1-2 0M13.3 10a1 1 0 1 1 2 0 1 1 0 1 1-2 0',
  chevron: 'M7.6 5.4 12.2 10l-4.6 4.6',
};

const FILLED = new Set(['more']);

const icon = (name: string) =>
  `<svg class="nav-svg${FILLED.has(name) ? ' filled' : ''}" viewBox="0 0 20 20" aria-hidden="true"><path d="${ICONS[name] || ''}"/></svg>`;

const TITLES: Record<PageKey, string> = {
  launch: '启动', instances: '版本管理', downloads: '下载', vanilla: '原版游戏',
  'mods-catalog': 'Mod', mods: '模组管理', modpacks: '整合包', datapacks: '数据包',
  resourcepacks: '资源包', shaders: '光影包', worlds: '世界', tasks: '下载任务',
  accounts: '账号', java: 'Java', servers: '服务器', playtime: '游玩时长',
  multiplayer: '陶瓦联机', ai: 'AI 助手', settings: '设置', feedback: '反馈与帮助',
  tools: '工具', more: '更多',
};

/** 侧栏读的就是后端那一份设置（ui_nav_* 由 get_settings 带过来）。 */
function navConfig(): NavConfig {
  return store.mergedSettings() as NavConfig;
}

const escapeAttr = (text: string) => text.replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] || c));

function navItemHtml(entry: Extract<NavEntry, { kind: 'item' }>): string {
  const label = escapeAttr(entry.label);
  const badge = entry.key === 'tasks'
    ? '<span class="badge" id="task-badge" style="display:none">0</span>' : '';
  return `<a class="nav-item${entry.top ? '' : ' nav-pinned'}" data-page="${entry.page}"`
    + ` data-nav-key="${entry.key}" title="${label}"${entry.draggable ? ' draggable="true"' : ''}>`
    + `<span class="nav-icon">${icon(entry.icon)}</span>`
    + `<span class="nav-label">${label}</span>${badge}</a>`;
}

function navHtml(): string {
  return navItemsFromConfig(navConfig()).map((entry) => {
    if (entry.kind === 'header') return `<div class="nav-group-title">${escapeAttr(entry.label)}</div>`;
    if (entry.kind === 'stretch') return '<div class="nav-spacer"></div>';
    return navItemHtml(entry);
  }).join('');
}

let navHtmlCache = '';

/**
 * 按配置重画侧栏。侧栏在设置回来之前就得先出来一版（否则开屏是空的），
 * 设置到手后再刷一次；HTML 没变就一个节点都不动。
 */
function renderNav() {
  const host = document.getElementById('sidebar-nav');
  if (!host) return;
  const html = navHtml();
  if (html === navHtmlCache) return;
  navHtmlCache = html;
  host.innerHTML = html;
  bindNavItems(host);
  highlightNav(router.page);
  paintTaskBadge(true);
}

let lastBadgeCount = -1;

/**
 * 「下载任务」上那颗计数。侧栏一重画它就是个新节点，所以每次都现查，
 * 不缓存引用；计数没变就一个字节都不写（下载高峰期这个订阅每帧都跑）。
 */
function paintTaskBadge(force = false) {
  const badge = document.getElementById('task-badge');
  if (!badge) return;
  if (!force && store.taskCount === lastBadgeCount) return;
  const grew = lastBadgeCount >= 0 && store.taskCount > lastBadgeCount;
  badge.textContent = String(store.taskCount);
  badge.style.display = store.taskCount > 0 ? '' : 'none';
  if (grew && !force) pop(badge);
  lastBadgeCount = store.taskCount;
}

function bindNavItems(host: ParentNode) {
  host.querySelectorAll<HTMLElement>('.nav-item').forEach((el) => {
    const page = el.dataset.page as PageKey;
    el.addEventListener('click', () => router.navigate(page));
    // 指针停到侧栏条目上就把那一页的 chunk 拉回来。真点下去时模块通常已经在内存里，
    // 转场不必再等一次网络/磁盘往返。
    el.addEventListener('pointerenter', () => { void loadPage(page).catch(() => undefined); }, { passive: true });
    el.addEventListener('contextmenu', (ev) => {
      ev.preventDefault();
      showNavMenu(el);
    });
    bindNavDrag(el);
  });
}

/** 当前页属于哪个分区（被固定到侧栏的子页不属于任何分区）。 */
function sectionOfKey(key: string): SectionId | null {
  if (!key || !ALL_SUB_KEYS.has(key)) return null;
  const members = sectionMembersFromConfig(navConfig());
  return SECTION_IDS.find((sec) => members[sec].includes(key)) || null;
}

function highlightNav(page: PageKey) {
  const navKey = NAV_KEY_FOR_PAGE[page] || '';
  const section = sectionOfKey(navKey);
  document.querySelectorAll<HTMLElement>('.nav-item').forEach((el) => {
    const key = el.dataset.navKey || '';
    el.classList.toggle('active', key === navKey);
    // 子页是从分区横条进来的，那一栏的一级项跟着亮（对齐 Qt 的分区高亮）
    el.classList.toggle('active-branch', !!section && key === section && key !== navKey);
  });
}

/**
 * 侧栏改动落盘：先按新配置画出来，再提交给桥；桥拒了就回滚成后端的实况。
 * 两端读同一份 config.json，这里写完 Qt 版下次开也是这个样子。
 */
async function saveNav(patch: Record<string, unknown>) {
  store.setSettings({ ...(store.settings || {}), ...patch } as SettingsInfo);
  renderNav();
  renderSectionBar(router.page);
  try {
    await bridge.call('save_settings', patch);
  } catch (e: unknown) {
    toast(e instanceof Error ? e.message : '侧栏没能保存', 'error');
    void loadInitialData();
  }
}

function showNavMenu(el: HTMLElement) {
  const key = el.dataset.navKey || '';
  if (!key) return;
  const cfg = navConfig();
  const hidden = ((cfg.ui_nav_hidden as string[] | undefined) || []).filter((k) => typeof k === 'string');
  const items = [];
  if (!ALL_SUB_KEYS.has(key) || navStyle(cfg) === NAV_STYLE_GROUPED) {
    items.push({
      label: '在侧栏隐藏这一项',
      onClick: () => { void saveNav({ ui_nav_hidden: [...new Set([...hidden, key])] }); },
    });
  }
  if (ALL_SUB_KEYS.has(key) && navStyle(cfg) !== NAV_STYLE_GROUPED) {
    items.push({
      label: '取消固定（放回分区）',
      onClick: () => {
        const out = unpinNavConfig(cfg, key);
        if (!out) return;
        void saveNav(out.patch);
        toast(`「${SUB_TITLES[key] || key}」放回了「${out.section === 'download' ? '游戏' : '更多'}」`, 'success');
      },
    });
  }
  items.push({ label: '自定义侧栏…', onClick: () => { void openNavEditor(); } });
  showContextMenu(el, items);
}

async function openNavEditor() {
  const { showSidebarEditor } = await import('./pages/nav_editor');
  const patch = await showSidebarEditor(navConfig());
  if (patch) await saveNav(patch);
}

/** 侧栏内拖动排序 / 把分区横条上的子页拖进侧栏固定。 */
function bindNavDrag(el: HTMLElement) {
  el.addEventListener('dragstart', (ev) => {
    ev.dataTransfer?.setData('text/pymcl-nav', el.dataset.navKey || '');
    ev.dataTransfer!.effectAllowed = 'move';
    el.classList.add('dragging');
  });
  el.addEventListener('dragend', () => {
    el.classList.remove('dragging');
    document.querySelectorAll('.nav-drop-before,.nav-drop-after')
      .forEach((n) => n.classList.remove('nav-drop-before', 'nav-drop-after'));
  });
  el.addEventListener('dragover', (ev) => {
    ev.preventDefault();
    const rect = el.getBoundingClientRect();
    const before = ev.clientY < rect.top + rect.height / 2;
    el.classList.toggle('nav-drop-before', before);
    el.classList.toggle('nav-drop-after', !before);
  });
  el.addEventListener('dragleave', () => {
    el.classList.remove('nav-drop-before', 'nav-drop-after');
  });
  el.addEventListener('drop', (ev) => {
    ev.preventDefault();
    el.classList.remove('nav-drop-before', 'nav-drop-after');
    const target = el.dataset.navKey || '';
    const rect = el.getBoundingClientRect();
    const before = ev.clientY < rect.top + rect.height / 2;
    const navKey = ev.dataTransfer?.getData('text/pymcl-nav') || '';
    const memberKey = ev.dataTransfer?.getData('text/pymcl-member') || '';
    const cfg = navConfig();
    if (navKey) {
      const patch = reorderNavConfig(cfg, navKey, target, before);
      if (patch) void saveNav(patch);
      return;
    }
    if (memberKey) pinMember(memberKey, target, before);
  });
}

function pinMember(key: string, target?: string, before = true) {
  const out = pinNavConfig(navConfig(), key, target, before);
  if (!out) return;
  if ('error' in out) {
    toast(out.error, 'warning', 5000);
    return;
  }
  void saveNav(out.patch);
  toast(`「${SUB_TITLES[key] || key}」已固定到侧栏`, 'success');
}

function renderShell() {
  app.innerHTML = `
    <div class="sidebar">
      <div class="sidebar-title"><span class="nav-icon">${icon('brand')}</span><span class="nav-label">PyMCL</span></div>
      <nav class="sidebar-nav" id="sidebar-nav"></nav>
      <button class="sidebar-edit" id="edit-nav" type="button" title="侧栏排法、顺序、显隐与固定项"><span class="nav-icon">${icon('grid')}</span><span class="nav-label">自定义侧栏</span></button>
      <button class="sidebar-edit" id="edit-layout" type="button" title="自由调整启动页布局：拖动、缩放、增删卡片"><span class="nav-icon">${icon('tools')}</span><span class="nav-label">编辑布局</span></button>
      <div class="sidebar-foot" id="bridge-status">桥接: 未连接</div>
      <div class="sidebar-resizer" id="sidebar-resizer"></div>
    </div>
    <div class="main-content">
      <header class="page-header"><div class="page-title" id="page-title">PyMCL 启动器</div></header>
      <div class="section-bar" id="section-bar" style="display:none"></div>
      <main class="page-content" id="page-content"></main>
    </div>
    <div class="toast-container" id="toast-container"></div>`;

  renderNav();
  // 从分区横条把子页拖到侧栏空白处也算固定（对齐 Qt 的拖拽固定）
  const nav = document.getElementById('sidebar-nav');
  nav?.addEventListener('dragover', (ev) => ev.preventDefault());
  nav?.addEventListener('drop', (ev) => {
    const key = ev.dataTransfer?.getData('text/pymcl-member') || '';
    if (!key) return;
    ev.preventDefault();
    pinMember(key);
  });

  document.getElementById('edit-nav')?.addEventListener('click', () => { void openNavEditor(); });
  // 不在启动页时画布还没挂上：layout_bus 记下这次请求，切过去后由画布自己领走
  document.getElementById('edit-layout')?.addEventListener('click', () => {
    if (!requestLayoutEdit()) router.navigate('launch');
  });
  const resizer = document.getElementById('sidebar-resizer');
  resizer?.addEventListener('pointerdown', (ev) => {
    ev.preventDefault();
    // 改一次 --sidebar-width 就是整页重排。高回报率鼠标一秒能发两百多个
    // pointermove，屏幕只刷六十次，所以攒到帧上只写最后那一个位置。
    let width = 232;
    let frame = 0;
    const apply = () => {
      frame = 0;
      document.documentElement.style.setProperty('--sidebar-width', `${width}px`);
    };
    const move = (e: PointerEvent) => {
      width = Math.max(140, Math.min(320, e.clientX));
      if (!frame) frame = requestAnimationFrame(apply);
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (frame) cancelAnimationFrame(frame);
      apply();
      // 本地覆盖层先记一份（离线也还原得回来），同时写回后端，
      // Qt 版读的是同一个 ui_sidebar_width
      store.setLocalPrefs({ ui_sidebar_width: width });
      void bridge.call('save_settings', { ui_sidebar_width: width }).catch(() => undefined);
    };
    window.addEventListener('pointermove', move, { passive: true });
    window.addEventListener('pointerup', up);
  });

  // 内容滚下去时给顶栏加一道分隔阴影，滚回顶部再收掉
  const scroller = document.getElementById('page-content');
  const header = document.querySelector('.page-header');
  let raised = false;
  scroller?.addEventListener('scroll', () => {
    const next = scroller.scrollTop > 4;
    if (next === raised) return;
    raised = next;
    header?.classList.toggle('raised', next);
  }, { passive: true });

  installRipple(app);
  router.subscribe(() => void renderPage(router.page));
}

/**
 * 分区横条：一栏里的子页在这里排成一排，跟 Qt 版分区页顶上那条一样，
 * 成员与顺序都读 ui_section_members。把一颗拖进侧栏就是固定。
 */
function renderSectionBar(page: PageKey) {
  const host = document.getElementById('section-bar');
  if (!host) return;
  const navKey = NAV_KEY_FOR_PAGE[page] || '';
  const section = sectionOfKey(navKey);
  if (!section) {
    host.innerHTML = '';
    host.style.display = 'none';
    return;
  }
  const members = sectionMembersFromConfig(navConfig())[section];
  host.style.display = '';
  host.innerHTML = `<div class="tabs">${members.map((key) =>
    `<button class="tab${key === navKey ? ' active' : ''}" draggable="true"`
    + ` data-member="${key}" title="拖到侧栏可固定">${escapeAttr(SUB_TITLES[key] || key)}</button>`).join('')}</div>`;
  host.querySelectorAll<HTMLElement>('[data-member]').forEach((btn) => {
    const key = btn.dataset.member!;
    btn.addEventListener('click', () => router.navigate(PAGE_FOR_NAV_KEY[key] || 'launch'));
    btn.addEventListener('dragstart', (ev) => {
      ev.dataTransfer?.setData('text/pymcl-member', key);
      ev.dataTransfer!.effectAllowed = 'move';
    });
  });
}

/** 点分区（游戏 / 更多）落到那一栏的第一项——分区本身不是页面。 */
function sectionLanding(page: PageKey): PageKey | null {
  const section: SectionId | null = page === 'downloads' ? 'download' : page === 'more' ? 'more' : null;
  if (!section) return null;
  const first = sectionMembersFromConfig(navConfig())[section][0];
  const target = first ? PAGE_FOR_NAV_KEY[first] : null;
  return target && target !== page ? target : null;
}

let renderSeq = 0;

async function renderPage(page: PageKey) {
  const landing = sectionLanding(page);
  if (landing) {
    router.navigate(landing);
    return;
  }
  const content = document.getElementById('page-content');
  const title = document.getElementById('page-title');
  if (!content || !title) return;
  const seq = ++renderSeq;
  // 模块先备好再转场，别让淡出和 import() 串成两段等待。
  const paint = await loadPage(page);
  // 等 chunk 的这段时间里用户可能又点了别处，那就让后来的那次说了算。
  if (seq !== renderSeq) return;
  clearPageCleanups();
  highlightNav(page);
  renderSectionBar(page);
  title.textContent = TITLES[page] || 'PyMCL';
  await pageSwap(content, () => paint(content));
}

type Painter = (content: HTMLElement) => void;

const pageLoaders: Record<PageKey, () => Promise<Painter>> = {
  launch: async () => (await import('./pages/launch')).renderLaunchPage,
  instances: async () => (await import('./pages/instances')).renderInstancesPage,
  mods: async () => (await import('./pages/mods')).renderModsPage,
  tasks: async () => (await import('./pages/tasks')).renderTasksPage,
  accounts: async () => (await import('./pages/accounts')).renderAccountsPage,
  java: async () => (await import('./pages/java')).renderJavaPage,
  servers: async () => (await import('./pages/servers')).renderServersPage,
  playtime: async () => (await import('./pages/playtime')).renderPlaytimePage,
  multiplayer: async () => (await import('./pages/multiplayer')).renderMultiplayerPage,
  ai: async () => (await import('./pages/ai')).renderAIPage,
  settings: async () => (await import('./pages/settings')).renderSettingsPage,
  feedback: async () => (await import('./pages/feedback')).renderFeedbackPage,
  tools: async () => (await import('./pages/tools')).renderToolsPage,
  vanilla: () => downloadPainter('vanilla'),
  'mods-catalog': () => downloadPainter('mods'),
  modpacks: () => downloadPainter('modpacks'),
  datapacks: () => downloadPainter('datapacks'),
  resourcepacks: () => downloadPainter('resourcepacks'),
  shaders: () => downloadPainter('shaders'),
  worlds: () => downloadPainter('worlds'),
  // 两个分区横条本身不是页面：renderPage 会先把它换成该分区的第一项，
  // 这两条只在整栏被清空（成员全被固定走）时兜底
  downloads: () => downloadPainter('vanilla'),
  more: async () => (await import('./pages/instances')).renderInstancesPage,
};

async function downloadPainter(category: DownloadCategory): Promise<Painter> {
  const { renderDownloadPage } = await import('./pages/downloads');
  return (content) => { void renderDownloadPage(content, category); };
}

const painterCache = new Map<PageKey, Promise<Painter>>();

function loadPage(page: PageKey): Promise<Painter> {
  let pending = painterCache.get(page);
  if (!pending) {
    pending = (pageLoaders[page] || pageLoaders.launch)();
    // 加载失败不留在缓存里，下次还能重来
    pending.catch(() => painterCache.delete(page));
    painterCache.set(page, pending);
  }
  return pending;
}

async function loadInitialData() {
  const results = await Promise.allSettled([
    bridge.call('get_settings'),
    bridge.call('get_instances'),
    bridge.call('get_version_list'),
    bridge.call('get_java_list'),
    bridge.call('get_account_rows'),
  ]);
  const [settings, instances, versions, javas, accounts] = results;
  if (settings.status === 'fulfilled') {
    store.setSettings(settings.value as any);
    applyAppearance(store.mergedSettings());
    renderNav();
    renderSectionBar(router.page);
  }
  if (instances.status === 'fulfilled') store.setInstances(instances.value as any);
  if (versions.status === 'fulfilled') store.setVersionList(versions.value as any);
  if (javas.status === 'fulfilled') store.setJavaList(javas.value as any);
  if (accounts.status === 'fulfilled') store.setAccounts(accounts.value as any);
  store.notify();
  if (results.every((r) => r.status === 'rejected')) toast('无法连接 Python 桥接服务', 'error');
}

function debounce(fn: () => void, wait: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return () => {
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(() => { timer = undefined; fn(); }, wait);
  };
}

const reloadInitialData = debounce(() => { void loadInitialData(); }, 280);

async function maybeClipboardHint() {
  try {
    const text = (await navigator.clipboard.readText()).trim();
    const low = text.toLowerCase();
    if (!text || !(low.includes('modrinth.com') || low.includes('curseforge.com'))) return;
    if (sessionStorage.getItem('pymcl.clip') === text) return;
    sessionStorage.setItem('pymcl.clip', text);
    // 记下链接：进入下载页时自动填进搜索框（对齐 Qt 版 catalog_page.showEvent）
    store.pendingClipLink = text;
    toast(`识别到剪贴板链接：${text.slice(0, 56)}（到下载页即自动填入）`, 'info', 5000);
  } catch { /* clipboard may be denied */ }
}

async function init() {
  renderShell();
  // 文件拖到没接收区的地方，Edge 默认会把它当网页打开，整个界面就没了
  window.addEventListener('dragover', (e) => e.preventDefault());
  window.addEventListener('drop', (e) => e.preventDefault());
  void renderPage(router.page);
  const bridgeConfigured = await initBridge();
  if (!bridgeConfigured) {
    toast('未获得本次启动的桥接凭据，请通过 eziapp_launcher.py 启动', 'error', 7000);
    return;
  }
  initBridgeLifecycle(() => {
    bridge.subscribe('task_added', (data: any) => store.updateTask(data.task_id, { title: data.title || '' }));
    bridge.subscribe('progress', (data: any) => store.updateTask(data.task_id, { current: data.current || 0, total: data.total || 0, message: data.message || '' }));
    bridge.subscribe('log', (data: any) => store.addLog(data.task_id, data.text || ''));
    bridge.subscribe('finished', (data: any) => store.updateTask(data.task_id, { success: data.success, finishedMessage: data.message || '' }));
    bridge.subscribe('task_count_changed', (data: any) => { store.taskCount = data.count || 0; store.notify(); });
    bridge.subscribe('game_started', () => { store.gameRunning = true; store.notify(); });
    bridge.subscribe('game_exited', () => { store.gameRunning = false; store.notify(); });
    bridge.subscribe('ui_changed', () => reloadInitialData());
    store.subscribe(() => paintTaskBadge());
    void loadInitialData();
    void maybeClipboardHint();
  });
}

init();

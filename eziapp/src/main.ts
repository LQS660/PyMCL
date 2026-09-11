import './styles/main.css';
import { bridge, initBridge } from './bridge';
import { router, type PageKey } from './router';
import { store } from './store';
import { initBridgeLifecycle, toast, clearPageCleanups, applyAppearance } from './ui';
import { installRipple, pageSwap, pop } from './motion';
// 极小模块，静态引它不会把 dashboard chunk 拽进入口包（见 layout_bus 头注释）。
import { requestLayoutEdit } from './layout_bus';
// 只取类型：`import type` 会被编译掉，不会把 downloads chunk 拽进入口包。
import type { DownloadCategory } from './pages/downloads';

const app = document.getElementById('app')!;

// 窄屏下侧栏收成 64px 只剩图标，子项没有图标就会塌成一排空格子，所以每项都得配一个。
type NavChild = { key: PageKey; label: string; icon: string };

/** 全部可导航的页面，按「常驻侧栏」「分组内」「只走快捷入口」三档摆。 */
const NAV_META: Record<string, NavChild> = {
  launch: { key: 'launch', label: '启动', icon: '▶' },
  downloads: { key: 'downloads', label: '下载', icon: '⬇' },
  java: { key: 'java', label: 'Java', icon: '☕' },
  ai: { key: 'ai', label: 'AI 助手', icon: '✦' },
  instances: { key: 'instances', label: '实例', icon: '🗃' },
  mods: { key: 'mods', label: '模组', icon: '🔧' },
  accounts: { key: 'accounts', label: '账号', icon: '👤' },
  multiplayer: { key: 'multiplayer', label: '联机', icon: '🛰' },
  servers: { key: 'servers', label: '服务器', icon: '🌐' },
  playtime: { key: 'playtime', label: '时长', icon: '⏱' },
  feedback: { key: 'feedback', label: '反馈', icon: '💬' },
  settings: { key: 'settings', label: '设置', icon: '⚙' },
  tools: { key: 'tools', label: '工具', icon: '🧰' },
  tasks: { key: 'tasks', label: '下载任务', icon: '☰' },
};

// 下载页顶部本来就有一条覆盖全部七个分类的 tab（downloads.ts renderShell），
// 侧栏再铺一遍是同一组入口出现两次。这里只留一个总入口，分类交给页内 tab。
const DOWNLOAD_CHILDREN: NavChild[] = [
  { key: 'vanilla', label: '内容下载', icon: '🧩' },
  NAV_META.java,
];
// 工具页的清理 / 更新 / 诊断 / 全局 Mod 在设置页都有入口（settings.ts 的「维护」组
// 甚至有个按钮直接跳过去），时长在启动页有常驻卡片——两者都不再占侧栏位置，
// 仍可从设置页和启动页的快捷入口卡片进。
const MORE_CHILDREN: NavChild[] = [
  NAV_META.instances, NAV_META.multiplayer, NAV_META.servers,
  NAV_META.feedback, NAV_META.settings,
];
/** 没有用户配置时，默认把这两项提到侧栏根——它们是改得最勤的两页。 */
const DEFAULT_PINNED = ['mods', 'accounts'];

const navChild = (it: NavChild) =>
  `<a class="nav-item" data-page="${it.key}" title="${it.label}"><span class="nav-icon">${it.icon}</span><span class="nav-label">${it.label}</span></a>`;

/** Qt 版把固定项写在 ui_nav_pinned 里（键名是 account/mods 这套），这里对齐过来。 */
const PIN_ALIASES: Record<string, string> = {
  account: 'accounts', instance: 'instances', version: 'vanilla',
  mod: 'mods-catalog', download: 'downloads',
};

function pinnedKeys(): NavChild[] {
  const raw = store.mergedSettings()?.ui_nav_pinned;
  const list = Array.isArray(raw) && raw.length ? raw : DEFAULT_PINNED;
  const hidden = new Set(
    (store.mergedSettings()?.ui_nav_hidden as string[] | undefined) || []);
  const seen = new Set<string>();
  return list
    .map((k) => PIN_ALIASES[String(k)] || String(k))
    .filter((k) => !hidden.has(k) && !seen.has(k) && (seen.add(k), NAV_META[k]))
    .map((k) => NAV_META[k]);
}

const TITLES: Record<PageKey, string> = {
  launch: '启动', instances: '实例', downloads: '下载', vanilla: '原版游戏',
  'mods-catalog': 'Mod', mods: '模组管理', modpacks: '整合包', datapacks: '数据包',
  resourcepacks: '资源包', shaders: '光影包', worlds: '世界', tasks: '下载任务',
  accounts: '账号', java: 'Java', servers: '服务器', playtime: '游玩时长',
  multiplayer: '陶瓦联机', ai: 'AI 助手', settings: '设置', feedback: '反馈与帮助',
  tools: '工具', more: '更多',
};

/**
 * 每个分组「管辖」哪些页面。这跟侧栏上摆出来的子项不是一回事：下载组只露两项，
 * 但七个分类页都归它管，从页内 tab 跳过去时也要让它亮起来。
 */
const SECTION_MEMBERS: Record<string, Set<PageKey>> = {
  downloads: new Set<PageKey>(['downloads', 'vanilla', 'mods-catalog', 'modpacks',
    'datapacks', 'resourcepacks', 'shaders', 'worlds', 'java']),
  more: new Set<PageKey>(['more', 'instances', 'multiplayer', 'servers',
    'playtime', 'feedback', 'settings', 'tools']),
};

/** 分组当前是否展开：记在 localStorage，切页不丢。 */
function sectionOpen(id: string): boolean {
  return localStorage.getItem(`pymcl.nav.${id}`) === '1';
}

/**
 * 可折叠的分组。对齐 Qt 版 PclSideBar 的行为——eziapp 之前两个分组永远摊开，
 * 22 个条目全挤在侧栏里，这是「臃肿」的直接来源。
 */
function navSection(id: string, head: NavChild, children: NavChild[]): string {
  const open = sectionOpen(id);
  return `
    <div class="nav-section${open ? ' open' : ''}" data-section="${id}">
      <a class="nav-item nav-section-head" data-page="${head.key}" title="${head.label}">
        <span class="nav-icon">${head.icon}</span><span class="nav-label">${head.label}</span>
        <span class="nav-chevron" data-section-toggle="${id}" role="button" aria-label="展开或收起">▾</span>
      </a>
      <div class="nav-children"><div class="nav-children-inner">${children.map(navChild).join('')}</div></div>
    </div>`;
}

function bindNavItems(host: ParentNode) {
  host.querySelectorAll('.nav-item').forEach((el) => {
    const key = (el as HTMLElement).dataset.page as PageKey;
    el.addEventListener('click', () => router.navigate(key));
    // 指针停到侧栏条目上就把那一页的 chunk 拉回来。真点下去时模块通常已经在内存里，
    // 转场不必再等一次网络/磁盘往返。
    el.addEventListener('pointerenter', () => { void loadPage(key).catch(() => undefined); }, { passive: true });
  });
}

/**
 * 侧栏是在设置回来之前就画好的，那一刻只能用默认固定项。设置到手后按
 * ui_nav_pinned / ui_nav_hidden 重排一次；内容没变就不动 DOM。
 */
function syncPinnedNav() {
  const host = document.getElementById('nav-pinned');
  if (!host) return;
  const html = pinnedKeys().map(navChild).join('');
  if (host.innerHTML === html) return;
  host.innerHTML = html;
  bindNavItems(host);
  document.querySelectorAll('.nav-item').forEach((el) => {
    el.classList.toggle('active', (el as HTMLElement).dataset.page === router.page);
  });
}

function renderShell() {
  app.innerHTML = `
    <div class="sidebar">
      <div class="sidebar-title"><span class="nav-icon">⛏️</span><span class="nav-label">PyMCL</span></div>
      <nav class="sidebar-nav">
        ${navChild(NAV_META.launch)}
        ${navSection('downloads', NAV_META.downloads, DOWNLOAD_CHILDREN)}
        <div id="nav-pinned">${pinnedKeys().map(navChild).join('')}</div>
        ${navChild(NAV_META.ai)}
        ${navSection('more', { key: 'more', label: '更多', icon: '⋯' }, MORE_CHILDREN)}
        <a class="nav-item" data-page="tasks" title="下载任务"><span class="nav-icon">☰</span><span class="nav-label">下载任务</span><span class="badge" id="task-badge" style="display:none">0</span></a>
      </nav>
      <button class="sidebar-edit" id="edit-layout" type="button" title="自由调整启动页布局：拖动、缩放、增删卡片"><span class="nav-icon">✎</span><span class="nav-label">编辑布局</span></button>
      <div class="sidebar-foot" id="bridge-status">桥接: 未连接</div>
      <div class="sidebar-resizer" id="sidebar-resizer"></div>
    </div>
    <div class="main-content">
      <header class="page-header"><div class="page-title" id="page-title">PyMCL 启动器</div></header>
      <main class="page-content" id="page-content"></main>
    </div>
    <div class="toast-container" id="toast-container"></div>`;

  // 箭头只管折叠，不跟着跳页；点条目本身仍然跳转（并顺手展开那一组）
  document.querySelectorAll<HTMLElement>('[data-section-toggle]').forEach((el) => {
    el.addEventListener('click', (ev) => {
      ev.stopPropagation();
      const id = el.dataset.sectionToggle!;
      const host = document.querySelector(`.nav-section[data-section="${id}"]`);
      const open = host?.classList.toggle('open') ?? false;
      localStorage.setItem(`pymcl.nav.${id}`, open ? '1' : '0');
    });
  });

  bindNavItems(app);
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
      // 桥接不往返 ui_sidebar_width，存本地覆盖层
      store.setLocalPrefs({ ui_sidebar_width: width });
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

let renderSeq = 0;

async function renderPage(page: PageKey) {
  const content = document.getElementById('page-content');
  const title = document.getElementById('page-title');
  if (!content || !title) return;
  const seq = ++renderSeq;
  // 模块先备好再转场，别让淡出和 import() 串成两段等待。
  const paint = await loadPage(page);
  // 等 chunk 的这段时间里用户可能又点了别处，那就让后来的那次说了算。
  if (seq !== renderSeq) return;
  clearPageCleanups();
  document.querySelectorAll('.nav-item').forEach((el) => {
    el.classList.toggle('active', (el as HTMLElement).dataset.page === page);
  });
  // 七个下载分类里只有一个在侧栏露面，其余靠页内 tab 到达；不管走哪条路，
  // 「下载」这一组都得亮起来，并且把它所在的分组展开。
  for (const [id, members] of Object.entries(SECTION_MEMBERS)) {
    const host = document.querySelector(`.nav-section[data-section="${id}"]`);
    if (!host) continue;
    const inside = members.has(page);
    host.querySelector('.nav-section-head')?.classList.toggle('active-branch', inside);
    if (inside) host.classList.add('open');
  }
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
  // 两个分区横条本身不是页面，点它落到该分区的第一项
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
    syncPinnedNav();
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
    const badge = document.getElementById('task-badge');
    let lastCount = -1;
    store.subscribe(() => {
      // 这个订阅在下载高峰期每帧都跑，计数没变就一个字节都不写
      if (!badge || store.taskCount === lastCount) return;
      badge.textContent = String(store.taskCount);
      badge.style.display = store.taskCount > 0 ? '' : 'none';
      if (lastCount >= 0 && store.taskCount > 0) pop(badge);
      lastCount = store.taskCount;
    });
    void loadInitialData();
    void maybeClipboardHint();
  });
}

init();

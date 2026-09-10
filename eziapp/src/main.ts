import './styles/main.css';
import { bridge, initBridge } from './bridge';
import { router, type PageKey } from './router';
import { store } from './store';
import { initBridgeLifecycle, toast, clearPageCleanups, applyAppearance } from './ui';
import { installRipple, pageSwap, pop } from './motion';
// 只取类型：`import type` 会被编译掉，不会把 downloads chunk 拽进入口包。
import type { DownloadCategory } from './pages/downloads';

const app = document.getElementById('app')!;

const DOWNLOAD_CHILDREN: { key: PageKey; label: string }[] = [
  { key: 'vanilla', label: '原版游戏' },
  { key: 'mods-catalog', label: 'Mod' },
  { key: 'modpacks', label: '整合包' },
  { key: 'datapacks', label: '数据包' },
  { key: 'resourcepacks', label: '资源包' },
  { key: 'shaders', label: '光影包' },
  { key: 'worlds', label: '世界' },
  { key: 'java', label: 'Java' },
];
const MORE_CHILDREN: { key: PageKey; label: string }[] = [
  { key: 'instances', label: '实例' },
  { key: 'mods', label: '模组' },
  { key: 'accounts', label: '账号' },
  { key: 'multiplayer', label: '联机' },
  { key: 'servers', label: '服务器' },
  { key: 'playtime', label: '时长' },
  { key: 'feedback', label: '反馈' },
  { key: 'settings', label: '设置' },
  { key: 'tools', label: '工具' },
];

const TITLES: Record<PageKey, string> = {
  launch: '启动', instances: '实例', downloads: '下载', vanilla: '原版游戏',
  'mods-catalog': 'Mod', mods: '模组管理', modpacks: '整合包', datapacks: '数据包',
  resourcepacks: '资源包', shaders: '光影包', worlds: '世界', tasks: '下载任务',
  accounts: '账号', java: 'Java', servers: '服务器', playtime: '游玩时长',
  multiplayer: '陶瓦联机', ai: 'AI 助手', settings: '设置', feedback: '反馈与帮助',
  tools: '工具', more: '更多',
};

function renderShell() {
  app.innerHTML = `
    <div class="sidebar">
      <div class="sidebar-title"><span class="nav-icon">⛏️</span><span class="nav-label">PyMCL</span></div>
      <nav class="sidebar-nav">
        <a class="nav-item" data-page="launch"><span class="nav-icon">▶</span><span class="nav-label">启动</span></a>
        <div class="nav-section">
          <a class="nav-item" data-page="downloads"><span class="nav-icon">⬇</span><span class="nav-label">下载</span></a>
          <div class="nav-children">${DOWNLOAD_CHILDREN.map((it) => `<a class="nav-item" data-page="${it.key}"><span class="nav-label">${it.label}</span></a>`).join('')}</div>
        </div>
        <a class="nav-item" data-page="ai"><span class="nav-icon">✦</span><span class="nav-label">AI 助手</span></a>
        <div class="nav-section">
          <a class="nav-item" data-page="more"><span class="nav-icon">⋯</span><span class="nav-label">更多</span></a>
          <div class="nav-children">${MORE_CHILDREN.map((it) => `<a class="nav-item" data-page="${it.key}"><span class="nav-label">${it.label}</span></a>`).join('')}</div>
        </div>
        <a class="nav-item" data-page="tasks"><span class="nav-icon">☰</span><span class="nav-label">下载任务</span><span class="badge" id="task-badge" style="display:none">0</span></a>
      </nav>
      <div class="sidebar-foot" id="bridge-status">桥接: 未连接</div>
      <div class="sidebar-resizer" id="sidebar-resizer"></div>
    </div>
    <div class="main-content">
      <header class="page-header"><div class="page-title" id="page-title">PyMCL 启动器</div></header>
      <main class="page-content" id="page-content"></main>
    </div>
    <div class="toast-container" id="toast-container"></div>`;

  document.querySelectorAll('.nav-item').forEach((el) => {
    const key = (el as HTMLElement).dataset.page as PageKey;
    el.addEventListener('click', () => router.navigate(key));
    // 指针停到侧栏条目上就把那一页的 chunk 拉回来。真点下去时模块通常已经在内存里，
    // 转场不必再等一次网络/磁盘往返。
    el.addEventListener('pointerenter', () => { void loadPage(key).catch(() => undefined); }, { passive: true });
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

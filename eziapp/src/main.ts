import './styles/main.css';
import { bridge, initBridge } from './bridge';
import { router, type PageKey } from './router';
import { store } from './store';
import { initBridgeLifecycle, toast, clearPageCleanups, applyAppearance } from './ui';

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
    el.addEventListener('click', () => router.navigate((el as HTMLElement).dataset.page as PageKey));
  });
  const resizer = document.getElementById('sidebar-resizer');
  resizer?.addEventListener('pointerdown', (ev) => {
    ev.preventDefault();
    const move = (e: PointerEvent) => {
      const w = Math.max(140, Math.min(320, e.clientX));
      document.documentElement.style.setProperty('--sidebar-width', `${w}px`);
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      const w = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-width')) || 232;
      void bridge.call('save_settings', { ui_sidebar_width: w }).catch(() => undefined);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });
  router.subscribe(() => void renderPage(router.page));
}

async function renderPage(page: PageKey) {
  const content = document.getElementById('page-content');
  const title = document.getElementById('page-title');
  if (!content || !title) return;
  clearPageCleanups();
  document.querySelectorAll('.nav-item').forEach((el) => {
    el.classList.toggle('active', (el as HTMLElement).dataset.page === page);
  });
  title.textContent = TITLES[page] || 'PyMCL';
  content.classList.remove('page-enter');
  void content.offsetWidth;
  content.classList.add('page-enter');

  if (page === 'downloads') page = 'vanilla';
  if (page === 'more') page = 'instances';

  switch (page) {
    case 'launch': (await import('./pages/launch')).renderLaunchPage(content); break;
    case 'instances': (await import('./pages/instances')).renderInstancesPage(content); break;
    case 'vanilla': (await import('./pages/downloads')).renderDownloadPage(content, 'vanilla'); break;
    case 'mods-catalog': (await import('./pages/downloads')).renderDownloadPage(content, 'mods'); break;
    case 'mods': (await import('./pages/mods')).renderModsPage(content); break;
    case 'modpacks': (await import('./pages/downloads')).renderDownloadPage(content, 'modpacks'); break;
    case 'datapacks': (await import('./pages/downloads')).renderDownloadPage(content, 'datapacks'); break;
    case 'resourcepacks': (await import('./pages/downloads')).renderDownloadPage(content, 'resourcepacks'); break;
    case 'shaders': (await import('./pages/downloads')).renderDownloadPage(content, 'shaders'); break;
    case 'worlds': (await import('./pages/downloads')).renderDownloadPage(content, 'worlds'); break;
    case 'tasks': (await import('./pages/tasks')).renderTasksPage(content); break;
    case 'accounts': (await import('./pages/accounts')).renderAccountsPage(content); break;
    case 'java': (await import('./pages/java')).renderJavaPage(content); break;
    case 'servers': (await import('./pages/servers')).renderServersPage(content); break;
    case 'playtime': (await import('./pages/playtime')).renderPlaytimePage(content); break;
    case 'multiplayer': (await import('./pages/multiplayer')).renderMultiplayerPage(content); break;
    case 'ai': (await import('./pages/ai')).renderAIPage(content); break;
    case 'settings': (await import('./pages/settings')).renderSettingsPage(content); break;
    case 'feedback': (await import('./pages/feedback')).renderFeedbackPage(content); break;
    case 'tools': (await import('./pages/tools')).renderToolsPage(content); break;
    default: (await import('./pages/launch')).renderLaunchPage(content);
  }
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
    applyAppearance(settings.value as any);
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
    toast(`识别到剪贴板链接：${text.slice(0, 64)}`, 'info', 5000);
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
    store.subscribe(() => {
      const badge = document.getElementById('task-badge');
      if (!badge) return;
      badge.textContent = String(store.taskCount);
      badge.style.display = store.taskCount > 0 ? '' : 'none';
    });
    void loadInitialData();
    void maybeClipboardHint();
  });
}

init();

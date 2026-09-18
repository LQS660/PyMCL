import { bridge } from '../bridge';
import { router, type PageKey } from '../router';
import { store } from '../store';
import { formDialog, toast, registerPageCleanup } from '../ui';
import { countUp, smoothProgress } from '../motion';
import { escapeHtml, errorMessage } from './common';
import { crashDialog, preflightDialog, showVersionSetup } from './dialogs';
import { DashboardCanvas, type CardSpec, type DashboardCard } from '../dashboard';
import { defaultDoc, docFromDict, type LayoutItem } from '../layout_geom';
import { attachLayoutEditor } from '../layout_bus';

let currentLaunchTaskId = '';

/**
 * 快捷入口卡片可选的导航目标。key 与 Qt 版 home_cards.QUICK_TARGETS 同名——
 * 布局文档（含 item.settings.targets）两套界面共用，存的必须是同一套键；
 * page 是 eziapp 这边对应的页面。ai 是 eziapp 独有的目标，Qt 读到会静默忽略。
 */
const QUICK_TARGETS: { key: string; label: string; page: PageKey }[] = [
  { key: 'launch', label: '启动', page: 'launch' },
  { key: 'version', label: '原版游戏', page: 'vanilla' },
  { key: 'mod', label: 'Mod', page: 'mods-catalog' },
  { key: 'modpack', label: '整合包', page: 'modpacks' },
  { key: 'datapack', label: '数据包', page: 'datapacks' },
  { key: 'resource', label: '资源包', page: 'resourcepacks' },
  { key: 'shader', label: '光影包', page: 'shaders' },
  { key: 'world', label: '世界', page: 'worlds' },
  { key: 'java', label: 'Java', page: 'java' },
  { key: 'instance', label: '实例', page: 'instances' },
  { key: 'mods', label: '模组', page: 'mods' },
  { key: 'account', label: '账号', page: 'accounts' },
  { key: 'multiplayer', label: '联机', page: 'multiplayer' },
  { key: 'servers', label: '服务器', page: 'servers' },
  { key: 'playtime', label: '时长', page: 'playtime' },
  { key: 'feedback', label: '反馈', page: 'feedback' },
  { key: 'settings', label: '设置', page: 'settings' },
  { key: 'tasks', label: '下载任务', page: 'tasks' },
  { key: 'ai', label: 'AI 助手', page: 'ai' },
];
/** 没配置时显示的入口（与 Qt QuickBody._targets 的缺省一致）。 */
const QUICK_DEFAULT = ['version', 'mod', 'modpack', 'mods', 'instance', 'account', 'settings', 'tasks'];
/** 旧版 eziapp 便签存本机的键；首个空便签卡会把它领走并搬进布局文档。 */
const LEGACY_NOTE_KEY = 'pymcl.notes';

function h(html: string): HTMLElement {
  const tpl = document.createElement('template');
  tpl.innerHTML = html.trim();
  return tpl.content.firstElementChild as HTMLElement;
}
/** 取正文里 data-f="name" 的控件。正文可能尚未挂进文档，不能用 getElementById。 */
function f<T extends Element = HTMLElement>(root: ParentNode, name: string): T {
  return root.querySelector(`[data-f="${name}"]`) as T;
}
function fmtDuration(sec: number): string {
  const s = Math.max(0, Math.floor(sec));
  return `${Math.floor(s / 3600)} 小时 ${Math.floor((s % 3600) / 60)} 分`;
}
function quickTargets(item: LayoutItem): string[] {
  const raw = item.settings.targets;
  const list = Array.isArray(raw) && raw.length ? raw.map(String) : QUICK_DEFAULT;
  return list.filter((k) => QUICK_TARGETS.some((t) => t.key === k));
}

export function renderLaunchPage(container: HTMLElement) {
  const settings = (store.settings || {}) as any;
  container.innerHTML = '<div class="dash-host"></div>';
  const host = container.firstElementChild as HTMLElement;

  // 多例卡片正文（便签 / 任务摘要…）各自的收尾：卡片被移除或页面卸载时调用
  const bodyCleanups = new Map<HTMLElement, () => void>();
  const keep = () => { /* 单例正文缓存在闭包里，卡片重建时原样接回 */ };
  const drop = (body: HTMLElement) => {
    bodyCleanups.get(body)?.();
    bodyCleanups.delete(body);
  };

  // ------------------------------------------------------------------
  // 布局落盘：卡片几何 / 增删 / 便签文字 / 快捷入口配置都走这里（对齐 Qt LaunchPage._persist_layout_now）
  // ------------------------------------------------------------------
  let persistTimer = 0;
  let legacyNotePending = false;
  const persistNow = async () => {
    if (persistTimer) { clearTimeout(persistTimer); persistTimer = 0; }
    const doc = canvas.currentDoc();
    try {
      await bridge.call('save_layout', { doc });
      if (legacyNotePending) {
        legacyNotePending = false;
        try { localStorage.removeItem(LEGACY_NOTE_KEY); } catch { /* ignore */ }
      }
    } catch (e) {
      toast(errorMessage(e, '布局保存失败'), 'error');
    }
  };
  const persistSoon = () => {
    if (persistTimer) clearTimeout(persistTimer);
    persistTimer = window.setTimeout(() => { persistTimer = 0; void persistNow(); }, 400);
  };

  // ==================================================================
  // 单例卡片正文（与页面逻辑强绑定；每页只建一份，卡片重建时复用）
  // ==================================================================
  const bannerBody = h(`
    <div class="hero dash-hero">
      <div>
        <div class="hero-title" data-f="hero-title">准备启动</div>
        <div class="hero-sub" data-f="hero-sub">选择实例、版本和账号，然后一键进入世界。</div>
      </div>
      <div class="form-row">
        <button class="btn btn-primary" data-f="launch" style="min-width:160px;height:44px">▶ 启动游戏</button>
        <button class="btn btn-danger" data-f="stop" style="display:none;height:44px">⏹ 停止</button>
        <button class="btn" data-f="setup">版本设置</button>
        <button class="btn" data-f="shortcut">桌面快捷方式</button>
        <button class="btn" data-f="script">导出启动脚本</button>
        <button class="btn" data-f="copy-cmd">复制启动命令</button>
      </div>
      <div data-f="progress-card" style="display:none">
        <div class="progress-bar"><div class="progress-bar-fill" data-f="progress" style="width:0%"></div></div>
        <div data-f="progress-text" style="font-size:12px;color:var(--text-secondary);margin-top:6px"></div>
      </div>
    </div>`);
  const configBody = h(`
    <div class="dash-config">
      <div class="form-row">
        <div class="form-group" style="flex:1;min-width:140px"><label class="form-label">实例</label><select class="select" data-f="instance" style="width:100%"></select></div>
        <div class="form-group" style="flex:1;min-width:140px"><label class="form-label">版本</label><select class="select" data-f="version" style="width:100%"></select></div>
      </div>
      <div class="form-row">
        <div class="form-group" style="flex:1;min-width:140px"><label class="form-label">账号</label><select class="select" data-f="account" style="width:100%"></select></div>
        <div class="form-group" style="flex:1;min-width:140px"><label class="form-label">离线用户名</label><input class="input" data-f="username" style="width:100%"></div>
      </div>
      <div class="form-row">
        <div class="form-group" style="flex:1;min-width:140px"><label class="form-label">Java</label><select class="select" data-f="java" style="width:100%"></select></div>
        <div class="form-group"><label class="form-label">内存 MB</label><input class="input" data-f="memory" type="number" style="width:100px"></div>
      </div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">宽</label><input class="input" data-f="width" type="number" style="width:80px"></div>
        <div class="form-group"><label class="form-label">高</label><input class="input" data-f="height" type="number" style="width:80px"></div>
        <div class="form-group" style="flex:1;min-width:150px"><label class="form-label">直连服务器（可选）</label><input class="input" data-f="server" placeholder="host 或 host:port" style="width:100%"></div>
      </div>
      <div class="form-row">
        <button class="btn btn-sm" data-f="ms-login" title="设备码登录微软账号">微软登录</button>
      </div>
    </div>`);
  const logBody = h('<div class="log-box dash-log" data-placeholder="启动日志将输出到这里…"></div>');
  const newsBody = h(`
    <div>
      <div class="dash-news-head"><button class="btn btn-sm" data-f="news-refresh" title="刷新新闻">↻ 刷新</button></div>
      <div data-f="news" style="font-size:13px;color:var(--text-secondary)">加载中…</div>
    </div>`);
  const skinBody = h(`
    <div class="dash-skin">
      <div class="skin-preview"><img data-f="skin" alt="" style="display:none"></div>
      <div data-f="skin-name" style="text-align:center;font-size:12px;color:var(--text-secondary);margin-top:8px">—</div>
    </div>`);

  const instanceSelect = f<HTMLSelectElement>(configBody, 'instance');
  const versionSelect = f<HTMLSelectElement>(configBody, 'version');
  const accountSelect = f<HTMLSelectElement>(configBody, 'account');
  const javaSelect = f<HTMLSelectElement>(configBody, 'java');
  const usernameInput = f<HTMLInputElement>(configBody, 'username');
  const memoryInput = f<HTMLInputElement>(configBody, 'memory');
  const widthInput = f<HTMLInputElement>(configBody, 'width');
  const heightInput = f<HTMLInputElement>(configBody, 'height');
  const serverInput = f<HTMLInputElement>(configBody, 'server');
  const btnLaunch = f<HTMLButtonElement>(bannerBody, 'launch');
  const btnStop = f<HTMLButtonElement>(bannerBody, 'stop');
  const logEl = logBody;
  const progressCard = f<HTMLDivElement>(bannerBody, 'progress-card');
  const progressFill = f<HTMLDivElement>(bannerBody, 'progress');
  const progressText = f<HTMLDivElement>(bannerBody, 'progress-text');
  const heroTitle = f(bannerBody, 'hero-title');
  const heroSub = f(bannerBody, 'hero-sub');
  usernameInput.value = store.currentUsername || 'Player';
  memoryInput.value = String(store.currentMemory || settings.default_memory_mb || 4096);
  widthInput.value = String(store.currentWidth || (settings.default_resolution || [854, 480])[0]);
  heightInput.value = String(store.currentHeight || (settings.default_resolution || [854, 480])[1]);
  serverInput.value = store.currentServer || '';

  // ==================================================================
  // 多例卡片正文：数据全部存在 item.settings 里随布局落盘（与 Qt 互通）
  // ==================================================================
  const quickRebuilders = new WeakMap<HTMLElement, () => void>();
  const makeQuickBody = (_card: DashboardCard, item: LayoutItem): HTMLElement => {
    const body = h('<div class="dash-quick"><div class="quick-grid"></div></div>');
    const grid = body.firstElementChild as HTMLElement;
    const rebuild = () => {
      grid.innerHTML = '';
      for (const key of quickTargets(item)) {
        const t = QUICK_TARGETS.find((x) => x.key === key)!;
        const btn = h(`<button class="quick-btn" type="button"><strong>${escapeHtml(t.label)}</strong><span style="font-size:11px;color:var(--text-secondary)">${escapeHtml(t.page)}</span></button>`);
        btn.addEventListener('click', () => router.navigate(t.page));
        grid.appendChild(btn);
      }
    };
    rebuild();
    quickRebuilders.set(body, rebuild);
    return body;
  };
  const quickSettings = async (_canvas: DashboardCanvas, card: DashboardCard, item: LayoutItem) => {
    const current = new Set(quickTargets(item));
    const values = await formDialog('选择快捷入口', QUICK_TARGETS.map((t) => ({
      id: t.key, label: t.label, type: 'checkbox' as const, value: current.has(t.key),
    })));
    if (!values) return;
    const picked = QUICK_TARGETS.filter((t) => values[t.key] === 'true').map((t) => t.key);
    if (!picked.length) return; // 一个都不选 = 不改（对齐 Qt QuickSettingsDialog.accept）
    item.settings.targets = picked;
    if (card.body) quickRebuilders.get(card.body)?.();
    persistSoon();
  };

  const makeNotesBody = (_card: DashboardCard, item: LayoutItem): HTMLElement => {
    const ta = h('<textarea class="input dash-notes" placeholder="写点什么，自动保存"></textarea>') as HTMLTextAreaElement;
    let text = String(item.settings.text ?? '');
    if (!text) {
      // 旧版 eziapp 的本机便签：搬进布局文档，落盘成功后再删本机那份，不丢
      let legacy = '';
      try { legacy = localStorage.getItem(LEGACY_NOTE_KEY) || ''; } catch { /* ignore */ }
      if (legacy) {
        text = legacy;
        item.settings.text = legacy;
        legacyNotePending = true;
        persistSoon();
      }
    }
    ta.value = text;
    let timer = 0;
    const commit = () => { timer = 0; item.settings.text = ta.value; persistSoon(); };
    ta.addEventListener('input', () => {
      if (timer) clearTimeout(timer);
      timer = window.setTimeout(commit, 600);
    });
    bodyCleanups.set(ta, () => { if (timer) { clearTimeout(timer); timer = 0; item.settings.text = ta.value; } });
    return ta;
  };

  const makePlaytimeBody = (card: DashboardCard, _item: LayoutItem): HTMLElement => {
    const body = h('<div><div class="dash-stat">总时长：—</div><div class="dash-stat-detail"></div></div>');
    const total = body.children[0] as HTMLElement;
    const detail = body.children[1] as HTMLElement;
    const load = async () => {
      try {
        const [sec, all] = await Promise.all([
          bridge.call<number>('get_total_playtime'),
          bridge.call<Record<string, any>>('get_all_playtime').catch(() => ({} as Record<string, any>)),
        ]);
        total.textContent = `总时长：${fmtDuration(Number(sec) || 0)}`;
        const rows = Object.entries(all || {})
          .map(([name, info]) => [name, Number(info?.total) || 0] as const)
          .filter(([, s]) => s > 0)
          .sort((a, b) => b[1] - a[1])
          .slice(0, 5);
        detail.textContent = rows.map(([name, s]) => `${name}  ${fmtDuration(s)}`).join('\n');
      } catch { /* 桥接未就绪时保留占位，下次 refresh 再来 */ }
    };
    card.refresh = () => { void load(); };
    void load();
    return body;
  };

  const makeTasksBody = (_card: DashboardCard, _item: LayoutItem): HTMLElement => {
    const body = h('<div><div class="dash-stat">下载任务：0</div><div class="dash-stat-detail">暂无任务</div></div>');
    const count = body.children[0] as HTMLElement;
    const last = body.children[1] as HTMLElement;
    let shown = -1;
    const paint = () => {
      if (store.taskCount === shown) return;
      shown = store.taskCount;
      count.textContent = `下载任务：${shown}`;
      if (shown === 0) last.textContent = '暂无任务';
    };
    const unsubStore = store.subscribe(paint);
    const unsubFinished = bridge.subscribe('finished', (d: any) => {
      last.textContent = (d.success ? '✓ ' : '✗ ') + String(d.message || '').slice(0, 120);
    });
    paint();
    bodyCleanups.set(body, () => { unsubStore(); unsubFinished(); });
    return body;
  };

  // ==================================================================
  // 注册表（顺序 = 调色板顺序；前 8 种与 Qt 同名同义，skin 为 eziapp 独有）
  // ==================================================================
  const registry: Record<string, CardSpec> = {
    banner: {
      key: 'banner', title: '启动横幅', icon: '🏠', desc: '启动横幅 — 大标题与启动/停止按钮、进度条',
      single: true, chrome: false, padded: false, makeBody: () => bannerBody, onRemoved: keep,
    },
    config: {
      key: 'config', title: '启动配置', icon: '⚙', desc: '启动配置 — 实例/版本/账号/内存等表单',
      single: true, makeBody: () => configBody, onRemoved: keep,
    },
    log: {
      key: 'log', title: '实时日志', icon: '📄', desc: '实时日志 — 游戏输出与启动过程',
      single: true, makeBody: () => logBody, onRemoved: keep,
    },
    news: {
      key: 'news', title: '新闻 / 主页', icon: '📰', desc: '主页 — Minecraft 新闻 / 自定义主页',
      single: true, makeBody: () => newsBody, onRemoved: keep,
    },
    quick: {
      key: 'quick', title: '快捷入口', icon: '🧭', desc: '快捷入口 — 一键跳转到常用页面，可配置显示哪些',
      makeBody: makeQuickBody, onSettings: quickSettings, onRemoved: drop,
    },
    notes: {
      key: 'notes', title: '便签', icon: '📝', desc: '便签 — 自动保存的随手记',
      makeBody: makeNotesBody, onRemoved: drop,
    },
    playtime: {
      key: 'playtime', title: '游戏时长', icon: '⏱', desc: '游戏时长 — 总量与各实例排行',
      makeBody: makePlaytimeBody, onRemoved: drop,
    },
    tasks: {
      key: 'tasks', title: '任务摘要', icon: '⬇', desc: '任务摘要 — 下载任务数量与最近结果',
      makeBody: makeTasksBody, onRemoved: drop,
    },
    skin: {
      key: 'skin', title: '皮肤', icon: '🧍', desc: '皮肤 — 当前账号的皮肤预览',
      single: true, makeBody: () => skinBody, onRemoved: keep,
    },
  };

  const canvas = new DashboardCanvas(registry, host);
  canvas.onChange = () => persistSoon();

  // 读布局：桥接可能还没连上（首屏先于 initBridge 画出来），失败先摆默认布局，
  // 连上后再读一次；连着的时候还读不到才算真失败。
  let layoutLoaded = false;
  let layoutLoading = false;
  const loadLayout = async () => {
    if (layoutLoaded || layoutLoading) return;
    layoutLoading = true;
    const wasConnected = store.bridgeConnected;
    try {
      const res = await bridge.call<{ doc?: unknown }>('get_layout');
      if (!host.isConnected) return;
      layoutLoaded = true;
      canvas.buildFromDoc(docFromDict(res?.doc));
    } catch (e) {
      if (!host.isConnected) return;
      if (!canvas.cards.length) canvas.buildFromDoc(defaultDoc());
      if (wasConnected) {
        layoutLoaded = true;
        toast(errorMessage(e, '读取启动页布局失败，先用默认布局'), 'warning');
      }
    } finally {
      layoutLoading = false;
    }
  };
  void loadLayout();

  // 三处「编辑布局」入口的落点：侧栏按钮 / 设置页 / 画布右上角悬浮入口
  attachLayoutEditor(() => canvas.setEditMode(true));

  // ==================================================================
  // 页面逻辑（启动 / 停止 / 进度 / 日志 / 新闻 / 皮肤 / 时长），行为与改造前一致
  // ==================================================================
  async function loadAccounts() {
    try {
      store.setAccounts(await bridge.call<any[]>('get_account_rows'));
      populateSelects();
      void refreshSkin();
    } catch { /* ignore */ }
  }

  function populateSelects() {
    instanceSelect.innerHTML = store.instances.map((i) => `<option value="${escapeHtml(i.name)}">${escapeHtml(i.name)} (${escapeHtml(i.mc || '?')})</option>`).join('');
    if (store.currentInstance) instanceSelect.value = store.currentInstance;
    // 版本框只放该实例已安装的版本（远程清单由下面的异步调用覆盖前，先给占位）
    if (!versionSelect.dataset.filled) {
      versionSelect.innerHTML = '<option value="">读取已安装版本…</option>';
    }
    accountSelect.innerHTML = '<option value="离线模式">离线模式</option>' +
      store.accounts.map((a) => `<option value="${escapeHtml(a.name)}" ${a.active ? 'selected' : ''}>${escapeHtml(a.name)}</option>`).join('');
    accountSelect.value = store.currentAccount || store.activeAccount || '离线模式';
    javaSelect.innerHTML = '<option value="自动选择">自动选择</option>' +
      store.javaList.map((j) => `<option value="${escapeHtml(j.path)}">${escapeHtml(j.name)} (Java ${escapeHtml(j.major)})</option>`).join('');
    if (store.currentJava) javaSelect.value = store.currentJava;
    const inst = instanceSelect.value || '实例';
    const ver = versionSelect.value || '未选版本';
    heroTitle.textContent = store.gameRunning ? '游戏运行中' : `启动 ${ver}`;
    heroSub.textContent = `${inst} · ${accountSelect.value || '离线'}`;
  }
  populateSelects();

  const fillVersions = (versions: string[]) => {
    versionSelect.dataset.filled = '1';
    versionSelect.innerHTML = versions.length
      ? versions.map((v) => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('')
      : '<option value="">无已安装版本，请到下载页安装</option>';
    if (store.currentVersion && versions.includes(store.currentVersion)) versionSelect.value = store.currentVersion;
    else if (versions.length) { versionSelect.value = versions[0]; store.currentVersion = versions[0]; }
    populateSelects();
  };
  void bridge.call<string[]>('get_installed_versions', { instance: instanceSelect.value || store.currentInstance || 'default' })
    .then(fillVersions).catch(() => undefined);

  const mode = String(settings.homepage_mode || 'news');
  const news = f(newsBody, 'news');
  const paintNews = (items: any[]) => {
    const rows = Array.isArray(items) ? items.slice(0, 4) : [];
    news.innerHTML = rows.length
      ? rows.map((n) => `<div style="padding:8px 0;border-bottom:1px solid var(--border-light)"><strong>${escapeHtml(n.title || n.version || '新闻')}</strong><div style="font-size:12px;margin-top:4px">${escapeHtml((n.body || '').slice(0, 120))}</div></div>`).join('')
      : '暂无新闻。点右上角 ↻ 刷新。';
  };
  if (mode === 'blank') news.textContent = '主页已设为空白';
  else if (mode === 'custom') news.textContent = settings.custom_homepage ? `自定义主页：${settings.custom_homepage}` : '未设置自定义主页';
  else {
    // 先铺缓存，再后台拉最新（对齐 Qt 版 _load_news）
    void bridge.call<any[]>('cached_news').then(paintNews).catch(() => { news.textContent = '新闻暂不可用'; });
    void bridge.call<any[]>('fetch_news').then((items) => {
      if (host.isConnected && Array.isArray(items) && items.length) paintNews(items);
    }).catch(() => undefined);
  }
  f(newsBody, 'news-refresh').addEventListener('click', async () => {
    news.textContent = '刷新中…';
    try { paintNews(await bridge.call<any[]>('fetch_news')); }
    catch (e: any) { news.textContent = e?.message || '新闻刷新失败'; }
  });

  // 皮肤预览：跟随启动页账号选择
  const skinImg = f<HTMLImageElement>(skinBody, 'skin');
  const skinName = f(skinBody, 'skin-name');
  const refreshSkin = async () => {
    const name = accountSelect.value || '';
    const row = store.accounts.find((a) => a.name === name);
    let body = row?.body || '';
    if (!body) {
      try { body = (await bridge.call<{ body?: string }>('skin_urls', { account_name: name }))?.body || ''; }
      catch { body = ''; }
    }
    if (body) {
      skinImg.src = body;
      skinImg.style.display = '';
      skinImg.onerror = () => { skinImg.style.display = 'none'; };
    } else {
      skinImg.style.display = 'none';
    }
    skinName.textContent = name === '离线模式' ? (usernameInput.value || 'Player') : (name || '—');
  };
  void refreshSkin();

  let wasRunning = store.gameRunning;
  const paintTasks = () => {
    if (store.gameRunning) { btnLaunch.style.display = 'none'; btnStop.style.display = ''; }
    else { btnLaunch.style.display = ''; btnStop.style.display = 'none'; }
    populateSelects();
    if (store.bridgeConnected) void loadLayout();
    // 游戏退出后时长有变化，让时长卡等重新拉一次
    if (wasRunning && !store.gameRunning) canvas.refreshCards();
    wasRunning = store.gameRunning;
  };
  const unsub = store.subscribe(paintTasks);
  paintTasks();

  registerPageCleanup(() => {
    attachLayoutEditor(null);
    unsub();
    for (const fn of bodyCleanups.values()) { try { fn(); } catch { /* ignore */ } }
    bodyCleanups.clear();
    // 便签还在防抖 / 几何刚改完没来得及落盘：离开前补一次
    if (persistTimer) void persistNow();
    canvas.destroy();
  });

  f(bannerBody, 'setup').addEventListener('click', () => {
    if (!versionSelect.value) return toast('请先选择版本', 'warning');
    void showVersionSetup(instanceSelect.value || 'default', versionSelect.value);
  });
  f(bannerBody, 'shortcut').addEventListener('click', async () => {
    try {
      await bridge.call('create_desktop_shortcut', { instance: instanceSelect.value, version: versionSelect.value, username: usernameInput.value });
      toast('已创建桌面快捷方式', 'success');
    } catch (e: any) { toast(e.message || '创建失败', 'error'); }
  });
  f(bannerBody, 'script').addEventListener('click', async () => {
    try {
      const dest = await bridge.call<string>('export_launch_script', { instance: instanceSelect.value, version: versionSelect.value });
      toast(dest ? `已导出 ${dest}` : '已导出启动脚本', 'success');
    } catch (e: any) { toast(e.message || '导出失败', 'error'); }
  });
  f(configBody, 'ms-login').addEventListener('click', async () => {
    const { showMicrosoftLogin } = await import('./dialogs');
    showMicrosoftLogin((ok) => { if (ok) void loadAccounts(); });
  });
  f(bannerBody, 'copy-cmd').addEventListener('click', async () => {
    if (!versionSelect.value) return toast('请先选择版本', 'warning');
    try {
      const cmd = await bridge.call<string>('build_launch_command', {
        instance: instanceSelect.value || 'default', version: versionSelect.value,
        account: accountSelect.value, username: usernameInput.value || 'Player',
        memory_mb: parseInt(memoryInput.value) || 4096,
        width: parseInt(widthInput.value) || 854, height: parseInt(heightInput.value) || 480,
        java: javaSelect.value,
      });
      await navigator.clipboard.writeText(cmd);
      toast('启动命令已复制到剪贴板', 'success');
    } catch (e: any) { toast(e.message || '复制失败', 'error'); }
  });

  btnLaunch.addEventListener('click', async () => {
    const instance = instanceSelect.value;
    const version = versionSelect.value;
    const account = accountSelect.value;
    const username = usernameInput.value || 'Player';
    const java = javaSelect.value === '自动选择' ? '' : javaSelect.value;
    const memory = parseInt(memoryInput.value) || 4096;
    const width = parseInt(widthInput.value) || 854;
    const height = parseInt(heightInput.value) || 480;
    if (!version) return toast('请先选择或安装一个 Minecraft 版本', 'warning');
    // 直连服务器：host[:port] → --server/--port（对齐 Qt 版 _on_launch）
    const serverText = serverInput.value.trim();
    let extraGameArgs: string[] | null = null;
    if (serverText) {
      if (serverText.includes(':')) {
        const [hostName, port] = serverText.split(/:(?!.*:)/);
        extraGameArgs = ['--server', hostName, '--port', port];
      } else {
        extraGameArgs = ['--server', serverText, '--port', '25565'];
      }
    }
    let force = false;
    try {
      const pf = await bridge.call<{ items?: any[] }>('preflight_launch', { instance, version, memory_mb: memory, java });
      const verdict = await preflightDialog(Array.isArray(pf?.items) ? pf!.items : []);
      if (verdict === 'cancel') return;
      force = verdict === 'force';
    } catch (e: any) { return toast(e?.message || '启动预检失败', 'error'); }
    progressCard.style.display = 'block';
    logEl.textContent = '';
    progressFill.style.width = '0%';
    progressText.textContent = '启动中...';
    let crashShown = false;
    try {
      const taskId = await bridge.call<string>('launch_game', {
        instance, version, account, username, java,
        memory_mb: memory, width, height, extra_game_args: extraGameArgs, force,
      });
      currentLaunchTaskId = taskId;
      store.gameRunning = true;
      btnLaunch.style.display = 'none';
      btnStop.style.display = '';
      const unsubProgress = bridge.subscribe('progress', (data: any) => {
        if (data.task_id !== taskId) return;
        smoothProgress(progressFill, data.total > 0 ? (data.current / data.total) * 100 : 0);
        progressText.textContent = data.message || `${data.current}/${data.total}`;
      });
      const unsubLog = bridge.subscribe('log', (data: any) => {
        if (data.task_id !== taskId) return;
        logEl.textContent += data.text + '\n';
        logEl.scrollTop = logEl.scrollHeight;
      });
      const unsubFinished = bridge.subscribe('finished', (data: any) => {
        if (data.task_id !== taskId) return;
        store.gameRunning = false;
        btnLaunch.style.display = '';
        btnStop.style.display = 'none';
        unsubProgress(); unsubLog(); unsubFinished();
        if (data.success) { toast('游戏已启动！', 'success'); return; }
        if (crashShown || data.crash) return;
        if (String(data.message || '') === '已取消') { toast('已停止', 'info'); return; }
        // 启动器阶段失败（还没产出不崩溃报告）：合成一份，对齐 Qt 版 _on_finished
        void crashDialog({
          title: '启动失败', headline: '启动中止',
          detail: String(data.message || '启动失败'),
          help: '这是启动器在拉起游戏之前捕获的错误，还没有游戏崩溃报告。',
          instance, version, task_id: taskId,
        }).then((relaunch) => { if (relaunch) btnLaunch.click(); });
      });
      bridge.subscribe('crash', (data: any) => {
        if (data.task_id !== taskId) return;
        crashShown = true;
        void crashDialog(data).then((relaunch) => { if (relaunch) btnLaunch.click(); });
      });
    } catch (e: any) {
      toast(e.message || '启动失败', 'error');
      btnLaunch.style.display = '';
      btnStop.style.display = 'none';
    }
  });
  btnStop.addEventListener('click', async () => {
    try { await bridge.call('cancel_task', { task_id: currentLaunchTaskId }); toast('已发送停止信号', 'info'); }
    catch (e: any) { toast(e.message || '停止失败', 'error'); }
  });
  instanceSelect.addEventListener('change', async () => {
    store.currentInstance = instanceSelect.value;
    try {
      fillVersions(await bridge.call<string[]>('get_installed_versions', { instance: instanceSelect.value }));
    } catch { /* ignore */ }
  });
  versionSelect.addEventListener('change', () => { store.currentVersion = versionSelect.value; populateSelects(); });
  accountSelect.addEventListener('change', () => { store.currentAccount = accountSelect.value; populateSelects(); void refreshSkin(); });
  usernameInput.addEventListener('change', () => { store.currentUsername = usernameInput.value || 'Player'; void refreshSkin(); });
  serverInput.addEventListener('change', () => { store.currentServer = serverInput.value.trim(); });
  memoryInput.addEventListener('change', () => { store.currentMemory = parseInt(memoryInput.value) || 4096; });
  widthInput.addEventListener('change', () => { store.currentWidth = parseInt(widthInput.value) || 854; });
  heightInput.addEventListener('change', () => { store.currentHeight = parseInt(heightInput.value) || 480; });
  javaSelect.addEventListener('change', () => { store.currentJava = javaSelect.value; });

  // 总时长展示已移到「游戏时长」卡；横幅副标题里不再重复。首屏数字滚动留给时长卡自己。
  void countUp;
}

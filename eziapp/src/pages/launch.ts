import { bridge } from '../bridge';
import { router } from '../router';
import { store } from '../store';
import { toast, registerPageCleanup } from '../ui';
import { countUp, smoothProgress } from '../motion';
import { escapeHtml } from './common';
import { crashDialog, preflightDialog, showVersionSetup } from './dialogs';

let currentLaunchTaskId = '';

const QUICK = [
  ['vanilla', '原版'], ['mods-catalog', 'Mod'], ['mods', '模组'], ['modpacks', '整合包'], ['worlds', '世界'],
  ['instances', '实例'], ['accounts', '账号'], ['java', 'Java'], ['multiplayer', '联机'],
  ['servers', '服务器'], ['playtime', '时长'], ['ai', 'AI'], ['settings', '设置'],
];

export function renderLaunchPage(container: HTMLElement) {
  const noteKey = 'pymcl.notes';
  const settings = (store.settings || {}) as any;
  container.innerHTML = `
    <div class="dash">
      <div class="card hero dash-wide">
        <div>
          <div class="hero-title" id="hero-title">准备启动</div>
          <div class="hero-sub" id="hero-sub">选择实例、版本和账号，然后一键进入世界。</div>
        </div>
        <div class="form-row" style="gap:12px;flex-wrap:wrap">
          <div class="form-group" style="min-width:160px;flex:1"><label class="form-label">实例</label><select class="select" id="launch-instance" style="width:100%"></select></div>
          <div class="form-group" style="min-width:160px;flex:1"><label class="form-label">版本</label><select class="select" id="launch-version" style="width:100%"></select></div>
          <div class="form-group" style="min-width:160px;flex:1"><label class="form-label">账号</label><select class="select" id="launch-account" style="width:100%"></select></div>
          <div class="form-group"><label class="form-label">&nbsp;</label><button class="btn" id="btn-ms-login" title="设备码登录微软账号">微软登录</button></div>
        </div>
        <div class="form-row">
          <button class="btn btn-primary" id="btn-launch" style="min-width:160px;height:44px">▶ 启动游戏</button>
          <button class="btn btn-danger" id="btn-stop" style="display:none">⏹ 停止</button>
          <button class="btn" id="btn-setup">版本设置</button>
          <button class="btn" id="btn-shortcut">桌面快捷方式</button>
          <button class="btn" id="btn-script">导出启动脚本</button>
          <button class="btn" id="btn-copy-cmd">复制启动命令</button>
        </div>
        <div id="launch-progress-card" style="display:none">
          <div class="progress-bar"><div class="progress-bar-fill" id="launch-progress" style="width:0%"></div></div>
          <div id="launch-progress-text" style="font-size:12px;color:var(--text-secondary);margin-top:6px"></div>
        </div>
      </div>
      <div class="card">
        <div class="card-header">启动配置</div>
        <div class="form-row">
          <div class="form-group" style="flex:1"><label class="form-label">离线用户名</label><input class="input" id="launch-username" style="width:100%" value="${escapeHtml(store.currentUsername || 'Player')}"></div>
          <div class="form-group" style="flex:1"><label class="form-label">Java</label><select class="select" id="launch-java" style="width:100%"></select></div>
        </div>
        <div class="form-row">
          <div class="form-group"><label class="form-label">内存 MB</label><input class="input" id="launch-memory" type="number" value="${store.currentMemory || settings.default_memory_mb || 4096}" style="width:110px"></div>
          <div class="form-group"><label class="form-label">宽</label><input class="input" id="launch-width" type="number" value="${store.currentWidth || (settings.default_resolution || [854, 480])[0]}" style="width:80px"></div>
          <div class="form-group"><label class="form-label">高</label><input class="input" id="launch-height" type="number" value="${store.currentHeight || (settings.default_resolution || [854, 480])[1]}" style="width:80px"></div>
          <div class="form-group" style="flex:1;min-width:180px"><label class="form-label">直连服务器（可选）</label><input class="input" id="launch-server" style="width:100%" placeholder="host 或 host:port" value="${escapeHtml(store.currentServer || '')}"></div>
        </div>
      </div>
      <div class="card">
        <div class="card-header">皮肤</div>
        <div class="skin-preview"><img id="launch-skin" alt="" style="display:none"></div>
        <div id="launch-skin-name" style="text-align:center;font-size:12px;color:var(--text-secondary);margin-top:8px">—</div>
      </div>
      <div class="card">
        <div class="card-header">快捷入口</div>
        <div class="quick-grid">${QUICK.map(([k, l]) => `<button class="quick-btn" data-go="${k}"><strong>${escapeHtml(l)}</strong><span style="font-size:11px;color:var(--text-secondary)">${escapeHtml(k)}</span></button>`).join('')}</div>
      </div>
      <div class="card">
        <div class="card-header" style="justify-content:space-between">新闻 / 主页<button class="btn btn-sm" id="btn-news-refresh" title="刷新新闻">↻</button></div>
        <div id="launch-news" style="font-size:13px;color:var(--text-secondary)">加载中…</div>
      </div>
      <div class="card">
        <div class="card-header">便签</div>
        <textarea class="input" id="launch-note" style="width:100%;min-height:140px" placeholder="随便记点东西，只存在本机。"></textarea>
      </div>
      <div class="card">
        <div class="card-header">时长与任务</div>
        <div id="launch-play" style="font-size:22px;font-weight:760;margin-bottom:8px">—</div>
        <div id="launch-tasks" style="font-size:13px;color:var(--text-secondary)">暂无进行中的任务</div>
      </div>
      <div class="card dash-wide" id="launch-log-card" style="display:none">
        <div class="card-header">实时日志</div>
        <div class="log-box" id="launch-log" style="max-height:280px"></div>
      </div>
    </div>`;

  const instanceSelect = document.getElementById('launch-instance') as HTMLSelectElement;
  const versionSelect = document.getElementById('launch-version') as HTMLSelectElement;
  const accountSelect = document.getElementById('launch-account') as HTMLSelectElement;
  const javaSelect = document.getElementById('launch-java') as HTMLSelectElement;
  const usernameInput = document.getElementById('launch-username') as HTMLInputElement;
  const memoryInput = document.getElementById('launch-memory') as HTMLInputElement;
  const widthInput = document.getElementById('launch-width') as HTMLInputElement;
  const heightInput = document.getElementById('launch-height') as HTMLInputElement;
  const btnLaunch = document.getElementById('btn-launch') as HTMLButtonElement;
  const btnStop = document.getElementById('btn-stop') as HTMLButtonElement;
  const logEl = document.getElementById('launch-log') as HTMLDivElement;
  const logCard = document.getElementById('launch-log-card') as HTMLDivElement;
  const progressCard = document.getElementById('launch-progress-card') as HTMLDivElement;
  const progressFill = document.getElementById('launch-progress') as HTMLDivElement;
  const progressText = document.getElementById('launch-progress-text') as HTMLDivElement;
  const serverInput = document.getElementById('launch-server') as HTMLInputElement;
  const heroTitle = document.getElementById('hero-title')!;
  const heroSub = document.getElementById('hero-sub')!;
  const note = document.getElementById('launch-note') as HTMLTextAreaElement;
  note.value = localStorage.getItem(noteKey) || '';
  note.addEventListener('input', () => localStorage.setItem(noteKey, note.value));

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
  const news = document.getElementById('launch-news')!;
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
      if (container.isConnected && Array.isArray(items) && items.length) paintNews(items);
    }).catch(() => undefined);
  }
  document.getElementById('btn-news-refresh')?.addEventListener('click', async () => {
    news.textContent = '刷新中…';
    try { paintNews(await bridge.call<any[]>('fetch_news')); }
    catch (e: any) { news.textContent = e?.message || '新闻刷新失败'; }
  });

  // 皮肤预览：跟随启动页账号选择
  const skinImg = document.getElementById('launch-skin') as HTMLImageElement;
  const skinName = document.getElementById('launch-skin-name')!;
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

  void bridge.call<number>('get_total_playtime').then((sec) => {
    const s = Number(sec) || 0;
    countUp(document.getElementById('launch-play'), s,
      (v) => `${Math.floor(v / 3600)} 小时 ${Math.floor((v % 3600) / 60)} 分`, 900);
  }).catch(() => undefined);

  const paintTasks = () => {
    const running = Array.from(store.tasks.values()).filter((t) => t.success === undefined);
    document.getElementById('launch-tasks')!.textContent = running.length
      ? running.map((t) => t.title || t.message || '任务').join(' · ')
      : '暂无进行中的任务';
    if (store.gameRunning) { btnLaunch.style.display = 'none'; btnStop.style.display = ''; }
    else { btnLaunch.style.display = ''; btnStop.style.display = 'none'; }
    populateSelects();
  };
  const unsub = store.subscribe(paintTasks);
  registerPageCleanup(unsub);

  container.querySelectorAll<HTMLButtonElement>('[data-go]').forEach((btn) => {
    btn.addEventListener('click', () => router.navigate(btn.dataset.go as any));
  });
  document.getElementById('btn-setup')?.addEventListener('click', () => {
    if (!versionSelect.value) return toast('请先选择版本', 'warning');
    void showVersionSetup(instanceSelect.value || 'default', versionSelect.value);
  });
  document.getElementById('btn-shortcut')?.addEventListener('click', async () => {
    try {
      await bridge.call('create_desktop_shortcut', { instance: instanceSelect.value, version: versionSelect.value, username: usernameInput.value });
      toast('已创建桌面快捷方式', 'success');
    } catch (e: any) { toast(e.message || '创建失败', 'error'); }
  });
  document.getElementById('btn-script')?.addEventListener('click', async () => {
    try {
      const dest = await bridge.call<string>('export_launch_script', { instance: instanceSelect.value, version: versionSelect.value });
      toast(dest ? `已导出 ${dest}` : '已导出启动脚本', 'success');
    } catch (e: any) { toast(e.message || '导出失败', 'error'); }
  });
  document.getElementById('btn-ms-login')?.addEventListener('click', async () => {
    const { showMicrosoftLogin } = await import('./dialogs');
    showMicrosoftLogin((ok) => { if (ok) void loadAccounts(); });
  });
  document.getElementById('btn-copy-cmd')?.addEventListener('click', async () => {
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
        const [host, port] = serverText.split(/:(?!.*:)/);
        extraGameArgs = ['--server', host, '--port', port];
      } else {
        extraGameArgs = ['--server', serverText, '--port', '25565'];
      }
    }
    try {
      const pf = await bridge.call<{ items?: any[] }>('preflight_launch', { instance, version, memory_mb: memory, java });
      if (await preflightDialog(Array.isArray(pf?.items) ? pf!.items : []) !== 'continue') return;
    } catch (e: any) { return toast(e?.message || '启动预检失败', 'error'); }
    logCard.style.display = 'block';
    progressCard.style.display = 'block';
    logEl.textContent = '';
    progressFill.style.width = '0%';
    progressText.textContent = '启动中...';
    let crashShown = false;
    try {
      const taskId = await bridge.call<string>('launch_game', {
        instance, version, account, username, java,
        memory_mb: memory, width, height, extra_game_args: extraGameArgs,
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
  versionSelect.addEventListener('change', () => { store.currentVersion = versionSelect.value; });
  accountSelect.addEventListener('change', () => { store.currentAccount = accountSelect.value; void refreshSkin(); });
  usernameInput.addEventListener('change', () => { store.currentUsername = usernameInput.value || 'Player'; void refreshSkin(); });
  serverInput.addEventListener('change', () => { store.currentServer = serverInput.value.trim(); });
  memoryInput.addEventListener('change', () => { store.currentMemory = parseInt(memoryInput.value) || 4096; });
  widthInput.addEventListener('change', () => { store.currentWidth = parseInt(widthInput.value) || 854; });
  heightInput.addEventListener('change', () => { store.currentHeight = parseInt(heightInput.value) || 480; });
  javaSelect.addEventListener('change', () => { store.currentJava = javaSelect.value; });
}

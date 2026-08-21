// 启动页 - 游戏启动主界面
import { bridge } from '../bridge';
import { store } from '../store';
import { toast, registerPageCleanup, preflightDialog, crashDialog } from '../ui';
import { escapeHtml } from './common';

let currentLaunchTaskId = '';

export function renderLaunchPage(container: HTMLElement) {
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px;max-width:800px">
      <div class="card">
        <div class="card-header">🚀 启动游戏</div>
        <div class="form-group">
          <label class="form-label">实例</label>
          <select class="select" id="launch-instance" style="width:100%"></select>
        </div>
        <div class="form-row" style="gap:12px;flex-wrap:wrap">
          <div class="form-group" style="flex:1;min-width:200px">
            <label class="form-label">Minecraft 版本</label>
            <select class="select" id="launch-version" style="width:100%"></select>
          </div>
          <div class="form-group" style="flex:1;min-width:200px">
            <label class="form-label">账号</label>
            <select class="select" id="launch-account" style="width:100%"></select>
          </div>
        </div>
        <div class="form-row" style="gap:12px;flex-wrap:wrap">
          <div class="form-group" style="flex:1;min-width:150px">
            <label class="form-label">离线用户名</label>
            <input class="input" id="launch-username" style="width:100%" value="Player">
          </div>
          <div class="form-group" style="flex:1;min-width:150px">
            <label class="form-label">Java</label>
            <select class="select" id="launch-java" style="width:100%"></select>
          </div>
        </div>
        <div class="form-row" style="gap:12px;flex-wrap:wrap">
          <div class="form-group" style="flex:1;min-width:120px">
            <label class="form-label">内存 (MB)</label>
            <input class="input" id="launch-memory" type="number" style="width:100%" value="4096" min="512" max="65536">
          </div>
          <div class="form-group" style="width:80px">
            <label class="form-label">宽度</label>
            <input class="input" id="launch-width" type="number" style="width:100%" value="854">
          </div>
          <div class="form-group" style="width:80px">
            <label class="form-label">高度</label>
            <input class="input" id="launch-height" type="number" style="width:100%" value="480">
          </div>
        </div>
        <div style="display:flex;gap:8px;margin-top:8px">
          <button class="btn btn-primary" id="btn-launch">▶ 启动游戏</button>
          <button class="btn btn-danger" id="btn-stop" style="display:none">⏹ 停止</button>
        </div>
      </div>

      <div class="card" id="launch-log-card" style="display:none">
        <div class="card-header">📋 日志</div>
        <div class="log-box" id="launch-log" style="max-height:400px;font-size:12px"></div>
      </div>

      <div class="card" id="launch-progress-card" style="display:none">
        <div class="card-header">📊 进度</div>
        <div class="progress-bar" style="margin-bottom:8px"><div class="progress-bar-fill" id="launch-progress" style="width:0%"></div></div>
        <div id="launch-progress-text" style="font-size:12px;color:var(--text-secondary)"></div>
      </div>
    </div>
  `;

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

  function populateSelects() {
    instanceSelect.innerHTML = store.instances.map(i => `<option value="${escapeHtml(i.name)}">${escapeHtml(i.name)} (${escapeHtml(i.mc || '?')})</option>`).join('');
    if (store.currentInstance) instanceSelect.value = store.currentInstance;

    versionSelect.innerHTML = store.versionList.map(v => `<option value="${escapeHtml(v.version)}">${escapeHtml(v.version)} [${escapeHtml(v.type)}]</option>`).join('');
    if (store.currentVersion) versionSelect.value = store.currentVersion;

    accountSelect.innerHTML = '<option value="离线模式">离线模式</option>' +
      store.accounts.map(a => `<option value="${escapeHtml(a.name)}" ${a.active ? 'selected' : ''}>${escapeHtml(a.name)} (${a.type === 'microsoft' ? '正版' : a.type === 'authlib' ? '第三方' : '离线'})</option>`).join('');
    accountSelect.value = store.currentAccount || store.activeAccount || '离线模式';

    javaSelect.innerHTML = '<option value="自动选择">自动选择</option>' +
      store.javaList.map(j => `<option value="${escapeHtml(j.path)}">${escapeHtml(j.name)} (Java ${escapeHtml(j.major)})</option>`).join('');
    if (store.currentJava) javaSelect.value = store.currentJava;
  }

  populateSelects();

  const unsub = store.subscribe(() => {
    populateSelects();
    if (store.gameRunning) {
      btnLaunch.style.display = 'none';
      btnStop.style.display = '';
    } else {
      btnLaunch.style.display = '';
      btnStop.style.display = 'none';
    }
  });

  registerPageCleanup(() => {
    unsub();
    currentLaunchTaskId = '';
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

    if (!version) {
      toast('请先选择或安装一个 Minecraft 版本', 'warning');
      return;
    }

    try {
      const pf = await bridge.call<{ ok?: boolean; items?: any[] }>('preflight_launch', {
        instance, version, memory_mb: memory, java,
      });
      const decision = await preflightDialog(Array.isArray(pf?.items) ? pf!.items : []);
      if (decision !== 'continue') return;
    } catch (e: any) {
      toast(e?.message || '启动预检失败', 'error');
      return;
    }

    logCard.style.display = 'block';
    progressCard.style.display = 'block';
    logEl.textContent = '';
    progressFill.style.width = '0%';
    progressText.textContent = '启动中...';

    try {
      const taskId = await bridge.call<string>('launch_game', {
        instance, version, account, username, java, memory_mb: memory, width, height,
      });
      currentLaunchTaskId = taskId;
      store.launchLog = [];
      store.gameRunning = true;
      btnLaunch.style.display = 'none';
      btnStop.style.display = '';
      toast('游戏启动中...', 'info');

      const unsubProgress = bridge.subscribe('progress', data => {
        const d = data as any;
        if (d.task_id === taskId) {
          const pct = d.total > 0 ? (d.current / d.total) * 100 : 0;
          progressFill.style.width = `${Math.min(pct, 100)}%`;
          progressText.textContent = d.message || `${d.current}/${d.total}`;
        }
      });
      const unsubLog = bridge.subscribe('log', data => {
        const d = data as any;
        if (d.task_id === taskId) {
          store.launchLog.push(d.text);
          logEl.textContent += d.text + '\n';
          logEl.scrollTop = logEl.scrollHeight;
        }
      });
      const unsubFinished = bridge.subscribe('finished', data => {
        const d = data as any;
        if (d.task_id === taskId) {
          store.gameRunning = false;
          btnLaunch.style.display = '';
          btnStop.style.display = 'none';
          unsubProgress(); unsubLog(); unsubFinished();
          if (d.success) toast('游戏已启动！', 'success');
          else if (!d.crash) toast(d.message || '启动失败', 'error');
        }
      });
      const unsubCrash = bridge.subscribe('crash', data => {
        const d = data as any;
        if (d.task_id === taskId) {
          unsubCrash();
          void crashDialog(d).then(relaunch => {
            if (!relaunch) return;
            if (d.instance) instanceSelect.value = d.instance;
            if (d.version) versionSelect.value = d.version;
            btnLaunch.click();
          });
        }
      });
    } catch (e: any) {
      toast(e.message || '启动失败', 'error');
      btnLaunch.style.display = '';
      btnStop.style.display = 'none';
    }
  });

  btnStop.addEventListener('click', async () => {
    try {
      await bridge.call('cancel_task', { task_id: currentLaunchTaskId });
      toast('已发送停止信号', 'info');
    } catch (e: any) {
      toast(e.message || '停止失败', 'error');
    }
  });

  instanceSelect.addEventListener('change', async () => {
    const name = instanceSelect.value;
    store.currentInstance = name;
    try {
      const versions = await bridge.call<string[]>('get_installed_versions', { instance: name });
      versionSelect.innerHTML = versions.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
    } catch { /* 忽略 */ }
  });

  versionSelect.addEventListener('change', () => { store.currentVersion = versionSelect.value; });
  accountSelect.addEventListener('change', () => { store.currentAccount = accountSelect.value; });
  usernameInput.addEventListener('change', () => { store.currentUsername = usernameInput.value || 'Player'; });
  memoryInput.addEventListener('change', () => { store.currentMemory = parseInt(memoryInput.value) || 4096; });
  widthInput.addEventListener('change', () => { store.currentWidth = parseInt(widthInput.value) || 854; });
  heightInput.addEventListener('change', () => { store.currentHeight = parseInt(heightInput.value) || 480; });
  javaSelect.addEventListener('change', () => { store.currentJava = javaSelect.value; });
}

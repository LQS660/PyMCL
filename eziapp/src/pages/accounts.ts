// 账号管理：离线、微软设备代码和 Authlib-Injector 登录。
import { bridge } from '../bridge';
import { store, type AccountInfo } from '../store';
import { confirmDialog, inputDialog, registerPageCleanup, showError, showLoading, toast } from '../ui';
import { errorMessage, escapeHtml } from './common';

interface LoginState {
  taskId: string;
  kind: 'microsoft' | 'authlib';
  status: string;
  code?: string;
  uri?: string;
}

let pageToken = 0;
let loginState: LoginState | null = null;

export function renderAccountsPage(container: HTMLElement) {
  const token = ++pageToken;
  showLoading(container);

  const reload = async () => {
    try {
      const rows = await bridge.call<AccountInfo[]>('get_account_rows');
      if (token !== pageToken || !container.isConnected) return;
      store.setAccounts(Array.isArray(rows) ? rows : []);
      render(container, reload);
    } catch (error) {
      if (token !== pageToken || !container.isConnected) return;
      showError(container, `加载账号失败：${errorMessage(error, '未知错误')}`, () => void reload());
    }
  };

  const removeCodeListener = bridge.subscribe('login_code', (data) => {
    if (!loginState || loginState.kind !== 'microsoft') return;
    loginState.code = String(data.code || '');
    loginState.uri = String(data.uri || '');
    loginState.status = '请在浏览器中输入设备代码完成登录。';
    if (token === pageToken && container.isConnected) render(container, reload);
  });
  const removeStatusListener = bridge.subscribe('login_status', (data) => {
    if (!loginState) return;
    loginState.status = String(data.text || loginState.status);
    if (token === pageToken && container.isConnected) render(container, reload);
  });
  const removeFinishedListener = bridge.subscribe('finished', (data) => {
    if (!loginState || String(data.task_id || '') !== loginState.taskId) return;
    const success = Boolean(data.success);
    const message = String(data.message || (success ? '登录完成' : '登录失败'));
    loginState = null;
    if (success) toast(message, 'success');
    else toast(message, 'error');
    void reload();
  });
  const removeUiChangedListener = bridge.subscribe('ui_changed', () => void reload());
  registerPageCleanup(() => {
    if (token === pageToken) pageToken += 1;
    removeCodeListener();
    removeStatusListener();
    removeFinishedListener();
    removeUiChangedListener();
  });

  void reload();
}

function render(container: HTMLElement, reload: () => Promise<void>) {
  const accounts = store.accounts;
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px;max-width:1000px">
      ${renderLoginStatus()}
      <div class="card">
        <div class="card-header">🔑 添加账号</div>
        <div class="form-row" style="margin-bottom:16px">
          <button class="btn btn-primary" id="account-add-offline">＋ 离线账号</button>
          <button class="btn btn-primary" id="account-add-microsoft">微软账号</button>
        </div>
        <div style="border-top:1px solid var(--border-light);padding-top:16px">
          <div style="font-size:13px;font-weight:600;margin-bottom:10px">第三方登录（Authlib-Injector）</div>
          <div class="form-row" style="align-items:flex-end">
            <div class="form-group" style="min-width:220px;flex:1">
              <label class="form-label">认证服务器 API 地址</label>
              <input class="input" id="authlib-api" style="width:100%" placeholder="https://authserver.example/api/yggdrasil">
            </div>
            <div class="form-group" style="min-width:150px;flex:1">
              <label class="form-label">用户名或邮箱</label>
              <input class="input" id="authlib-username" style="width:100%" autocomplete="username">
            </div>
            <div class="form-group" style="min-width:150px;flex:1">
              <label class="form-label">密码</label>
              <input class="input" id="authlib-password" type="password" style="width:100%" autocomplete="current-password">
            </div>
            <button class="btn" id="account-add-authlib">登录</button>
          </div>
        </div>
      </div>
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px">
          <div class="card-header" style="margin:0">已保存账号</div>
          <button class="btn btn-sm" id="account-refresh">↻ 刷新</button>
        </div>
        ${accounts.length ? `<div class="grid-list">${accounts.map((account, index) => renderAccountCard(account, index)).join('')}</div>` : '<div class="empty-state"><div class="empty-state-icon">👤</div><div>还没有保存账号。可直接使用离线模式启动游戏。</div></div>'}
      </div>
    </div>
  `;

  container.querySelector<HTMLButtonElement>('#account-refresh')?.addEventListener('click', () => void reload());
  container.querySelector<HTMLButtonElement>('#account-add-offline')?.addEventListener('click', async () => {
    const username = await inputDialog('添加离线账号', '游戏内显示的用户名');
    if (!username?.trim()) return;
    try {
      await bridge.call<string>('add_offline_account', { username: username.trim() });
      toast('离线账号已添加', 'success');
      await reload();
    } catch (error) {
      toast(errorMessage(error, '添加离线账号失败'), 'error');
    }
  });
  container.querySelector<HTMLButtonElement>('#account-add-microsoft')?.addEventListener('click', async () => {
    try {
      const taskId = await bridge.call<string>('start_microsoft_login');
      loginState = { taskId, kind: 'microsoft', status: '正在请求微软设备代码…' };
      render(container, reload);
    } catch (error) {
      toast(errorMessage(error, '无法开始微软登录'), 'error');
    }
  });
  container.querySelector<HTMLButtonElement>('#account-add-authlib')?.addEventListener('click', async () => {
    const api = container.querySelector<HTMLInputElement>('#authlib-api')!.value.trim();
    const username = container.querySelector<HTMLInputElement>('#authlib-username')!.value.trim();
    const password = container.querySelector<HTMLInputElement>('#authlib-password')!.value;
    if (!api || !username || !password) {
      toast('请填写认证服务器、用户名和密码', 'warning');
      return;
    }
    try {
      const taskId = await bridge.call<string>('start_authlib_login', { api, username, password });
      loginState = { taskId, kind: 'authlib', status: '正在验证第三方账号…' };
      render(container, reload);
    } catch (error) {
      toast(errorMessage(error, '无法开始第三方登录'), 'error');
    }
  });
  container.querySelector<HTMLButtonElement>('#account-open-microsoft')?.addEventListener('click', () => {
    if (loginState?.uri) window.open(loginState.uri, '_blank', 'noopener');
  });
  container.querySelector<HTMLButtonElement>('#account-cancel-login')?.addEventListener('click', async () => {
    if (!loginState) return;
    try {
      await bridge.call('cancel_task', { task_id: loginState.taskId });
      toast('已请求取消登录', 'info');
    } catch (error) {
      toast(errorMessage(error, '取消登录失败'), 'error');
    }
  });

  container.querySelectorAll<HTMLButtonElement>('[data-account-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      const account = accounts[Number(button.dataset.accountIndex)];
      if (!account) return;
      const action = button.dataset.accountAction;
      try {
        if (action === 'activate') {
          await bridge.call('set_active_account', { name: account.name });
          toast(`${account.name} 已设为当前账号`, 'success');
        } else if (action === 'delete') {
          const confirmed = await confirmDialog('删除账号', `确定要删除账号“${account.name}”吗？`);
          if (!confirmed) return;
          await bridge.call('remove_account', { name: account.name });
          toast('账号已删除', 'success');
        }
        await reload();
      } catch (error) {
        toast(errorMessage(error, '账号操作失败'), 'error');
      }
    });
  });
}

function renderLoginStatus(): string {
  if (!loginState) return '';
  const code = loginState.code
    ? `<div style="font-family:var(--font-mono);font-size:22px;font-weight:700;letter-spacing:2px;margin:6px 0">${escapeHtml(loginState.code)}</div>`
    : '';
  const action = loginState.kind === 'microsoft' && loginState.uri
    ? '<button class="btn btn-sm btn-primary" id="account-open-microsoft">打开微软验证页</button>'
    : '';
  return `
    <div class="card" style="border-color:var(--primary)">
      <div class="card-header">${loginState.kind === 'microsoft' ? '微软登录' : '第三方账号登录'}</div>
      <div style="font-size:13px;color:var(--text-secondary)">${escapeHtml(loginState.status)}</div>
      ${code}
      <div style="display:flex;gap:8px;margin-top:10px">${action}<button class="btn btn-sm" id="account-cancel-login">取消</button></div>
    </div>
  `;
}

function renderAccountCard(account: AccountInfo, index: number): string {
  const typeLabel: Record<string, string> = {
    microsoft: '微软正版',
    offline: '离线账号',
    authlib: '第三方账号',
  };
  const avatar = account.avatar ? `<img src="${escapeHtml(account.avatar)}" alt="" style="width:34px;height:34px;border-radius:50%;object-fit:cover;background:var(--bg-tertiary)">` : '<div style="width:34px;height:34px;border-radius:50%;background:var(--primary-light);display:grid;place-items:center">👤</div>';
  return `
    <div class="grid-item">
      <div style="display:flex;align-items:center;gap:10px">
        ${avatar}
        <div style="min-width:0;flex:1">
          <div class="grid-item-title">${escapeHtml(account.name)}</div>
          <div class="grid-item-meta"><span>${escapeHtml(typeLabel[account.type] || account.type || '账号')}</span>${account.active ? '<span class="tag tag-primary">当前使用</span>' : ''}</div>
        </div>
      </div>
      ${account.api ? `<div style="font-size:11px;color:var(--text-secondary);margin-top:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(account.api)}</div>` : ''}
      <div class="grid-item-actions">
        ${account.active ? '' : `<button class="btn btn-sm btn-primary" data-account-action="activate" data-account-index="${index}">设为当前</button>`}
        <button class="btn btn-sm btn-danger" data-account-action="delete" data-account-index="${index}">删除</button>
      </div>
    </div>
  `;
}

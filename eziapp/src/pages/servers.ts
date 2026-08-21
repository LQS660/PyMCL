// 服务器列表管理页
import { bridge } from '../bridge';
import { store } from '../store';
import { confirmDialog, inputDialog, showError, showLoading, toast } from '../ui';
import { errorMessage, escapeHtml } from './common';

interface ServerRow {
  name?: string;
  ip?: string;
  port?: number;
  description?: string;
}

export function renderServersPage(container: HTMLElement) {
  showLoading(container);
  void loadAndRender(container);
}

async function loadAndRender(container: HTMLElement) {
  const instance = store.currentInstance || store.instances[0]?.name || '';
  try {
    const servers = await bridge.call<ServerRow[]>('list_servers', { instance });
    if (!container.isConnected) return;
    render(container, instance, Array.isArray(servers) ? servers : []);
  } catch (error) {
    if (!container.isConnected) return;
    showError(container, '加载服务器列表失败：' + errorMessage(error, '未知错误'), () => void loadAndRender(container));
  }
}

function render(container: HTMLElement, instance: string, servers: ServerRow[]) {
  const instanceOptions = store.instances.length
    ? store.instances.map((i) => `<option value="${escapeHtml(i.name)}" ${i.name === instance ? 'selected' : ''}>${escapeHtml(i.name)}</option>`).join('')
    : `<option value="">无实例</option>`;

  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px;max-width:960px">
      <div class="card">
        <div class="card-header">🌐 服务器列表</div>
        <div class="form-row" style="gap:12px;flex-wrap:wrap;align-items:flex-end">
          <div class="form-group" style="flex:1;min-width:200px">
            <label class="form-label">实例</label>
            <select class="select" id="servers-instance" style="width:100%">${instanceOptions}</select>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn btn-primary" id="servers-add">添加服务器</button>
            <button class="btn btn-sm" id="servers-import">导入</button>
            <button class="btn btn-sm" id="servers-export">导出</button>
            <button class="btn btn-sm" id="servers-refresh">↻ 刷新</button>
          </div>
        </div>
      </div>
      <div class="card">
        <div id="servers-list">${renderServerTable(servers)}</div>
      </div>
    </div>
  `;

  container.querySelector<HTMLSelectElement>('#servers-instance')?.addEventListener('change', () => {
    const name = container.querySelector<HTMLSelectElement>('#servers-instance')!.value;
    store.currentInstance = name;
    void loadAndRender(container);
  });
  container.querySelector<HTMLButtonElement>('#servers-refresh')?.addEventListener('click', () => void loadAndRender(container));
  container.querySelector<HTMLButtonElement>('#servers-add')?.addEventListener('click', () => void onAdd(container));
  container.querySelector<HTMLButtonElement>('#servers-import')?.addEventListener('click', () => void onImport(container));
  container.querySelector<HTMLButtonElement>('#servers-export')?.addEventListener('click', () => void onExport(container));

  container.querySelectorAll<HTMLButtonElement>('[data-server-edit]').forEach((btn) => {
    btn.addEventListener('click', () => void onEdit(container, Number(btn.dataset.serverEdit)));
  });
  container.querySelectorAll<HTMLButtonElement>('[data-server-delete]').forEach((btn) => {
    btn.addEventListener('click', () => void onDelete(container, Number(btn.dataset.serverDelete), servers));
  });
}

function renderServerTable(servers: ServerRow[]): string {
  if (!servers.length) {
    return '<div class="empty-state"><div class="empty-state-icon">🌐</div><div>暂无服务器，点击「添加服务器」开始添加</div></div>';
  }
  return `
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead>
        <tr style="text-align:left;color:var(--text-secondary);border-bottom:1px solid var(--border-light)">
          <th style="padding:8px 10px">名称</th>
          <th style="padding:8px 10px">地址</th>
          <th style="padding:8px 10px">端口</th>
          <th style="padding:8px 10px">描述</th>
          <th style="padding:8px 10px">操作</th>
        </tr>
      </thead>
      <tbody>
        ${servers.map((s, i) => `
          <tr style="border-bottom:1px solid var(--border-light)">
            <td style="padding:10px">${escapeHtml(s.name || '未命名')}</td>
            <td style="padding:10px">${escapeHtml(s.ip || '')}</td>
            <td style="padding:10px">${escapeHtml(String(s.port ?? 25565))}</td>
            <td style="padding:10px;color:var(--text-secondary)">${escapeHtml((s.description || '').slice(0, 40))}</td>
            <td style="padding:10px">
              <button class="btn btn-sm" data-server-edit="${i}">编辑</button>
              <button class="btn btn-sm btn-danger" data-server-delete="${i}">删除</button>
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function currentInstance(container: HTMLElement): string {
  return container.querySelector<HTMLSelectElement>('#servers-instance')?.value || store.currentInstance || '';
}

async function onAdd(container: HTMLElement) {
  const instance = currentInstance(container);
  if (!instance) {
    toast('请先创建并选择实例', 'warning');
    return;
  }
  const name = await inputDialog('添加服务器', '服务器名称（可选）', '');
  if (name === null) return;
  const ip = await inputDialog('添加服务器', '服务器地址', '');
  if (ip === null || !ip.trim()) {
    toast('地址不能为空', 'warning');
    return;
  }
  const portText = await inputDialog('添加服务器', '端口（默认 25565）', '25565');
  if (portText === null) return;
  const port = /^\d{1,5}$/.test(portText.trim()) ? Number(portText.trim()) : 25565;
  try {
    await bridge.call('add_server', { instance, name: name.trim(), ip: ip.trim(), port });
    toast('服务器已添加', 'success');
    void loadAndRender(container);
  } catch (error) {
    toast(errorMessage(error, '添加失败'), 'error');
  }
}

async function onEdit(container: HTMLElement, index: number) {
  const instance = currentInstance(container);
  let servers: ServerRow[] = [];
  try {
    servers = await bridge.call<ServerRow[]>('list_servers', { instance });
  } catch (error) {
    toast(errorMessage(error, '读取失败'), 'error');
    return;
  }
  const s = servers[index];
  if (!s) return;
  const name = await inputDialog('编辑服务器', '服务器名称', s.name || '');
  if (name === null) return;
  const ip = await inputDialog('编辑服务器', '服务器地址', s.ip || '');
  if (ip === null || !ip.trim()) {
    toast('地址不能为空', 'warning');
    return;
  }
  try {
    await bridge.call('update_server', { instance, index, name: name.trim(), ip: ip.trim(), port: s.port ?? 25565 });
    toast('服务器已更新', 'success');
    void loadAndRender(container);
  } catch (error) {
    toast(errorMessage(error, '更新失败'), 'error');
  }
}

async function onDelete(container: HTMLElement, index: number, servers: ServerRow[]) {
  const s = servers[index];
  if (!s) return;
  const confirmed = await confirmDialog('确认删除', `删除服务器 ${s.name || s.ip || '?'}？`);
  if (!confirmed) return;
  try {
    await bridge.call('delete_server', { instance: currentInstance(container), index });
    toast('已删除', 'success');
    void loadAndRender(container);
  } catch (error) {
    toast(errorMessage(error, '删除失败'), 'error');
  }
}

async function onImport(container: HTMLElement) {
  const instance = currentInstance(container);
  const text = await inputDialog('导入服务器', '粘贴 servers.txt 或 JSON 内容', '');
  if (text === null || !text.trim()) return;
  try {
    const count = await bridge.call<number>('import_servers', { instance, text });
    toast(`已导入 ${Number(count) || 0} 个服务器`, 'success');
    void loadAndRender(container);
  } catch (error) {
    toast(errorMessage(error, '导入失败'), 'error');
  }
}

async function onExport(container: HTMLElement) {
  const instance = currentInstance(container);
  try {
    const text = await bridge.call<string>('export_servers', { instance });
    await navigator.clipboard.writeText(text);
    toast('已复制导出内容到剪贴板', 'success');
  } catch (error) {
    toast(errorMessage(error, '导出失败'), 'error');
  }
}

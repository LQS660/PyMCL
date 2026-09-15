import { bridge } from '../bridge';
import { store } from '../store';
import {
  confirmDialog, enableFileDrop, pickFile, readPickedFile, registerPageCleanup,
  showError, showSkeleton, stashUpload, toast, flyToTasks, type PickedFile,
} from '../ui';
import { errorMessage, escapeHtml, formatBytes } from './common';

interface ModEntry { filename?: string; enabled?: boolean; bytes?: number }
interface Target { label?: string; value?: string }

export function renderModsPage(container: HTMLElement) {
  showSkeleton(container, 'rows', 5);
  void load(container);
}

async function load(container: HTMLElement) {
  if (!store.instances.length) {
    try { store.setInstances(await bridge.call<any[]>('get_instances')); } catch { /* ignore */ }
  }
  const instance = store.currentInstance || store.instances[0]?.name || 'default';
  let targets: Target[] = [{ label: '实例共享 mods 目录', value: '' }];
  try { targets = await bridge.call<Target[]>('get_mods_targets', { instance }) || targets; } catch { /* ignore */ }
  render(container, instance, '', targets, []);
  await reloadList(container);
}

async function reloadList(container: HTMLElement) {
  const instance = (container.querySelector('#mods-instance') as HTMLSelectElement | null)?.value
    || store.currentInstance || store.instances[0]?.name || 'default';
  const version = (container.querySelector('#mods-target') as HTMLSelectElement | null)?.value || '';
  const query = ((container.querySelector('#mods-filter') as HTMLInputElement | null)?.value || '').toLowerCase();
  const listHost = container.querySelector('#mods-list') as HTMLElement | null;
  if (listHost && !listHost.querySelector('.catalog-row')) showSkeleton(listHost, 'rows', 4);
  try {
    const rows = await bridge.call<ModEntry[]>('get_installed_mod_entries', { instance, version });
    paintList(container, (rows || []).filter((r) => !query || String(r.filename || '').toLowerCase().includes(query)));
    const on = (rows || []).filter((r) => r.enabled).length;
    const total = rows?.length || 0;
    const size = (rows || []).reduce((sum, r) => sum + (Number(r.bytes) || 0), 0);
    const pill = container.querySelector('#mods-count');
    if (pill) pill.textContent = `${on}/${total}`;
    const sub = container.querySelector('#mods-subtitle');
    if (sub) sub.textContent = `启用 ${on} · 禁用 ${total - on} · ${formatBytes(size)}${version ? ` · ${version}` : ''}`;
  } catch (e) {
    showError(container.querySelector('#mods-list') as HTMLElement || container, errorMessage(e, '读取模组失败'), () => void reloadList(container));
  }
}

function render(container: HTMLElement, instance: string, version: string, targets: Target[], _rows: ModEntry[]) {
  const instOpts = (store.instances.length ? store.instances : [{ name: instance }]).map((i) =>
    `<option value="${escapeHtml(i.name)}" ${i.name === instance ? 'selected' : ''}>${escapeHtml(i.name)}</option>`).join('');
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px;max-width:1100px">
      <div class="card">
        <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap">
          <div>
            <div class="card-header" style="margin:0">模组管理</div>
            <div style="font-size:12px;color:var(--text-secondary);margin-top:4px" id="mods-subtitle">查看、启禁、导入已安装模组。版本隔离后可切换独立目录。</div>
          </div>
          <span class="tag tag-primary" id="mods-count">0/0</span>
        </div>
        <div class="form-row" style="margin-top:14px;align-items:flex-end">
          <div class="form-group"><label class="form-label">实例</label><select class="select" id="mods-instance">${instOpts}</select></div>
          <div class="form-group"><label class="form-label">目录</label><select class="select" id="mods-target">${targets.map((t) => `<option value="${escapeHtml(t.value || '')}">${escapeHtml(t.label || t.value || '共享')}</option>`).join('')}</select></div>
          <div class="form-group" style="flex:1;min-width:180px"><label class="form-label">筛选</label><input class="input" id="mods-filter" placeholder="按文件名筛选…" style="width:100%"></div>
          <button class="btn" id="mods-folder">打开目录</button>
          <button class="btn" id="mods-import" title="也可以把 jar 直接拖进这个页面">导入 jar</button>
          <button class="btn btn-primary" id="mods-update">检查更新</button>
        </div>
      </div>
      <div class="card" id="mods-list"></div>
    </div>`;
  const instSel = container.querySelector<HTMLSelectElement>('#mods-instance')!;
  const tgtSel = container.querySelector<HTMLSelectElement>('#mods-target')!;
  instSel.addEventListener('change', async () => {
    store.currentInstance = instSel.value;
    try {
      const next = await bridge.call<Target[]>('get_mods_targets', { instance: instSel.value });
      tgtSel.innerHTML = (next || []).map((t) => `<option value="${escapeHtml(t.value || '')}">${escapeHtml(t.label || '')}</option>`).join('');
    } catch { /* ignore */ }
    void reloadList(container);
  });
  tgtSel.addEventListener('change', () => void reloadList(container));
  container.querySelector('#mods-filter')?.addEventListener('input', () => void reloadList(container));
  container.querySelector('#mods-folder')?.addEventListener('click', async () => {
    try { await bridge.call('open_mods_folder', { instance: instSel.value, version: tgtSel.value }); }
    catch (e) { toast(errorMessage(e, '打开失败'), 'error'); }
  });
  container.querySelector('#mods-import')?.addEventListener('click', async () => {
    const picked = await pickFile('.jar,application/java-archive');
    if (!picked) return;
    await importJars(container, instSel, tgtSel, [picked]);
  });
  // 拖一个 jar 进来跟点「导入 jar」等价
  registerPageCleanup(enableFileDrop(
    container,
    async (files) => {
      const picked = (await Promise.all(files.map(readPickedFile))).filter(Boolean) as PickedFile[];
      if (picked.length) await importJars(container, instSel, tgtSel, picked);
    },
    (f) => f.name.toLowerCase().endsWith('.jar'),
  ));
  container.querySelector('#mods-update')?.addEventListener('click', async () => {
    const btn = container.querySelector<HTMLButtonElement>('#mods-update')!;
    btn.disabled = true;
    try {
      const taskId = await bridge.call<string>('start_mod_updates', { instance: instSel.value });
      toast('已开始检查更新', 'info');
      const unsub = bridge.subscribe('finished', (data: any) => {
        if (String(data.task_id || '') !== taskId) return;
        unsub();
        btn.disabled = false;
        toast(String(data.message || (data.success ? '模组更新完成' : '检查更新失败')), data.success ? 'success' : 'error', 6000);
        if (data.success) void reloadList(container);
      });
    } catch (e) {
      btn.disabled = false;
      toast(errorMessage(e, '检查更新失败'), 'error');
    }
  });
}

/** 选出来的和拖进来的 jar 走同一条路：先落盘换真实路径，再交给 install_mod。 */
async function importJars(
  container: HTMLElement,
  instSel: HTMLSelectElement,
  tgtSel: HTMLSelectElement,
  files: PickedFile[],
) {
  let done = 0;
  for (const file of files) {
    try {
      const path = await stashUpload(file);
      await bridge.call('install_mod', {
        name: file.name, instance: instSel.value,
        extra: { path, instance: instSel.value, version: tgtSel.value, source: '本地' },
      });
      done++;
    } catch (e) { toast(errorMessage(e, `导入 ${file.name} 失败`), 'error'); }
  }
  if (!done) return;
  toast(done > 1 ? `已加入 ${done} 个导入任务` : '已加入导入任务', 'success');
  await flyToTasks(container.querySelector('#mods-import'), files[0].name);
}

function paintList(container: HTMLElement, rows: ModEntry[]) {
  const host = container.querySelector('#mods-list');
  if (!host) return;
  if (!rows.length) {
    host.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🧩</div><div>还没有安装模组，可导入 jar 或到下载页搜索。</div></div>';
    return;
  }
  host.innerHTML = rows.map((r, i) => `
    <div class="catalog-row">
      <div class="thumb">${escapeHtml(String(r.filename || '?').slice(0, 1).toUpperCase())}</div>
      <div style="flex:1;min-width:0">
        <div class="grid-item-title">${escapeHtml(r.filename || '?')}</div>
        <div class="grid-item-meta"><span>${escapeHtml(formatBytes(r.bytes))}</span>${r.enabled ? '' : '<span class="tag">已禁用</span>'}</div>
      </div>
      <label class="toggle"><input type="checkbox" data-toggle="${i}" ${r.enabled ? 'checked' : ''}><span class="toggle-slider"></span></label>
      <button class="btn btn-sm btn-danger" data-del="${i}">删除</button>
    </div>`).join('');
  const instance = (container.querySelector('#mods-instance') as HTMLSelectElement).value;
  const version = (container.querySelector('#mods-target') as HTMLSelectElement).value;
  host.querySelectorAll<HTMLInputElement>('[data-toggle]').forEach((input) => {
    input.addEventListener('change', async () => {
      const row = rows[Number(input.dataset.toggle)];
      try {
        await bridge.call(input.checked ? 'enable_mod' : 'disable_mod', { instance, filename: row.filename, version });
      } catch (e) {
        input.checked = !input.checked;
        toast(errorMessage(e, '切换失败'), 'error');
      }
    });
  });
  host.querySelectorAll<HTMLButtonElement>('[data-del]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const row = rows[Number(btn.dataset.del)];
      if (!await confirmDialog('删除模组', `将删除「${row.filename}」，不可恢复。`)) return;
      try {
        await bridge.call('delete_mod', { instance, filename: row.filename, version });
        toast('已删除', 'success');
        void reloadList(container);
      } catch (e) { toast(errorMessage(e, '删除失败'), 'error'); }
    });
  });
}

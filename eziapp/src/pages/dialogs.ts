import { bridge } from '../bridge';
import { store } from '../store';
import { confirmDialog, formDialog, inputDialog, toast } from '../ui';
import { errorMessage, escapeHtml, formatBytes } from './common';

export async function showVersionSetup(instance: string, version: string) {
  let data: any = {};
  try {
    data = await bridge.call('get_version_settings', { instance, version });
  } catch (e) {
    toast(errorMessage(e, '读取版本设置失败'), 'error');
    return;
  }
  const javas = [{ value: '自动选择', label: '自动选择' }, ...store.javaList.map((j) => ({ value: j.path, label: `${j.name} (${j.major})` }))];
  const accounts = [{ value: '', label: '跟随启动页' }, ...store.accounts.map((a) => ({ value: a.name, label: a.name }))];
  const values = await formDialog(`版本设置 · ${version}`, [
    { id: 'isolation', label: '隔离', type: 'select', value: data.isolation || 'none', options: [
      { value: 'none', label: '关闭（共用实例目录）' }, { value: 'saves', label: '隔离存档' },
      { value: 'mods', label: '隔离 Mod 与配置' }, { value: 'all', label: '隔离全部' },
    ]},
    { id: 'memory_mb', label: '内存 MB（空=启动页）', value: data.memory_mb || '', placeholder: '4096' },
    { id: 'java', label: 'Java', type: 'select', value: data.java || '自动选择', options: javas },
    { id: 'gc', label: 'GC', type: 'select', value: data.gc || '', options: [
      { value: '', label: '跟随全局' }, { value: 'auto', label: 'G1（推荐）' }, { value: 'g1', label: 'G1' },
      { value: 'g1_tuned', label: '调优 G1' }, { value: 'zgc', label: 'ZGC' }, { value: 'none', label: '不指定' },
    ]},
    { id: 'jvm_args', label: 'JVM 参数', type: 'textarea', value: data.jvm_args || '' },
    { id: 'game_args', label: '游戏参数', value: data.game_args || '' },
    { id: 'login_account', label: '绑定账号', type: 'select', value: data.login_account || '', options: accounts },
    { id: 'nide8_id', label: '统一通行证 ID', value: data.nide8_id || '' },
    { id: 'auth_server', label: '认证服 API', value: data.auth_server || '' },
    { id: 'server', label: '启动直连服务器', value: data.server || '' },
    { id: 'port', label: '端口', value: data.port || '' },
    { id: 'window_title', label: '窗口标题', value: data.window_title || '' },
    { id: 'window_mode', label: '窗口模式', type: 'select', value: data.window_mode || 'window', options: [
      { value: 'window', label: '窗口' }, { value: 'maximize', label: '全屏' },
    ]},
    { id: 'window_width', label: '窗口宽度', value: data.window_width || '' },
    { id: 'window_height', label: '窗口高度', value: data.window_height || '' },
    { id: 'offline_skin', label: '离线皮肤', type: 'select', value: data.offline_skin || 'default', options: [
      { value: 'default', label: '默认' }, { value: 'steve', label: 'Steve' }, { value: 'alex', label: 'Alex' },
    ]},
    { id: 'pre_launch', label: '启动前命令', value: data.pre_launch || '' },
    { id: 'pre_launch_wait', label: '等待启动前命令结束', type: 'checkbox', value: data.pre_launch_wait !== false },
    { id: 'post_launch', label: '退出后命令', value: data.post_launch || '' },
    { id: 'process_priority', label: '进程优先级', type: 'select', value: data.process_priority || 'normal', options: [
      { value: 'low', label: 'low' }, { value: 'normal', label: 'normal' }, { value: 'high', label: 'high' },
    ]},
  ]);
  if (!values) return;
  const payload: Record<string, unknown> = {
    isolation: values.isolation,
    memory_mb: values.memory_mb ? Number(values.memory_mb) : null,
    java: values.java,
    gc: values.gc,
    jvm_args: values.jvm_args,
    game_args: values.game_args,
    login_account: values.login_account,
    nide8_id: values.nide8_id,
    auth_server: values.auth_server,
    server: values.server,
    port: values.port,
    window_title: values.window_title,
    window_mode: values.window_mode,
    window_width: values.window_width ? Number(values.window_width) : null,
    window_height: values.window_height ? Number(values.window_height) : null,
    offline_skin: values.offline_skin,
    pre_launch: values.pre_launch,
    pre_launch_wait: values.pre_launch_wait === 'true',
    post_launch: values.post_launch,
    process_priority: values.process_priority,
  };
  try {
    await bridge.call('save_version_settings', { instance, version, data: payload });
    toast('版本设置已保存', 'success');
  } catch (e) {
    toast(errorMessage(e, '保存失败'), 'error');
  }
}

export async function showSavesDialog(instance: string, version = '') {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal" style="width:min(720px, calc(100vw - 32px));max-width:720px">
      <div class="modal-title">存档 · ${escapeHtml(instance)}</div>
      <div class="tabs" id="sv-tabs">
        ${[['saves', '存档'], ['backups', '备份'], ['screenshots', '截图'], ['crash-reports', '崩溃报告'], ['logs', '日志']].map(([k, l], i) =>
          `<button class="tab ${i ? '' : 'active'}" data-kind="${k}">${l}</button>`).join('')}
      </div>
      <div id="sv-list" class="log-box" style="max-height:42vh"></div>
      <div class="form-row" style="margin-top:12px">
        <button class="btn" id="sv-open">打开</button>
        <button class="btn btn-danger" id="sv-del">删除</button>
        <button class="btn" id="sv-backup">备份</button>
        <button class="btn" id="sv-restore">还原</button>
        <button class="btn" id="sv-export">导出 zip</button>
        <button class="btn" id="sv-dp">装数据包</button>
        <button class="btn btn-primary" id="sv-close">关闭</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  let kind = 'saves';
  let rows: any[] = [];
  const listEl = overlay.querySelector('#sv-list')!;
  const selected = () => {
    const idx = Number((listEl.querySelector('input:checked') as HTMLInputElement | null)?.value ?? -1);
    return rows[idx];
  };
  const reload = async () => {
    listEl.textContent = '加载中…';
    try {
      if (kind === 'saves') rows = await bridge.call<any[]>('list_saves', { instance, version });
      else if (kind === 'backups') rows = await bridge.call<any[]>('list_save_backups', { instance, version });
      else rows = await bridge.call<any[]>('list_media', { instance, kind, version });
      rows = Array.isArray(rows) ? rows : [];
      listEl.innerHTML = rows.length
        ? rows.map((r, i) => `<label style="display:flex;gap:8px;padding:6px 0;border-bottom:1px solid var(--border-light)"><input type="radio" name="sv" value="${i}"><span>${escapeHtml(r.name || r.filename || '?')} · ${escapeHtml(formatBytes(r.bytes))}</span></label>`).join('')
        : '<div class="empty-state" style="padding:24px"><div>没有内容</div></div>';
    } catch (e) {
      listEl.textContent = errorMessage(e, '读取失败');
    }
  };
  overlay.querySelectorAll<HTMLButtonElement>('[data-kind]').forEach((btn) => {
    btn.addEventListener('click', () => {
      kind = btn.dataset.kind || 'saves';
      overlay.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t === btn));
      void reload();
    });
  });
  overlay.querySelector('#sv-open')?.addEventListener('click', async () => {
    const row = selected();
    if (!row) return;
    try {
      if (kind === 'saves') await bridge.call('open_save', { instance, name: row.name, version });
      else if (row.path) await bridge.call('open_crash_file', { path: row.path });
    } catch (e) { toast(errorMessage(e, '打开失败'), 'error'); }
  });
  overlay.querySelector('#sv-del')?.addEventListener('click', async () => {
    const row = selected();
    if (!row) return;
    if (!await confirmDialog('删除', `删除 ${row.name || '?'}？`)) return;
    try {
      if (kind === 'backups') await bridge.call('delete_save_backup', { instance, backup_name: row.name, version });
      else await bridge.call('delete_save', { instance, name: row.name, version });
      toast('已删除', 'success');
      void reload();
    } catch (e) { toast(errorMessage(e, '删除失败'), 'error'); }
  });
  overlay.querySelector('#sv-backup')?.addEventListener('click', async () => {
    const row = selected();
    if (!row || kind !== 'saves') return toast('请先选择存档', 'warning');
    try {
      await bridge.call('backup_save', { instance, name: row.name, version });
      toast('已备份', 'success');
    } catch (e) { toast(errorMessage(e, '备份失败'), 'error'); }
  });
  overlay.querySelector('#sv-restore')?.addEventListener('click', async () => {
    const row = selected();
    if (!row || kind !== 'backups') return toast('请先选择备份', 'warning');
    try {
      await bridge.call('restore_save_backup', { instance, backup_name: row.name, version });
      toast('已还原', 'success');
    } catch (e) { toast(errorMessage(e, '还原失败'), 'error'); }
  });
  overlay.querySelector('#sv-export')?.addEventListener('click', async () => {
    const row = selected();
    if (!row || kind !== 'saves') return toast('请先选择存档', 'warning');
    const dest = await inputDialog('导出存档', '目标 zip 路径', `${row.name}.zip`);
    if (!dest) return;
    try {
      await bridge.call('export_save', { instance, name: row.name, dest, version });
      toast('已导出', 'success');
    } catch (e) { toast(errorMessage(e, '导出失败'), 'error'); }
  });
  overlay.querySelector('#sv-dp')?.addEventListener('click', async () => {
    const row = selected();
    if (!row || kind !== 'saves') return toast('请先选择存档', 'warning');
    const filename = await inputDialog('装进存档', '数据包文件名', '');
    if (!filename) return;
    try {
      await bridge.call('install_datapack_into_save', { instance, filename, save_name: row.name, version });
      toast('已装入数据包', 'success');
    } catch (e) { toast(errorMessage(e, '安装失败'), 'error'); }
  });
  const close = () => overlay.remove();
  overlay.querySelector('#sv-close')?.addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  void reload();
}

export async function showGlobalMods() {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal" style="width:min(560px, calc(100vw - 32px))">
      <div class="modal-title">全局 Mod</div>
      <div style="font-size:12px;color:var(--text-secondary);margin-bottom:10px">启用的 jar 会在每次启动前链到当前版本的 mods。</div>
      <div id="gm-list"></div>
      <div class="modal-actions">
        <button class="btn" id="gm-open">打开文件夹</button>
        <button class="btn btn-primary" id="gm-close">关闭</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  const list = overlay.querySelector('#gm-list')!;
  const reload = async () => {
    try {
      const rows = await bridge.call<any[]>('list_global_mods');
      if (!rows?.length) {
        list.innerHTML = '<div class="empty-state" style="padding:20px"><div>还没有全局模组</div></div>';
        return;
      }
      list.innerHTML = rows.map((r, i) => `
        <div class="setting-row">
          <span>${escapeHtml(r.filename || '?')}</span>
          <label class="toggle"><input type="checkbox" data-gm="${i}" ${r.enabled ? 'checked' : ''}><span class="toggle-slider"></span></label>
        </div>`).join('');
      list.querySelectorAll<HTMLInputElement>('[data-gm]').forEach((input) => {
        input.addEventListener('change', async () => {
          const row = rows[Number(input.dataset.gm)];
          try {
            await bridge.call('set_global_mod_enabled', { filename: row.filename, enabled: input.checked });
          } catch (e) {
            input.checked = !input.checked;
            toast(errorMessage(e, '切换失败'), 'error');
          }
        });
      });
    } catch (e) {
      list.textContent = errorMessage(e, '读取失败');
    }
  };
  overlay.querySelector('#gm-open')?.addEventListener('click', () => void bridge.call('open_global_mods').catch((e) => toast(errorMessage(e, '打开失败'), 'error')));
  overlay.querySelector('#gm-close')?.addEventListener('click', () => overlay.remove());
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  void reload();
}

export async function pickCatalogFile(item: Record<string, unknown>, kind: string, gameVersion: string): Promise<Record<string, unknown> | null> {
  try {
    const files = await bridge.call<any[]>('list_catalog_files', {
      extra: { ...item, kind, game_version: gameVersion },
    });
    if (!files?.length) return item;
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    const rows = files.slice(0, 80).map((f, i) => `
      <label class="catalog-row" style="cursor:pointer">
        <input type="radio" name="cf" value="${i}" ${i ? '' : 'checked'}>
        <div style="flex:1;min-width:0">
          <div class="grid-item-title">${escapeHtml(f.name || f.filename || f.version || '构建')}</div>
          <div class="grid-item-meta">
            <span>${escapeHtml(f.game_version || f.mc || '')}</span>
            <span>${escapeHtml((f.loaders || []).join('/') || f.loader || '')}</span>
            <span>${escapeHtml(f.date || f.updated || '')}</span>
          </div>
        </div>
      </label>`).join('');
    overlay.innerHTML = `
      <div class="modal" style="width:min(640px, calc(100vw - 32px));max-width:640px">
        <div class="modal-title">选择版本 · ${escapeHtml(String(item.name || ''))}</div>
        <div style="max-height:50vh;overflow:auto">${rows}</div>
        <div class="modal-actions"><button class="btn" id="cf-cancel">取消</button><button class="btn btn-primary" id="cf-ok">安装</button></div>
      </div>`;
    document.body.appendChild(overlay);
    return await new Promise((resolve) => {
      const finish = (v: Record<string, unknown> | null) => { overlay.remove(); resolve(v); };
      overlay.querySelector('#cf-cancel')?.addEventListener('click', () => finish(null));
      overlay.addEventListener('click', (e) => { if (e.target === overlay) finish(null); });
      overlay.querySelector('#cf-ok')?.addEventListener('click', () => {
        const idx = Number((overlay.querySelector('input[name="cf"]:checked') as HTMLInputElement | null)?.value || 0);
        finish({ ...item, ...files[idx] });
      });
    });
  } catch {
    return item;
  }
}

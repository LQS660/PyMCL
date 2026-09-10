import { bridge } from '../bridge';
import { store } from '../store';
import { confirmDialog, dismissOverlay, formDialog, inputDialog, toast } from '../ui';
import { errorMessage, escapeHtml, formatBytes } from './common';

export type PreflightItem = { level?: string; code?: string; title?: string; detail?: string };
export type CrashAction = { id?: string; label?: string; mods?: string[]; major?: number; version?: string; instance?: string; memory_mb?: number };

/** 启动预检：有 error 阻止；仅 warn 可继续。 */
export function preflightDialog(
  items: PreflightItem[],
): Promise<'block' | 'continue' | 'cancel'> {
  const errors = items.filter(i => i.level === 'error');
  const warns = items.filter(i => i.level === 'warn');
  if (!errors.length && !warns.length) return Promise.resolve('continue');

  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    const blocked = errors.length > 0;
    const rows = (blocked ? errors : warns)
      .map(i => `<div style="margin-bottom:10px"><strong>${escapeHtml(i.title || i.code || '')}</strong><div style="font-size:12px;color:var(--text-secondary);white-space:pre-wrap;margin-top:4px">${escapeHtml(i.detail || '')}</div></div>`)
      .join('');
    overlay.innerHTML = `
      <div class="modal" style="max-width:560px">
        <div class="modal-title" id="pf-title"></div>
        <div id="pf-body" style="max-height:360px;overflow:auto;margin-bottom:12px"></div>
        <div class="modal-actions" id="pf-actions"></div>
      </div>
    `;
    (overlay.querySelector('#pf-title') as HTMLElement).textContent = blocked ? '启动预检未通过' : '启动预检有警告';
    (overlay.querySelector('#pf-body') as HTMLElement).innerHTML = rows;
    const actions = overlay.querySelector('#pf-actions') as HTMLElement;
    if (blocked) {
      actions.innerHTML = `<button class="btn btn-primary" id="pf-ok">知道了</button>`;
      actions.querySelector('#pf-ok')!.addEventListener('click', () => { dismissOverlay(overlay); resolve('block'); });
    } else {
      actions.innerHTML = `
        <button class="btn" id="pf-cancel">取消</button>
        <button class="btn btn-primary" id="pf-go">继续启动</button>
      `;
      actions.querySelector('#pf-cancel')!.addEventListener('click', () => { dismissOverlay(overlay); resolve('cancel'); });
      actions.querySelector('#pf-go')!.addEventListener('click', () => { dismissOverlay(overlay); resolve('continue'); });
    }
    overlay.addEventListener('click', e => {
      if (e.target === overlay) { dismissOverlay(overlay); resolve(blocked ? 'block' : 'cancel'); }
    });
    document.body.appendChild(overlay);
  });
}

/** 崩溃报告 + 一键修复动作 + 查看输出/导出/上报。返回 true 表示用户点了「重新启动」。 */
export function crashDialog(report: {
  title?: string; headline?: string; detail?: string; help?: string;
  actions?: CrashAction[]; task_id?: string;
  instance?: string; version?: string;
  direct_file?: string; output_tail?: string;
}): Promise<boolean> {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    const actions = Array.isArray(report.actions) ? report.actions : [];
    const canRelaunch = !!(report.instance && report.version);
    const hasFile = !!(report.direct_file || report.output_tail || report.task_id);
    const actBtns = actions.map((a, i) =>
      `<button class="btn" data-act="${i}">${escapeHtml(a.label || a.id || '修复')}</button>`
    ).join('');
    overlay.innerHTML = `
      <div class="modal" style="max-width:640px">
        <div class="modal-title" id="cr-title"></div>
        <div id="cr-head" style="font-size:13px;margin-bottom:8px;font-weight:600"></div>
        <pre id="cr-detail" class="log-box" style="max-height:280px;margin:0 0 10px"></pre>
        <div id="cr-help" style="font-size:12px;color:var(--text-secondary);margin-bottom:10px"></div>
        ${actBtns ? `<div style="font-size:13px;font-weight:650;margin-bottom:6px">建议操作</div><div id="cr-acts" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px">${actBtns}</div>` : ''}
        <div class="modal-actions" style="flex-wrap:wrap">
          ${canRelaunch ? '<button class="btn" id="cr-relaunch">重新启动</button>' : ''}
          ${hasFile ? '<button class="btn" id="cr-view">查看输出</button>' : ''}
          <button class="btn" id="cr-export">导出错误报告</button>
          <button class="btn" id="cr-send">发送给开发者</button>
          <button class="btn btn-primary" id="cr-ok">确定</button>
        </div>
      </div>
    `;
    (overlay.querySelector('#cr-title') as HTMLElement).textContent = report.title || 'Minecraft 出现错误';
    const head = overlay.querySelector('#cr-head') as HTMLElement;
    if (report.headline && report.headline !== report.title) head.textContent = report.headline;
    else head.style.display = 'none';
    (overlay.querySelector('#cr-detail') as HTMLElement).textContent = report.detail || report.output_tail || '';
    (overlay.querySelector('#cr-help') as HTMLElement).textContent = report.help || '';
    overlay.querySelectorAll('[data-act]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const idx = Number((btn as HTMLElement).dataset.act);
        const action = actions[idx];
        if (!action) return;
        (btn as HTMLButtonElement).disabled = true;
        try {
          const result = await bridge.call<{ ok?: boolean; message?: string }>('apply_crash_action', {
            action, report,
          });
          if (result?.ok) {
            toast(result.message || '已处理', 'success');
            if (action.id === 'disable_mods') (btn as HTMLButtonElement).textContent = '已禁用';
          } else {
            toast(result?.message || '操作失败', 'error');
            (btn as HTMLButtonElement).disabled = false;
          }
        } catch (e: any) {
          toast(e?.message || '操作失败', 'error');
          (btn as HTMLButtonElement).disabled = false;
        }
      });
    });
    const close = (relaunch: boolean) => { dismissOverlay(overlay); resolve(relaunch); };
    overlay.querySelector('#cr-ok')!.addEventListener('click', () => close(false));
    overlay.querySelector('#cr-relaunch')?.addEventListener('click', () => close(true));
    overlay.querySelector('#cr-view')?.addEventListener('click', async () => {
      try {
        await bridge.call('open_crash_file', { path: report.direct_file || '', task_id: report.task_id || '' });
      } catch (e: any) { toast(e?.message || '没有可打开的日志文件', 'error'); }
    });
    overlay.querySelector('#cr-export')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget as HTMLButtonElement;
      btn.disabled = true;
      try {
        const path = await bridge.call<string>('export_crash_report', { task_id: report.task_id || '' });
        toast(path ? `已导出：${path}` : '已导出错误报告', 'success', 6000);
        if (path) await bridge.call('open_crash_file', { path }).catch(() => undefined);
      } catch (err: any) {
        toast(err?.message || '导出失败', 'error');
        btn.disabled = false;
      }
    });
    overlay.querySelector('#cr-send')?.addEventListener('click', async (e) => {
      const btn = e.currentTarget as HTMLButtonElement;
      if (!store.mergedSettings().feedback_consent) {
        const ok = await confirmDialog('上传诊断数据', '发送崩溃报告会附带本机配置信息。是否允许上传？');
        if (!ok) { toast('未同意上传，已取消发送', 'warning'); return; }
        try { await bridge.call('save_settings', { feedback_consent: true }); } catch { /* 忽略 */ }
        store.setSettings({ ...(store.settings || {}), feedback_consent: true } as any);
      }
      btn.disabled = true;
      btn.textContent = '发送中…';
      try {
        // 直接上报对话框里的报告内容：启动失败这类合成报告后端 _crashes 里没有，
        // submit_crash_report(task_id) 会找不到，submit_crash_feedback 带全文更稳。
        const result = await bridge.call<{ message?: string }>('submit_crash_feedback', { report });
        btn.textContent = '已发送';
        toast(result?.message || '已发给开发者', 'success');
      } catch (err: any) {
        toast(err?.message || '发送失败', 'error');
        btn.disabled = false;
        btn.textContent = '发送给开发者';
      }
    });
    overlay.addEventListener('click', e => { if (e.target === overlay) close(false); });
    document.body.appendChild(overlay);
  });
}

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
  const syncButtons = () => {
    // 对齐 Qt 版 _set_actions：不同页签启用不同操作
    const isSave = kind === 'saves';
    const isBackup = kind === 'backups';
    const set = (id: string, on: boolean) => {
      const b = overlay.querySelector<HTMLButtonElement>(id);
      if (b) b.disabled = !on;
    };
    set('#sv-del', isSave || isBackup);
    set('#sv-backup', isSave);
    set('#sv-export', isSave);
    set('#sv-dp', isSave);
    set('#sv-restore', isBackup);
  };
  overlay.querySelectorAll<HTMLButtonElement>('[data-kind]').forEach((btn) => {
    btn.addEventListener('click', () => {
      kind = btn.dataset.kind || 'saves';
      overlay.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t === btn));
      syncButtons();
      void reload();
    });
  });
  syncButtons();
  overlay.querySelector('#sv-open')?.addEventListener('click', async () => {
    const row = selected();
    if (!row) return;
    try {
      if (kind === 'saves') await bridge.call('open_save', { instance, name: row.name, version });
      else if (row.path) await bridge.call('open_media', { path: row.path });
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
    try {
      const packs = await bridge.call<string[]>('get_installed_datapacks', { instance });
      if (!packs?.length) return toast('实例 datapacks 目录还没有数据包，先到下载页安装', 'warning');
      const picked = await formDialog('选择数据包', [{
        id: 'filename', label: `装进存档「${row.name}」`, type: 'select', value: packs[0],
        options: packs.map((p) => ({ value: p, label: p })),
      }]);
      if (!picked?.filename) return;
      await bridge.call('install_datapack_into_save', { instance, filename: picked.filename, save_name: row.name, version });
      toast('已装入数据包', 'success');
    } catch (e) { toast(errorMessage(e, '安装失败'), 'error'); }
  });
  const close = () => dismissOverlay(overlay);
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
  overlay.querySelector('#gm-close')?.addEventListener('click', () => dismissOverlay(overlay));
  overlay.addEventListener('click', (e) => { if (e.target === overlay) dismissOverlay(overlay); });
  void reload();
}

/** 微软设备码登录对话框：login_code/login_status 事件驱动，可取消。 */
export function showMicrosoftLogin(onDone?: (ok: boolean) => void) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal" style="max-width:440px">
      <div class="modal-title">微软账号登录</div>
      <div id="ms-status" style="font-size:13px;color:var(--text-secondary)">正在请求微软设备代码…</div>
      <div id="ms-code" style="font-family:var(--font-mono);font-size:24px;font-weight:700;letter-spacing:3px;margin:12px 0;text-align:center"></div>
      <div class="modal-actions" style="justify-content:space-between">
        <button class="btn" id="ms-cancel">取消</button>
        <button class="btn btn-primary" id="ms-open" style="display:none">打开验证页</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  let taskId = '';
  let uri = '';
  let settled = false;
  const statusEl = overlay.querySelector<HTMLElement>('#ms-status')!;
  const codeEl = overlay.querySelector<HTMLElement>('#ms-code')!;
  const openBtn = overlay.querySelector<HTMLButtonElement>('#ms-open')!;
  const finish = (ok: boolean, message = '') => {
    if (settled) return;
    settled = true;
    unsubCode(); unsubStatus(); unsubFinished();
    dismissOverlay(overlay);
    if (message) toast(message, ok ? 'success' : 'error');
    onDone?.(ok);
  };
  const unsubCode = bridge.subscribe('login_code', (data: any) => {
    if (!taskId) return;
    codeEl.textContent = String(data.code || '');
    uri = String(data.uri || '');
    if (uri) openBtn.style.display = '';
    statusEl.textContent = '请在浏览器中输入设备代码完成登录。';
  });
  const unsubStatus = bridge.subscribe('login_status', (data: any) => {
    if (!taskId) return;
    statusEl.textContent = String(data.text || '') || statusEl.textContent;
  });
  const unsubFinished = bridge.subscribe('finished', (data: any) => {
    if (!taskId || String(data.task_id || '') !== taskId) return;
    finish(!!data.success, String(data.message || (data.success ? '登录完成' : '登录失败')));
  });
  overlay.querySelector('#ms-cancel')?.addEventListener('click', () => {
    if (taskId) void bridge.call('cancel_task', { task_id: taskId }).catch(() => undefined);
    finish(false);
  });
  overlay.addEventListener('click', (e) => {
    if (e.target !== overlay) return;
    if (taskId) void bridge.call('cancel_task', { task_id: taskId }).catch(() => undefined);
    finish(false);
  });
  openBtn.addEventListener('click', () => { if (uri) window.open(uri, '_blank', 'noopener'); });
  void bridge.call<string>('start_microsoft_login').then((id) => { taskId = id; })
    .catch((e) => finish(false, errorMessage(e, '无法开始微软登录')));
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
      const finish = (v: Record<string, unknown> | null) => { dismissOverlay(overlay); resolve(v); };
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

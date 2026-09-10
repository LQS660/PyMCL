// 实例管理页
import { bridge } from '../bridge';
import { store } from '../store';
import { toast, showSkeleton, showError, confirmDialog, inputDialog, showContextMenu } from '../ui';
import { errorMessage, escapeHtml } from './common';

export async function renderInstancesPage(container: HTMLElement) {
  showSkeleton(container, 'cards', 4);
  try {
    const instances = await bridge.call<any[]>('get_instances');
    store.setInstances(instances);
    render(container);
  } catch (e: any) {
    showError(container, '加载实例失败: ' + (e.message || '未知错误'), () => renderInstancesPage(container));
  }
}

function render(container: HTMLElement) {
  const instances = store.instances;
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px">
      <div style="display:flex;gap:8px;align-items:center">
        <button class="btn btn-primary" id="btn-create-instance">➕ 新建实例</button>
      </div>
      <div class="grid-list" id="instance-list">
        ${instances.length === 0
          ? '<div class="empty-state"><div class="empty-state-icon">📦</div><div>暂无实例，请创建一个</div></div>'
          : instances.map(inst => `
            <div class="grid-item" data-instance="${escapeHtml(inst.name)}">
              <div class="grid-item-title">${escapeHtml(inst.name)}</div>
              <div class="grid-item-meta">
                <span>MC: ${escapeHtml(inst.mc || '?')}</span>
                <span>版本: ${escapeHtml(inst.versions || 0)}</span>
                ${inst.pack ? `<span>整合包: ${escapeHtml(inst.pack)}</span>` : ''}
                <span>Java: ${escapeHtml(inst.javaLabel || '自动')}</span>
              </div>
              <div class="grid-item-actions">
                <button class="btn btn-sm btn-primary" data-action="launch">启动</button>
                <button class="btn btn-sm" data-action="rename">重命名</button>
                <button class="btn btn-sm" data-action="open">目录</button>
                <button class="btn btn-sm" data-action="saves">存档</button>
                <button class="btn btn-sm" data-action="java">Java</button>
                <button class="btn btn-sm" data-action="export">导出</button>
                <button class="btn btn-sm" data-action="versions">版本</button>
                <button class="btn btn-sm btn-danger" data-action="delete">删除</button>
              </div>
            </div>
          `).join('')}
      </div>
    </div>
  `;

  document.getElementById('btn-create-instance')?.addEventListener('click', async () => {
    const name = await inputDialog('新建实例', '实例名称', '');
    if (!name) return;
    try {
      await bridge.call('create_instance', { name });
      toast('实例创建成功', 'success');
      renderInstancesPage(container);
    } catch (e: any) {
      toast(e.message || '创建失败', 'error');
    }
  });

  document.querySelectorAll('#instance-list .grid-item').forEach(el => {
    const instanceName = (el as HTMLElement).dataset.instance!;
    el.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const action = (btn as HTMLElement).dataset.action!;
        switch (action) {
          case 'launch': {
            store.currentInstance = instanceName;
            const { router } = await import('../router');
            router.navigate('launch');
            break;
          }
          case 'rename': {
            const newName = await inputDialog('重命名实例', '新名称', instanceName);
            if (!newName || newName === instanceName) return;
            try {
              await bridge.call('rename_instance', { name: instanceName, new_name: newName });
              toast('重命名成功', 'success');
              renderInstancesPage(container);
            } catch (err: any) {
              toast(err.message || '重命名失败', 'error');
            }
            break;
          }
          case 'open': {
            try {
              await bridge.call('open_instance_folder', { name: instanceName });
              toast('已打开实例目录', 'info');
            } catch (err: any) {
              toast(err.message || '打开失败', 'error');
            }
            break;
          }
          case 'saves': {
            const { showSavesDialog } = await import('./dialogs');
            await showSavesDialog(instanceName);
            break;
          }
          case 'java': {
            try {
              const opts = await bridge.call<Array<{ label?: string; value?: string }>>('java_combo_options', { instance: instanceName, scan_system: true });
              const picked = await inputDialog('选择 Java', (opts || []).map((o) => o.label).join(' / '), opts?.[0]?.label || '自动选择');
              if (!picked) break;
              const value = opts?.find((o) => o.label === picked)?.value || picked;
              await bridge.call('set_instance_java', { name: instanceName, java: value });
              toast('已更新实例 Java', 'success');
              renderInstancesPage(container);
            } catch (err: any) {
              toast(err.message || '设置失败', 'error');
            }
            break;
          }
          case 'export': {
            try {
              await bridge.call('export_modpack', { instance: instanceName });
              toast('已开始导出整合包', 'success');
            } catch (err: any) {
              toast(err.message || '导出失败', 'error');
            }
            break;
          }
          case 'versions': {
            showInstanceVersions(container, instanceName);
            break;
          }
          case 'delete': {
            const confirmed = await confirmDialog('删除实例', `确定要删除实例 "${instanceName}" 吗？此操作不可恢复。`);
            if (!confirmed) return;
            try {
              await bridge.call('delete_instance', { name: instanceName });
              toast('实例已删除', 'success');
              renderInstancesPage(container);
            } catch (err: any) {
              toast(err.message || '删除失败', 'error');
            }
            break;
          }
        }
      });
    });
  });
}

async function showInstanceVersions(container: HTMLElement, instanceName: string, includeHidden = false) {
  try {
    const versions = await bridge.call<string[]>('get_installed_versions', { instance: instanceName, include_hidden: includeHidden });
    const modal = document.createElement('div');
    modal.className = 'modal-overlay';
    modal.innerHTML = `
      <div class="modal" style="width:min(640px, calc(100vw - 32px));max-width:640px">
        <div class="modal-title">📋 实例版本 - ${escapeHtml(instanceName)}</div>
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
          <button class="btn btn-sm btn-primary" id="btn-add-version">➕ 安装版本</button>
          <label class="check-row" style="margin-left:auto"><input type="checkbox" id="vs-show-hidden" ${includeHidden ? 'checked' : ''}> 显示隐藏</label>
        </div>
        <div id="version-list">
          ${versions.length === 0
            ? '<div style="color:var(--text-secondary);padding:16px;text-align:center">暂无已安装版本</div>'
            : versions.map(v => `
              <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 0;border-bottom:1px solid var(--border-light)">
                <span style="min-width:0;overflow:hidden;text-overflow:ellipsis"><strong>${escapeHtml(v)}</strong></span>
                <div style="display:flex;gap:4px;flex:0 0 auto">
                  <button class="btn btn-sm" data-action="setup-version" data-version="${escapeHtml(v)}">设置</button>
                  <button class="btn btn-sm" data-action="saves-version" data-version="${escapeHtml(v)}">存档</button>
                  <button class="btn btn-sm" data-action="more-version" data-version="${escapeHtml(v)}">更多 ▾</button>
                </div>
              </div>
            `).join('')}
        </div>
        <div class="modal-actions"><button class="btn" id="close-versions">关闭</button></div>
      </div>
    `;
    document.body.appendChild(modal);

    const reload = () => { modal.remove(); void showInstanceVersions(container, instanceName, includeHidden); };
    modal.querySelector('#close-versions')?.addEventListener('click', () => modal.remove());
    modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });
    modal.querySelector<HTMLInputElement>('#vs-show-hidden')?.addEventListener('change', (e) => {
      modal.remove();
      void showInstanceVersions(container, instanceName, (e.target as HTMLInputElement).checked);
    });

    modal.querySelectorAll('[data-action="setup-version"]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const version = (btn as HTMLElement).dataset.version!;
        const { showVersionSetup } = await import('./dialogs');
        await showVersionSetup(instanceName, version);
      });
    });

    modal.querySelectorAll('[data-action="saves-version"]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const version = (btn as HTMLElement).dataset.version!;
        const { showSavesDialog } = await import('./dialogs');
        await showSavesDialog(instanceName, version);
      });
    });

    modal.querySelectorAll<HTMLButtonElement>('[data-action="more-version"]').forEach(btn => {
      btn.addEventListener('click', () => {
        const version = btn.dataset.version!;
        const run = (fn: () => Promise<unknown>, ok: string, reloadAfter = false) => void (async () => {
          try {
            const out = await fn();
            toast(typeof out === 'string' && out ? out : ok, 'success');
            if (reloadAfter) reload();
          } catch (e) { toast(errorMessage(e, '操作失败'), 'error'); }
        })();
        showContextMenu(btn, [
          { label: '修复（补全缺失文件）', onClick: () => run(async () => { await bridge.call('repair_version', { instance: instanceName, version }); return '已开始修复，进度见下载任务页'; }, '') },
          { label: '重命名', onClick: () => void (async () => {
              const newId = await inputDialog('重命名版本', '新版本 ID', version);
              if (!newId || newId === version) return;
              run(() => bridge.call('rename_version', { instance: instanceName, version, new_id: newId }), '已重命名', true);
            })() },
          { label: '复制', onClick: () => void (async () => {
              const newId = await inputDialog('复制版本', '新版本 ID', `${version}-copy`);
              if (!newId) return;
              run(() => bridge.call('copy_version', { instance: instanceName, version, new_id: newId }), '已复制', true);
            })() },
          { label: '隐藏 / 取消隐藏', onClick: () => void (async () => {
              try {
                const data = await bridge.call<any>('get_version_settings', { instance: instanceName, version });
                run(() => bridge.call('hide_version', { instance: instanceName, version, hidden: !data?.hidden }), '已切换隐藏状态', true);
              } catch (e) { toast(errorMessage(e, '操作失败'), 'error'); }
            })() },
          { label: '打开游戏文件夹', onClick: () => run(() => bridge.call('open_version_folder', { instance: instanceName, version, which: 'game' }), '已打开') },
          { label: '打开 mods 目录', onClick: () => run(() => bridge.call('open_version_folder', { instance: instanceName, version, which: 'mods' }), '已打开') },
          { label: '打开 saves 目录', onClick: () => run(() => bridge.call('open_version_folder', { instance: instanceName, version, which: 'saves' }), '已打开') },
          { label: '打开截图目录', onClick: () => run(() => bridge.call('open_version_folder', { instance: instanceName, version, which: 'screenshots' }), '已打开') },
          { label: '创建桌面快捷方式', onClick: () => run(() => bridge.call('create_desktop_shortcut', { instance: instanceName, version }), '已创建桌面快捷方式') },
          { label: '导出启动脚本', onClick: () => run(async () => { await bridge.call('export_launch_script', { instance: instanceName, version }); return '已加入导出任务，完成后到下载任务页查看'; }, '') },
          { label: '卸载版本', danger: true, onClick: () => void (async () => {
              if (!await confirmDialog('卸载版本', `确定要卸载版本 ${version} 吗？`)) return;
              run(() => bridge.call('uninstall_version', { spec: `${instanceName} / ${version}` }), '版本已卸载', true);
            })() },
        ]);
      });
    });

    modal.querySelector('#btn-add-version')?.addEventListener('click', () => {
      modal.remove();
      store.currentInstance = instanceName;
      import('../router').then(({ router: r }) => r.navigate('downloads'));
    });
  } catch (e: any) {
    toast(e.message || '加载版本失败', 'error');
  }
}
// Java 管理页
import { bridge } from '../bridge';
import { store } from '../store';
import { toast, showError, showSkeleton, flyToTasks } from '../ui';
import { escapeHtml } from './common';

// 与 Qt 版 java_page.NOTES 对齐
const JAVA_NOTES: Record<string, string> = {
  '8': '1.16 及以下旧版本',
  '11': '部分旧模组环境',
  '17': '1.18 – 1.20.4 推荐',
  '21': '1.20.5+ 新版本',
};

export async function renderJavaPage(container: HTMLElement) {
  showSkeleton(container, 'cards', 4);
  try {
    const [javas, settings, vendors] = await Promise.all([
      bridge.call<any[]>('get_java_list', { scan_system: true }),
      bridge.call<any>('get_settings'),
      bridge.call<string[]>('java_vendor_list').catch(() => ['adoptium']),
    ]);
    store.setJavaList(javas);
    store.setSettings(settings);
    const labels = await Promise.all((vendors?.length ? vendors : ['adoptium']).map(async (v) => ({
      value: v,
      label: await bridge.call<string>('java_vendor_label', { vendor: v }).catch(() => v),
    })));
    render(container, labels);
  } catch (e: any) {
    showError(container, '加载 Java 列表失败: ' + (e.message || '未知错误'), () => renderJavaPage(container));
  }
}

function render(container: HTMLElement, vendors: { value: string; label: string }[]) {
  const javas = store.javaList;
  const currentDefault = ((store.settings || {}) as any).default_java || '';
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px;max-width:1050px">
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">
          <div>
            <div class="card-header" style="margin:0">本机环境</div>
            <div style="font-size:12px;color:var(--text-secondary);margin-top:4px">启动时会按游戏版本自动匹配 Java；也可在实例页为每个实例单独指定。</div>
          </div>
          <button class="btn" id="btn-scan-java">↻ 重新检测</button>
        </div>
      </div>
      <div class="grid-list" id="java-list">
        ${javas.length === 0
          ? '<div class="empty-state"><div class="empty-state-icon">☕</div><div>未检测到 Java，请从下方下载</div></div>'
          : javas.map(j => {
            const isDefault = !!j.path && j.path === currentDefault;
            return `
            <div class="grid-item" data-java="${escapeHtml(j.path)}">
              <div style="display:flex;gap:12px;align-items:center">
                <div class="task-icon" style="background:#E8862E">J</div>
                <div style="min-width:0;flex:1">
                  <div class="grid-item-title">${escapeHtml(j.name)}${isDefault ? ' <span class="tag tag-primary">默认</span>' : ''}</div>
                  <div class="grid-item-meta"><span>Java ${escapeHtml(j.major)}</span></div>
                  <div style="font-size:11px;color:var(--text-disabled);word-break:break-all;font-family:var(--font-mono);margin-top:4px">${escapeHtml(j.path)}</div>
                </div>
              </div>
              <div class="grid-item-actions">
                <button class="btn btn-sm ${isDefault ? '' : 'btn-primary'}" data-action="set-default" data-java="${escapeHtml(j.path)}" ${isDefault ? 'disabled' : ''}>${isDefault ? '当前默认' : '设为默认'}</button>
              </div>
            </div>
          `;
          }).join('')}
      </div>
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:12px">
          <div class="card-header" style="margin:0">下载新运行时</div>
          <div style="display:flex;align-items:center;gap:8px">
            <span style="font-size:12px;color:var(--text-secondary)">发行版</span>
            <select class="select" id="java-vendor">${vendors.map((v) => `<option value="${escapeHtml(v.value)}" ${v.value === 'adoptium' ? 'selected' : ''}>${escapeHtml(v.label)}</option>`).join('')}</select>
          </div>
        </div>
        <div class="grid-list" style="grid-template-columns:repeat(auto-fill,minmax(170px,1fr));margin-bottom:0">
          ${['8', '11', '17', '21'].map((major) => `
            <div class="grid-item" style="display:flex;flex-direction:column">
              <div class="grid-item-title" style="font-size:16px">Java ${major}</div>
              <div style="font-size:12px;color:var(--text-secondary);flex:1">${escapeHtml(JAVA_NOTES[major] || '')}</div>
              <div class="grid-item-actions"><button class="btn btn-sm btn-primary" id="btn-download-java-${major}">下载</button></div>
            </div>`).join('')}
        </div>
      </div>
    </div>
  `;

  container.querySelector('#btn-scan-java')?.addEventListener('click', async () => {
    try {
      const javas = await bridge.call<any[]>('get_java_list', { scan_system: true });
      store.setJavaList(javas);
      render(container, vendors);
      toast('扫描完成', 'success');
    } catch (e: any) {
      toast(e.message || '扫描失败', 'error');
    }
  });

  ['8', '11', '17', '21'].forEach(major => {
    container.querySelector(`#btn-download-java-${major}`)?.addEventListener('click', async (e) => {
      const btn = e.currentTarget as HTMLElement;
      try {
        const vendor = (container.querySelector('#java-vendor') as HTMLSelectElement | null)?.value || 'adoptium';
        await bridge.call<string>('download_java', { major, vendor });
        toast(`开始下载 Java ${major}`, 'info');
        await flyToTasks(btn, 'J', '#E8862E');
        const { router } = await import('../router');
        router.navigate('tasks');
      } catch (err: any) {
        toast(err.message || `下载 Java ${major} 失败`, 'error');
      }
    });
  });

  container.querySelectorAll('#java-list .grid-item').forEach(el => {
    const javaPath = (el as HTMLElement).dataset.java!;
    el.querySelector('[data-action="set-default"]')?.addEventListener('click', async () => {
      try {
        // 只提交这一个键。以前是 `{...store.settings, default_java}`，
        // store 里可能是别处存进去的残缺 settings，整份回传会把没带上的键一起写坏。
        await bridge.call('save_settings', { default_java: javaPath });
        store.setSettings({ ...(store.settings || {}), default_java: javaPath } as any);
        render(container, vendors);
        toast('已设为默认 Java', 'success');
      } catch (e: any) {
        toast(e.message || '设置失败', 'error');
      }
    });
  });
}

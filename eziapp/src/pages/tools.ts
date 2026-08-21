// 维护工具：清理、更新、环境信息和新闻。
import { bridge } from '../bridge';
import { router } from '../router';
import { confirmDialog, showError, showLoading, toast } from '../ui';
import { errorMessage, escapeHtml, formatBytes } from './common';

interface CleanerPreview {
  count?: number;
  bytes?: number;
  unused_libraries?: unknown[];
  parts?: unknown[];
  cache?: unknown[];
}

interface NewsItem {
  title?: string;
  body?: string;
  version?: string;
  date?: string;
}

interface UpdateInfo {
  ok?: boolean;
  current?: string;
  latest?: string;
  has_update?: boolean;
  message?: string;
  notes?: string;
}

export function renderToolsPage(container: HTMLElement) {
  showLoading(container);
  void loadAndRender(container);
}

async function loadAndRender(container: HTMLElement) {
  const [cleanerResult, newsResult] = await Promise.allSettled([
    bridge.call<CleanerPreview>('cleaner_preview'),
    bridge.call<NewsItem[]>('cached_news'),
  ]);
  if (!container.isConnected) return;
  const cleaner = cleanerResult.status === 'fulfilled' ? cleanerResult.value : undefined;
  const news = newsResult.status === 'fulfilled' && Array.isArray(newsResult.value) ? newsResult.value : [];
  if (!cleaner && newsResult.status === 'rejected') {
    showError(container, '无法读取工具数据：' + errorMessage(newsResult.reason, '未知错误'), () => void loadAndRender(container));
    return;
  }
  render(container, cleaner || {}, news);
}

function render(container: HTMLElement, cleaner: CleanerPreview, news: NewsItem[]) {
  const itemCount = Number(cleaner.count || 0);
  const totalBytes = Number(cleaner.bytes || 0);
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px;max-width:1050px">
      <div class="grid-list" style="grid-template-columns:repeat(auto-fit,minmax(280px,1fr))">
        <div class="card">
          <div class="card-header">🧹 清理缓存</div>
          <div style="font-size:13px;color:var(--text-secondary);line-height:1.6">检测到 ${itemCount} 个可清理项目，约 ${formatBytes(totalBytes)}。</div>
          <div style="display:flex;flex-direction:column;gap:6px;margin:12px 0;font-size:13px">
            <label><input type="checkbox" data-clean-kind="parts" checked> 中断下载文件 (${cleaner.parts?.length || 0})</label>
            <label><input type="checkbox" data-clean-kind="cache" checked> 更新与临时缓存 (${cleaner.cache?.length || 0})</label>
            <label><input type="checkbox" data-clean-kind="unused_libraries" checked> 未引用 libraries (${cleaner.unused_libraries?.length || 0})</label>
          </div>
          <div class="grid-item-actions"><button class="btn btn-primary" id="tools-clean">清理所选内容</button><button class="btn btn-sm" id="tools-clean-refresh">↻ 重新扫描</button></div>
        </div>
        <div class="card">
          <div class="card-header">⬆️ 启动器更新</div>
          <div id="tools-update-result" style="font-size:13px;color:var(--text-secondary);line-height:1.6">仅在你点击后检查更新。</div>
          <div class="grid-item-actions"><button class="btn btn-primary" id="tools-check-update">检查更新</button></div>
        </div>
        <div class="card">
          <div class="card-header">🖥️ 环境诊断</div>
          <div style="font-size:13px;color:var(--text-secondary);line-height:1.6">查看系统、内存与 Java 环境信息，便于排查启动和性能问题。</div>
          <div class="grid-item-actions"><button class="btn" id="tools-system-info">查看系统信息</button><button class="btn" id="tools-recommend">查看推荐配置</button></div>
        </div>
        <div class="card">
          <div class="card-header">🧩 全局模组</div>
          <div style="font-size:13px;color:var(--text-secondary);line-height:1.6">打开全局模组目录，用于管理共享模组文件。</div>
          <div class="grid-item-actions"><button class="btn" id="tools-global-mods">打开目录</button></div>
        </div>
      </div>
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px">
          <div class="card-header" style="margin:0">Minecraft 新闻</div>
          <button class="btn btn-sm" id="tools-refresh-news">↻ 更新新闻</button>
        </div>
        <div id="tools-news">${renderNews(news)}</div>
      </div>
    </div>
  `;

  container.querySelector<HTMLButtonElement>('#tools-clean-refresh')?.addEventListener('click', () => void loadAndRender(container));
  container.querySelector<HTMLButtonElement>('#tools-clean')?.addEventListener('click', async () => {
    const kinds = Array.from(container.querySelectorAll<HTMLInputElement>('[data-clean-kind]:checked')).map((input) => input.dataset.cleanKind || '');
    if (!kinds.length) {
      toast('请至少选择一种清理内容', 'warning');
      return;
    }
    const confirmed = await confirmDialog('清理缓存', `确定清理 ${itemCount} 个可选项目吗？`);
    if (!confirmed) return;
    const button = container.querySelector<HTMLButtonElement>('#tools-clean')!;
    button.disabled = true;
    button.textContent = '清理中…';
    try {
      const result = await bridge.call<{ removed?: number; bytes?: number }>('cleaner_apply', { kinds });
      toast(`已清理 ${Number(result.removed || 0)} 个项目，释放 ${formatBytes(result.bytes)}`, 'success');
      await loadAndRender(container);
    } catch (error) {
      toast(errorMessage(error, '清理失败'), 'error');
      button.disabled = false;
      button.textContent = '清理所选内容';
    }
  });
  container.querySelector<HTMLButtonElement>('#tools-check-update')?.addEventListener('click', async () => {
    const button = container.querySelector<HTMLButtonElement>('#tools-check-update')!;
    const resultEl = container.querySelector<HTMLElement>('#tools-update-result')!;
    button.disabled = true;
    resultEl.textContent = '正在检查更新…';
    try {
      const info = await bridge.call<UpdateInfo>('check_update');
      renderUpdateResult(resultEl, info);
      if (info.has_update) {
        const startButton = document.createElement('button');
        startButton.className = 'btn btn-sm btn-primary';
        startButton.textContent = '下载并更新';
        startButton.style.marginTop = '8px';
        startButton.addEventListener('click', async () => {
          startButton.disabled = true;
          try {
            await bridge.call<string>('start_self_update');
            toast('更新任务已创建', 'success');
            router.navigate('tasks');
          } catch (error) {
            toast(errorMessage(error, '无法创建更新任务'), 'error');
            startButton.disabled = false;
          }
        });
        resultEl.appendChild(startButton);
      }
    } catch (error) {
      resultEl.textContent = `检查失败：${errorMessage(error, '未知错误')}`;
    } finally {
      button.disabled = false;
    }
  });
  container.querySelector<HTMLButtonElement>('#tools-system-info')?.addEventListener('click', async () => {
    try {
      const data = await bridge.call<Record<string, unknown>>('collect_sysinfo', { scan_system_java: true });
      showJsonDialog('系统信息', data);
    } catch (error) {
      toast(errorMessage(error, '读取系统信息失败'), 'error');
    }
  });
  container.querySelector<HTMLButtonElement>('#tools-recommend')?.addEventListener('click', async () => {
    try {
      const data = await bridge.call<Record<string, unknown>>('get_smart_recommendation');
      showJsonDialog('推荐配置', data);
    } catch (error) {
      toast(errorMessage(error, '获取推荐配置失败'), 'error');
    }
  });
  container.querySelector<HTMLButtonElement>('#tools-global-mods')?.addEventListener('click', async () => {
    try {
      await bridge.call('open_global_mods');
    } catch (error) {
      toast(errorMessage(error, '无法打开全局模组目录'), 'error');
    }
  });
  container.querySelector<HTMLButtonElement>('#tools-refresh-news')?.addEventListener('click', async () => {
    const host = container.querySelector<HTMLElement>('#tools-news')!;
    host.innerHTML = '<div style="font-size:13px;color:var(--text-secondary)">正在更新新闻…</div>';
    try {
      const items = await bridge.call<NewsItem[]>('fetch_news');
      host.innerHTML = renderNews(Array.isArray(items) ? items : []);
    } catch (error) {
      host.innerHTML = `<div style="font-size:13px;color:var(--danger)">更新新闻失败：${escapeHtml(errorMessage(error, '未知错误'))}</div>`;
    }
  });
}

function renderUpdateResult(element: HTMLElement, info: UpdateInfo): void {
  element.innerHTML = `
    <div>${escapeHtml(info.message || '检查完成')}</div>
    <div style="margin-top:4px">当前 ${escapeHtml(info.current || '?')}，最新 ${escapeHtml(info.latest || info.current || '?')}</div>
    ${info.notes ? `<div style="margin-top:6px;white-space:pre-wrap">${escapeHtml(info.notes)}</div>` : ''}
  `;
}

function renderNews(items: NewsItem[]): string {
  if (!items.length) return '<div class="empty-state"><div class="empty-state-icon">📰</div><div>暂无缓存新闻，点击“更新新闻”读取最新内容。</div></div>';
  return `<div style="display:flex;flex-direction:column;gap:10px">${items.slice(0, 8).map((item) => `
    <div style="padding:10px 0;border-bottom:1px solid var(--border-light)">
      <div style="font-size:14px;font-weight:600">${escapeHtml(item.title || item.version || 'Minecraft 新闻')}</div>
      ${item.body ? `<div style="font-size:12px;color:var(--text-secondary);margin-top:4px;line-height:1.5">${escapeHtml(item.body)}</div>` : ''}
      ${item.date ? `<div style="font-size:11px;color:var(--text-disabled);margin-top:5px">${escapeHtml(item.date)}</div>` : ''}
    </div>
  `).join('')}</div>`;
}

function showJsonDialog(title: string, data: Record<string, unknown>) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal" style="width:min(760px, calc(100vw - 32px))">
      <div class="modal-title">${escapeHtml(title)}</div>
      <pre class="log-box" style="max-height:55vh">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
      <div class="modal-actions"><button class="btn btn-primary" id="tools-json-close">关闭</button></div>
    </div>
  `;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector<HTMLButtonElement>('#tools-json-close')?.addEventListener('click', close);
  overlay.addEventListener('click', (event) => { if (event.target === overlay) close(); });
}

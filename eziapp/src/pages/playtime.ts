// 游玩时长统计页
import { bridge } from '../bridge';
import { confirmDialog, showError, showLoading, toast } from '../ui';
import { errorMessage, escapeHtml } from './common';

interface PlaytimeData {
  total?: number;
  versions?: Record<string, number>;
  sessions?: Array<{ start?: number; duration?: number; version?: string }>;
}

type PlaytimeMap = Record<string, PlaytimeData>;

export function renderPlaytimePage(container: HTMLElement) {
  showLoading(container);
  void loadAndRender(container);
}

async function loadAndRender(container: HTMLElement) {
  try {
    const [allData, totalSeconds] = await Promise.all([
      bridge.call<PlaytimeMap>('get_all_playtime'),
      bridge.call<number>('get_total_playtime'),
    ]);
    if (!container.isConnected) return;
    await render(container, allData || {}, Number(totalSeconds) || 0);
  } catch (error) {
    if (!container.isConnected) return;
    showError(container, '加载游玩时长失败：' + errorMessage(error, '未知错误'), () => void loadAndRender(container));
  }
}

async function formatPlaytime(seconds: number): Promise<string> {
  try {
    return await bridge.call<string>('format_playtime', { seconds });
  } catch {
    const s = Math.max(0, seconds || 0);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (h > 0) return `${h} 小时 ${m} 分钟`;
    return `${m} 分钟`;
  }
}

async function render(container: HTMLElement, allData: PlaytimeMap, totalSeconds: number) {
  const rows = Object.entries(allData).filter(([, d]) => Number(d?.total || 0) > 0);
  const totalText = await formatPlaytime(totalSeconds);

  if (!rows.length) {
    container.innerHTML = `
      <div style="max-width:900px">
        <div class="card">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
            <div class="card-header" style="margin:0">⏱️ 游玩时长</div>
            <button class="btn btn-sm btn-danger" id="playtime-clear">清除记录</button>
          </div>
          <div class="empty-state" style="margin-top:12px">
            <div class="empty-state-icon">⏱️</div>
            <div>还没有游玩记录，启动游戏后会自动记录</div>
          </div>
        </div>
      </div>
    `;
    bindClear(container, '');
    return;
  }

  const cards = await Promise.all(rows.map(async ([name, data]) => {
    const total = Number(data.total || 0);
    const versions = Object.entries(data.versions || {})
      .filter(([, secs]) => Number(secs) > 0)
      .sort((a, b) => Number(b[1]) - Number(a[1]));
    const versionRows = await Promise.all(versions.map(async ([vid, secs]) => {
      const text = await formatPlaytime(Number(secs));
      return `<div style="display:flex;justify-content:space-between;gap:12px;padding:6px 0;font-size:13px;border-bottom:1px solid var(--border-light)">
        <span>${escapeHtml(vid)}</span>
        <span style="color:var(--text-secondary)">${escapeHtml(text)}</span>
      </div>`;
    }));
    const sessions = (data.sessions || []).slice(-5).reverse();
    const sessionRows = sessions.length
      ? `<div style="margin-top:10px;font-size:12px;color:var(--text-secondary)">最近会话</div>` +
        (await Promise.all(sessions.map(async (s) => {
          const dur = await formatPlaytime(Number(s.duration || 0));
          const when = s.start ? new Date(Number(s.start) * 1000).toLocaleString('zh-CN') : '';
          return `<div style="font-size:12px;color:var(--text-disabled);padding:4px 0">${escapeHtml(when)} · ${escapeHtml(s.version || '?')} · ${escapeHtml(dur)}</div>`;
        }))).join('')
      : '';
    return `
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px">
          <div style="font-size:15px;font-weight:600">${escapeHtml(name)}</div>
          <div style="font-size:14px">${escapeHtml(await formatPlaytime(total))}</div>
        </div>
        ${versionRows.join('')}
        ${sessionRows}
      </div>
    `;
  }));

  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px;max-width:900px">
      <div class="card">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px">
          <div>
            <div class="card-header" style="margin:0">⏱️ 总游玩时长</div>
            <div style="font-size:22px;font-weight:700;margin-top:6px">${escapeHtml(totalText)}</div>
          </div>
          <div style="display:flex;gap:8px">
            <button class="btn btn-sm" id="playtime-refresh">↻ 刷新</button>
            <button class="btn btn-sm btn-danger" id="playtime-clear">清除全部</button>
          </div>
        </div>
      </div>
      ${cards.join('')}
    </div>
  `;

  container.querySelector<HTMLButtonElement>('#playtime-refresh')?.addEventListener('click', () => void loadAndRender(container));
  bindClear(container, '');
}

function bindClear(container: HTMLElement, instance: string) {
  container.querySelector<HTMLButtonElement>('#playtime-clear')?.addEventListener('click', async () => {
    const confirmed = await confirmDialog('确认清除', '清除所有游玩时长记录？此操作不可恢复。');
    if (!confirmed) return;
    try {
      await bridge.call('clear_playtime', { instance, version: '' });
      toast('已清除游玩记录', 'success');
      void loadAndRender(container);
    } catch (error) {
      toast(errorMessage(error, '清除失败'), 'error');
    }
  });
}

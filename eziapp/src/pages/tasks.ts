// 下载任务页
import { bridge } from '../bridge';
import { store } from '../store';
import { toast, registerPageCleanup } from '../ui';

export function renderTasksPage(container: HTMLElement) {
  render(container);
  const unsub = store.subscribe(() => render(container));
  registerPageCleanup(() => unsub());
}

function render(container: HTMLElement) {
  const tasks = Array.from(store.tasks.values());
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px">
      <div style="display:flex;gap:8px;align-items:center">
        <span style="font-size:14px;font-weight:600">任务列表</span>
        <span class="tag tag-primary">${tasks.length} 个任务</span>
      </div>
      ${tasks.length === 0
        ? '<div class="empty-state"><div class="empty-state-icon">📋</div><div>暂无下载任务</div></div>'
        : tasks.map(t => `
          <div class="card" style="margin-bottom: 8px">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
              <div class="card-header" style="margin-bottom:0;font-size:14px">${t.title}</div>
              <div style="display:flex;gap:4px;align-items:center">
                ${t.success === undefined
                  ? `<button class="btn btn-sm btn-danger" data-task-id="${t.taskId}" data-action="cancel">取消</button>`
                  : ''}
                ${t.success === true ? '<span style="color:var(--success);font-size:12px">✓ 成功</span>' : ''}
                ${t.success === false ? '<span style="color:var(--danger);font-size:12px">✗ 失败</span>' : ''}
              </div>
            </div>
            <div class="progress-bar" style="margin-bottom:6px">
              <div class="progress-bar-fill" style="width:${t.total > 0 ? Math.min(100, t.current / t.total * 100) : 0}%"></div>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--text-secondary)">
              <span>${t.message || ''}</span>
              <span>${t.total > 0 ? `${Math.round(t.current / t.total * 100)}%` : ''}</span>
            </div>
            ${t.finishedMessage ? `<div style="font-size:12px;color:var(--text-secondary);margin-top:4px">${t.finishedMessage}</div>` : ''}
            ${t.log.length > 0 ? `
              <div class="log-box" style="margin-top:8px;max-height:120px;font-size:11px">
                ${t.log.map(l => escapeHtml(l)).join('\n')}
              </div>
            ` : ''}
          </div>
        `).join('')}
    </div>
  `;

  container.querySelectorAll('[data-action="cancel"]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const taskId = (btn as HTMLElement).dataset.taskId!;
      try {
        await bridge.call('cancel_task', { task_id: taskId });
        toast('任务已取消', 'info');
      } catch (e: any) {
        toast(e.message || '取消失败', 'error');
      }
    });
  });
}

function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}
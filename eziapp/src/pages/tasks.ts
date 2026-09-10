// 下载任务页
import { bridge } from '../bridge';
import { MAX_TASK_LOG_LINES, store, type TaskInfo } from '../store';
import { toast, registerPageCleanup } from '../ui';
import { smoothProgress } from '../motion';
import { escapeHtml } from './common';

// 与 Qt 版 tasks_page._TASK_ICONS 对齐的配色
const TASK_ICONS: [string, string, string][] = [
  ['安装游戏', '游', '#4C8BF5'],
  ['安装整合包', '整', '#7C5CD6'],
  ['安装模组', '模', '#2FA36B'],
  ['安装光影', '影', '#E8862E'],
  ['安装资源包', '资', '#2E9FB8'],
  ['安装数据包', '数', '#2FA36B'],
  ['安装世界', '界', '#2E9B6B'],
  ['下载 Java', 'J', '#D95568'],
  ['启动游戏', '▶', '#D95568'],
  ['微软登录', '微', '#8A6FBD'],
  ['准备陶瓦联机', '联', '#2E9B6B'],
];

function iconFor(title: string): [string, string] {
  for (const [prefix, letter, color] of TASK_ICONS) {
    if (title.startsWith(prefix)) return [letter, color];
  }
  return ['↓', '#4C8BF5'];
}

/** 进度消息里「状态  |  速度」分两栏显示（对齐 Qt 版 split_progress_message）。 */
function splitMessage(message: string): [string, string] {
  const text = message || '';
  if (text.includes('  |  ')) {
    const [status, speed] = text.split('  |  ', 2);
    return [status.trim(), speed.trim()];
  }
  return [text, ''];
}

export function renderTasksPage(container: HTMLElement) {
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:12px;max-width:1000px">
      <div class="form-row">
        <span style="font-size:14px;font-weight:680">任务列表</span>
        <span class="tag tag-primary" id="task-total">0 个任务</span>
        <span style="flex:1"></span>
        <button class="btn btn-sm" id="task-clear" style="display:none">清除已完成</button>
      </div>
      <div id="task-empty" class="empty-state"><div class="empty-state-icon">📋</div><div>暂无下载任务 —— 去下载板块里的版本 / 整合包 / 模组 / 光影 / 资源包 / Java 发起</div></div>
      <div id="task-host" style="display:flex;flex-direction:column;gap:10px"></div>
    </div>`;

  const host = container.querySelector<HTMLElement>('#task-host')!;
  const empty = container.querySelector<HTMLElement>('#task-empty')!;
  const total = container.querySelector<HTMLElement>('#task-total')!;
  const clearBtn = container.querySelector<HTMLButtonElement>('#task-clear')!;
  const cards = new Map<string, TaskCard>();

  clearBtn.addEventListener('click', () => {
    for (const task of Array.from(store.tasks.values())) {
      if (task.success !== undefined) store.removeTask(task.taskId);
    }
    toast('已清除完成的任务', 'success');
  });

  // 整块 innerHTML 重绘会把进度条元素连同它的 CSS 过渡一起换掉，
  // 结果就是进度永远在跳格。这里改成建一次、之后只改属性。
  let lastTotal = -1;
  let lastHasDone: boolean | null = null;
  const sync = () => {
    const tasks = Array.from(store.tasks.values());
    if (tasks.length !== lastTotal) {
      lastTotal = tasks.length;
      total.textContent = `${tasks.length} 个任务`;
      empty.style.display = tasks.length ? 'none' : '';
    }
    const hasDone = tasks.some((t) => t.success !== undefined);
    if (hasDone !== lastHasDone) {
      lastHasDone = hasDone;
      clearBtn.style.display = hasDone ? '' : 'none';
    }

    for (const [id, card] of cards) {
      if (!store.tasks.has(id)) {
        card.root.remove();
        cards.delete(id);
      }
    }
    let pending: DocumentFragment | null = null;
    for (const task of tasks) {
      let card = cards.get(task.taskId);
      if (!card) {
        card = buildCard(task);
        cards.set(task.taskId, card);
        (pending ||= document.createDocumentFragment()).appendChild(card.root);
      }
      updateCard(card, task);
    }
    if (pending) host.appendChild(pending);
  };

  sync();
  const unsub = store.subscribe(sync);
  registerPageCleanup(unsub);
}

/**
 * 每帧都 querySelector 一遍角色元素，在下载高峰期是纯浪费——建卡时取一次存起来，
 * 之后只写属性。`shown` 存的是上一次写进去的值，相同就整个跳过，DOM 一动不动。
 */
interface TaskCard {
  root: HTMLElement;
  title: HTMLElement;
  state: HTMLElement;
  cancel: HTMLElement;
  fill: HTMLElement;
  message: HTMLElement;
  speed: HTMLElement;
  done: HTMLElement;
  log: HTMLElement;
  /** 已渲染到 DOM 的累计行号，用来算这一轮该补几行 */
  logSeq: number;
  /** 当前日志框里实际有多少行，超过阈值就整段重置，避免 DOM 无限长 */
  lines: number;
  shown: Record<string, string>;
}

// store 只留 MAX_TASK_LOG_LINES 行，DOM 允许多攒半程再重置一次
const LOG_RESET_AT = Math.floor(MAX_TASK_LOG_LINES * 1.5);

function buildCard(task: TaskInfo): TaskCard {
  const card = document.createElement('div');
  card.className = 'card';
  const [letter, color] = iconFor(task.title || '');
  card.innerHTML = `
    <div style="display:flex;gap:12px;align-items:flex-start">
      <div class="task-icon" style="background:${color}">${escapeHtml(letter)}</div>
      <div style="flex:1;min-width:0">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px">
          <div class="card-header" style="margin:0;font-size:14px" data-role="title"></div>
          <div style="display:flex;gap:6px;align-items:center">
            <span data-role="state" style="font-size:12px"></span>
            <button class="btn btn-sm" data-role="toggle">日志</button>
            <button class="btn btn-sm btn-danger" data-role="cancel">取消</button>
          </div>
        </div>
        <div class="progress-bar" style="margin-bottom:6px"><div class="progress-bar-fill" data-role="fill" style="width:0%"></div></div>
        <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--text-secondary)">
          <span data-role="message"></span><span data-role="speed" style="flex:0 0 auto;padding-left:10px"></span>
        </div>
        <div data-role="done" style="font-size:12px;color:var(--text-secondary);margin-top:4px"></div>
        <div class="log-box" data-role="log" style="margin-top:8px;max-height:180px;font-size:11px;display:none"></div>
      </div>
    </div>`;
  card.querySelector('[data-role="cancel"]')!.addEventListener('click', async () => {
    try {
      await bridge.call('cancel_task', { task_id: task.taskId });
      toast('任务已取消', 'info');
    } catch (e: any) {
      toast(e.message || '取消失败', 'error');
    }
  });
  const pick = (role: string) => card.querySelector<HTMLElement>(`[data-role="${role}"]`)!;
  const log = pick('log');
  card.querySelector('[data-role="toggle"]')!.addEventListener('click', () => {
    const show = log.style.display === 'none';
    log.style.display = show ? '' : 'none';
    if (show) log.scrollTop = log.scrollHeight;
  });
  return {
    root: card,
    title: pick('title'), state: pick('state'), cancel: pick('cancel'),
    fill: pick('fill'), message: pick('message'), speed: pick('speed'),
    done: pick('done'), log,
    logSeq: 0,
    lines: 0,
    shown: {},
  };
}

/** 值没变就不碰 DOM——省掉的是重排，不只是一次赋值。 */
function setText(card: TaskCard, key: string, el: HTMLElement, value: string) {
  if (card.shown[key] === value) return;
  card.shown[key] = value;
  el.textContent = value;
}

function updateCard(card: TaskCard, task: TaskInfo) {
  const running = task.success === undefined;
  const percent = task.total > 0 ? Math.min(100, (task.current / task.total) * 100) : 0;
  setText(card, 'title', card.title, task.title || '任务');
  smoothProgress(card.fill, percent, !running && task.success === true);
  const [status, speed] = splitMessage(task.message || '');
  setText(card, 'message', card.message, status || (running ? '排队中…' : ''));
  setText(card, 'speed', card.speed, speed || (task.total > 0 ? `${Math.round(percent)}%` : ''));
  setText(card, 'state', card.state, running ? '' : task.success ? '✓ 成功' : '✗ 失败');
  const stateColor = task.success ? 'var(--success)' : 'var(--danger)';
  if (card.shown.stateColor !== stateColor) {
    card.shown.stateColor = stateColor;
    card.state.style.color = stateColor;
  }
  const cancelShown = running ? '' : 'none';
  if (card.shown.cancel !== cancelShown) {
    card.shown.cancel = cancelShown;
    card.cancel.style.display = cancelShown;
  }
  setText(card, 'done', card.done, task.finishedMessage || '');

  const log = card.log;
  if (!task.log.length) {
    log.style.display = 'none';
    return;
  }
  if (task.logSeq !== card.logSeq) {
    // 只补这一轮新增的几行。整段 join 重拼在上万行的整合包日志上是 O(n²)。
    const added = task.logSeq - card.logSeq;
    if (added >= task.log.length || card.lines + added > LOG_RESET_AT) {
      // 落后太多（换了任务 / 刚建卡），或者 DOM 里攒够了就整段重置。
      // 留一段余量再重置，中间那几百次追加才摊得平。
      log.textContent = task.log.join('\n');
      card.lines = task.log.length;
    } else {
      log.appendChild(document.createTextNode(`\n${task.log.slice(-added).join('\n')}`));
      card.lines += added;
    }
    card.logSeq = task.logSeq;
    if (log.style.display !== 'none') log.scrollTop = log.scrollHeight;
  }
  // 整合包安装自动展开日志（对齐 Qt 版 TaskCard）
  if (log.style.display === 'none' && (task.title || '').includes('整合包') && running) log.style.display = '';
}

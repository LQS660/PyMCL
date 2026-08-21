// AI 助手页：多会话、流式回答，以及安装操作的确认与选择。
import { bridge } from '../bridge';
import { store, type AIChat } from '../store';
import { confirmDialog, registerPageCleanup, showError, showLoading, toast } from '../ui';
import { errorMessage, escapeHtml, scrollToBottom } from './common';

interface ChatStoreResponse {
  active_id?: string;
  chats?: AIChat[];
}

interface AskOption {
  id?: string;
  label?: string;
}

interface AskQuestion {
  id?: string;
  prompt?: string;
  allow_multiple?: boolean;
  options?: AskOption[];
}

let pageToken = 0;
let streamActive = false;
let streamText = '';
let latestFailure = '';

export function renderAIPage(container: HTMLElement) {
  const token = ++pageToken;
  showLoading(container);

  const load = async () => {
    try {
      const data = await bridge.call<ChatStoreResponse>('ai_list_chats');
      if (token !== pageToken || !container.isConnected) return;
      applyChatStore(data);
      render(container, load);
    } catch (error) {
      if (token !== pageToken || !container.isConnected) return;
      showError(container, `加载 AI 对话失败：${errorMessage(error, '未知错误')}`, () => void load());
    }
  };

  const removeDelta = bridge.subscribe('ai.delta', (data) => {
    if (token !== pageToken || !container.isConnected) return;
    streamActive = true;
    streamText += String(data.text || '');
    updateStreamingMessage(container, streamText);
  });
  const removeStatus = bridge.subscribe('ai.status', (data) => {
    if (token !== pageToken || !container.isConnected) return;
    const status = container.querySelector<HTMLElement>('#ai-status');
    if (status) {
      const label = String(data.label || data.message || data.kind || 'AI 正在处理…');
      status.textContent = label;
    }
  });
  const removeDone = bridge.subscribe('ai.done', (data) => {
    if (token !== pageToken || !container.isConnected) return;
    streamActive = false;
    streamText = '';
    applyChatStore((data.store || {}) as ChatStoreResponse);
    render(container, load);
  });
  const removeFail = bridge.subscribe('ai.fail', (data) => {
    if (token !== pageToken || !container.isConnected) return;
    streamActive = false;
    const message = String(data.text || 'AI 请求失败');
    latestFailure = message;
    streamText = '';
    toast(message, data.stopped ? 'info' : 'error');
    render(container, load);
  });
  const removeConfirm = bridge.subscribe('ai.confirm', (data) => {
    void (async () => {
      const label = String(data.label || `执行 ${String(data.name || '操作')}`);
      const accepted = await confirmDialog('AI 请求确认', label);
      try {
        await bridge.call('ai_confirm', { ok: accepted });
      } catch (error) {
        toast(errorMessage(error, '无法提交确认结果'), 'error');
      }
    })();
  });
  const removeAsk = bridge.subscribe('ai.ask', (data) => {
    void (async () => {
      const result = await showAskDialog(
        Array.isArray(data.questions) ? data.questions as AskQuestion[] : [],
        String(data.title || '请选择'),
      );
      try {
        await bridge.call('ai_answer', { result });
      } catch (error) {
        toast(errorMessage(error, '无法提交选择结果'), 'error');
      }
    })();
  });
  registerPageCleanup(() => {
    if (token === pageToken) pageToken += 1;
    streamActive = false;
    streamText = '';
    removeDelta();
    removeStatus();
    removeDone();
    removeFail();
    removeConfirm();
    removeAsk();
  });

  void load();
}

function applyChatStore(data: ChatStoreResponse) {
  const chats = Array.isArray(data.chats) ? data.chats : [];
  const activeId = String(data.active_id || chats[0]?.id || '');
  store.setAIChats(chats, activeId);
}

function render(container: HTMLElement, load: () => Promise<void>) {
  const chats = store.aiChats;
  const activeId = store.aiActiveId || chats[0]?.id || '';
  const activeChat = chats.find((chat) => chat.id === activeId) || chats[0];
  const messages = activeChat?.messages || [];
  container.innerHTML = `
    <div class="ai-layout">
      <aside class="ai-sidebar">
        <button class="btn btn-primary" id="ai-new-chat">＋ 新对话</button>
        <div class="ai-chat-list">
          ${chats.map((chat) => `
            <div class="ai-chat-row ${chat.id === activeChat?.id ? 'active' : ''}">
              <button class="ai-chat-select" data-ai-chat="${escapeHtml(chat.id)}" title="${escapeHtml(chat.title || '新对话')}">${escapeHtml(chat.title || '新对话')}</button>
              <button class="btn btn-icon btn-sm" data-ai-delete="${escapeHtml(chat.id)}" title="删除对话">×</button>
            </div>
          `).join('') || '<div style="padding:12px;font-size:12px;color:var(--text-secondary)">暂无对话</div>'}
        </div>
      </aside>
      <section class="ai-main">
        <div class="ai-messages" id="ai-messages">
          ${messages.length ? messages.map(renderMessage).join('') : '<div class="empty-state" style="flex:1"><div class="empty-state-icon">🤖</div><div>可以问我安装版本、找模组或分析启动问题。</div></div>'}
          ${latestFailure ? renderStreamingMessage(latestFailure, true) : ''}
          ${streamActive ? renderStreamingMessage(streamText) : ''}
        </div>
        <div class="ai-status" id="ai-status">${streamActive ? 'AI 正在回答…' : ''}</div>
        <div class="ai-input-row">
          <textarea class="input" id="ai-input" rows="2" placeholder="问我要下什么、哪里报错、模组怎么配…" ${streamActive ? 'disabled' : ''}></textarea>
          <button class="btn btn-primary" id="ai-send" ${streamActive ? 'disabled' : ''}>发送</button>
          <button class="btn btn-danger" id="ai-stop" style="display:${streamActive ? '' : 'none'}">停止</button>
        </div>
      </section>
    </div>
  `;

  const messagesBox = container.querySelector<HTMLElement>('#ai-messages');
  scrollToBottom(messagesBox);
  container.querySelector<HTMLButtonElement>('#ai-new-chat')?.addEventListener('click', async () => {
    if (streamActive) {
      toast('请等待当前回答结束后再新建对话', 'warning');
      return;
    }
    try {
      const data = await bridge.call<ChatStoreResponse>('ai_new_chat');
      applyChatStore(data);
      render(container, load);
    } catch (error) {
      toast(errorMessage(error, '新建对话失败'), 'error');
    }
  });
  container.querySelectorAll<HTMLButtonElement>('[data-ai-chat]').forEach((button) => {
    button.addEventListener('click', async () => {
      if (streamActive) {
        toast('请等待当前回答结束后再切换对话', 'warning');
        return;
      }
      try {
        const data = await bridge.call<ChatStoreResponse>('ai_set_active', { chat_id: button.dataset.aiChat || '' });
        applyChatStore(data);
        render(container, load);
      } catch (error) {
        toast(errorMessage(error, '切换对话失败'), 'error');
      }
    });
  });
  container.querySelectorAll<HTMLButtonElement>('[data-ai-delete]').forEach((button) => {
    button.addEventListener('click', async (event) => {
      event.stopPropagation();
      if (streamActive) {
        toast('请等待当前回答结束后再删除对话', 'warning');
        return;
      }
      const confirmed = await confirmDialog('删除对话', '确定要删除这条 AI 对话吗？');
      if (!confirmed) return;
      try {
        const data = await bridge.call<ChatStoreResponse>('ai_delete_chat', { chat_id: button.dataset.aiDelete || '' });
        applyChatStore(data);
        render(container, load);
      } catch (error) {
        toast(errorMessage(error, '删除对话失败'), 'error');
      }
    });
  });

  const send = async () => {
    const input = container.querySelector<HTMLTextAreaElement>('#ai-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text || streamActive) return;
    streamActive = true;
    streamText = '';
    latestFailure = '';
    input.value = '';
    container.querySelector('#ai-streaming-message')?.remove();
    appendMessage(container, 'user', text);
    updateStreamingMessage(container, '');
    const sendButton = container.querySelector<HTMLButtonElement>('#ai-send');
    if (sendButton) {
      sendButton.textContent = '处理中…';
      sendButton.disabled = true;
    }
    const stopButton = container.querySelector<HTMLButtonElement>('#ai-stop');
    if (stopButton) stopButton.style.display = '';
    try {
      const result = await bridge.call<{ ok?: boolean; message?: string }>('ai_send', {
        text,
        chat_id: activeChat?.id || '',
        launch: {
          instance: store.currentInstance,
          version: store.currentVersion,
          account: store.currentAccount,
          username: store.currentUsername,
          memory_mb: store.currentMemory,
          width: store.currentWidth,
          height: store.currentHeight,
          java: store.currentJava,
        },
      });
      if (result && result.ok === false) throw new Error(result.message || 'AI 暂时无法处理请求');
      const status = container.querySelector<HTMLElement>('#ai-status');
      if (status) status.textContent = 'AI 正在回答…';
    } catch (error) {
      streamActive = false;
      latestFailure = errorMessage(error, 'AI 请求失败');
      streamText = '';
      render(container, load);
    }
  };
  container.querySelector<HTMLButtonElement>('#ai-send')?.addEventListener('click', () => void send());
  container.querySelector<HTMLTextAreaElement>('#ai-input')?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      void send();
    }
  });
  container.querySelector<HTMLButtonElement>('#ai-stop')?.addEventListener('click', async () => {
    try {
      await bridge.call('ai_stop');
    } catch (error) {
      toast(errorMessage(error, '停止 AI 请求失败'), 'error');
    }
  });
}

function renderMessage(message: { role: string; content: string }): string {
  const role = message.role === 'user' ? 'user' : message.role === 'error' ? 'error' : 'assistant';
  const label = role === 'user' ? '你' : role === 'error' ? '错误' : 'PyMCL AI';
  return `<article class="ai-message ${role}"><div class="ai-message-label">${label}</div><div class="ai-message-content">${escapeHtml(message.content)}</div></article>`;
}

function renderStreamingMessage(text: string, failed = false): string {
  return `<article class="ai-message ${failed ? 'error' : 'assistant'}" id="ai-streaming-message"><div class="ai-message-label">${failed ? '错误' : 'PyMCL AI'}</div><div class="ai-message-content" id="ai-streaming-content">${escapeHtml(text || '…')}</div></article>`;
}

function appendMessage(container: HTMLElement, role: 'user' | 'assistant' | 'error', content: string) {
  const box = container.querySelector<HTMLElement>('#ai-messages');
  if (!box) return;
  const empty = box.querySelector('.empty-state');
  if (empty) empty.remove();
  const host = document.createElement('div');
  host.innerHTML = renderMessage({ role, content });
  const message = host.firstElementChild;
  if (message) box.appendChild(message);
  scrollToBottom(box);
}

function updateStreamingMessage(container: HTMLElement, text: string, failed = false) {
  const box = container.querySelector<HTMLElement>('#ai-messages');
  if (!box) return;
  const empty = box.querySelector('.empty-state');
  if (empty) empty.remove();
  let message = box.querySelector<HTMLElement>('#ai-streaming-message');
  if (!message) {
    const host = document.createElement('div');
    host.innerHTML = renderStreamingMessage(text, failed);
    message = host.firstElementChild as HTMLElement | null;
    if (message) box.appendChild(message);
  }
  if (!message) return;
  message.classList.toggle('error', failed);
  message.classList.toggle('assistant', !failed);
  const label = message.querySelector<HTMLElement>('.ai-message-label');
  const content = message.querySelector<HTMLElement>('#ai-streaming-content');
  if (label) label.textContent = failed ? '错误' : 'PyMCL AI';
  if (content) content.textContent = text || '…';
  scrollToBottom(box);
}

function showAskDialog(rawQuestions: AskQuestion[], title: string): Promise<Record<string, unknown> | null> {
  const questions = rawQuestions.length ? rawQuestions : [{
    id: 'q1', prompt: '请选择', allow_multiple: false,
    options: [{ id: 'skip', label: '先不选' }, { id: 'other', label: '其他' }],
  }];
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = `
      <div class="modal" style="min-width:min(560px, calc(100vw - 32px))">
        <div class="modal-title">${escapeHtml(title || '请选择')}</div>
        <div id="ai-ask-questions">${questions.map((question, questionIndex) => renderAskQuestion(question, questionIndex)).join('')}</div>
        <div id="ai-ask-error" style="font-size:12px;color:var(--danger);min-height:18px;margin-top:8px"></div>
        <div class="modal-actions"><button class="btn" id="ai-ask-cancel">跳过</button><button class="btn btn-primary" id="ai-ask-submit">确定</button></div>
      </div>
    `;
    document.body.appendChild(overlay);

    overlay.querySelectorAll<HTMLInputElement>('[data-ai-other-toggle]').forEach((input) => {
      input.addEventListener('change', () => {
        const key = input.dataset.aiOtherToggle || '';
        const edit = overlay.querySelector<HTMLInputElement>(`[data-ai-other-input="${CSS.escape(key)}"]`);
        if (edit) edit.style.display = input.checked ? '' : 'none';
      });
    });
    const finish = (result: Record<string, unknown> | null) => {
      overlay.remove();
      resolve(result);
    };
    overlay.querySelector<HTMLButtonElement>('#ai-ask-cancel')?.addEventListener('click', () => finish(null));
    overlay.addEventListener('click', (event) => {
      if (event.target === overlay) finish(null);
    });
    overlay.querySelector<HTMLButtonElement>('#ai-ask-submit')?.addEventListener('click', () => {
      const answers: Record<string, unknown> = {};
      const error = overlay.querySelector<HTMLElement>('#ai-ask-error')!;
      for (let questionIndex = 0; questionIndex < questions.length; questionIndex += 1) {
        const question = questions[questionIndex];
        const key = String(question.id || `q${questionIndex + 1}`);
        const choices = Array.from(overlay.querySelectorAll<HTMLInputElement>(`[data-ai-question="${CSS.escape(String(questionIndex))}"]:checked`));
        if (!choices.length) {
          error.textContent = `请完成：${String(question.prompt || '请选择')}`;
          return;
        }
        const ids = choices.map((choice) => String(choice.dataset.aiOptionId || ''));
        const labels = choices.map((choice) => String(choice.dataset.aiOptionLabel || choice.value || ''));
        const other = overlay.querySelector<HTMLInputElement>(`[data-ai-other-input="${CSS.escape(String(questionIndex))}"]`)?.value.trim() || '';
        if (ids.includes('other') && !other && ids.length === 1) {
          error.textContent = '选择“其他”时请补充说明。';
          return;
        }
        answers[key] = { ids, labels, other_text: ids.includes('other') ? other : '' };
      }
      finish({ answers });
    });
  });
}

function renderAskQuestion(question: AskQuestion, questionIndex: number): string {
  const options = Array.isArray(question.options) ? question.options : [];
  const type = question.allow_multiple ? 'checkbox' : 'radio';
  const name = `ai-question-${questionIndex}`;
  return `
    <fieldset style="border:0;padding:0;margin:0 0 16px">
      <legend style="font-size:13px;font-weight:600;margin-bottom:8px">${escapeHtml(question.prompt || '请选择')}${question.allow_multiple ? '（可多选）' : ''}</legend>
      <div style="display:flex;flex-direction:column;gap:6px">
        ${options.map((option, optionIndex) => {
          const id = String(option.id || `opt_${optionIndex}`);
          const label = String(option.label || id);
          return `<label style="display:flex;align-items:center;gap:7px;font-size:13px"><input type="${type}" name="${name}" data-ai-question="${questionIndex}" data-ai-option-id="${escapeHtml(id)}" data-ai-option-label="${escapeHtml(label)}" ${id === 'other' ? `data-ai-other-toggle="${questionIndex}"` : ''}> ${escapeHtml(label)}</label>`;
        }).join('')}
      </div>
      <input class="input" data-ai-other-input="${questionIndex}" style="display:none;width:100%;margin-top:8px" placeholder="补充说明">
    </fieldset>
  `;
}

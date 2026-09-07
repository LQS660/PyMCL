// BridgeClient — authenticated JSON-RPC + SSE client for the local PyMCL bridge.
export interface BridgeEvent {
  event: string;
  data: Record<string, unknown>;
}

interface BridgeConfig {
  rpc_url: string;
  token: string;
}

type EventHandler = (data: Record<string, unknown>) => void;

const TOKEN_HEADER = 'X-PyMCL-Bridge-Token';

function parseBridgeConfig(value: unknown): BridgeConfig | null {
  if (!value || typeof value !== 'object') return null;
  const candidate = value as Partial<BridgeConfig>;
  if (typeof candidate.rpc_url !== 'string' || typeof candidate.token !== 'string' || candidate.token.length < 32) {
    return null;
  }
  try {
    const url = new URL(candidate.rpc_url);
    if (
      url.protocol !== 'http:'
      || url.hostname !== '127.0.0.1'
      || !url.port
      || url.username
      || url.password
      || (url.pathname !== '/' && url.pathname !== '')
      || url.search
      || url.hash
    ) {
      return null;
    }
    return { rpc_url: url.origin, token: candidate.token };
  } catch {
    return null;
  }
}

function runtimeConfigFromFragment(): BridgeConfig | null {
  const params = new URLSearchParams(window.location.hash.slice(1));
  const encoded = params.get('pymcl_bridge');
  if (!encoded) return null;
  try {
    const base64 = encoded.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
    const config = parseBridgeConfig(JSON.parse(atob(padded)));
    if (config) {
      // The fragment is never sent to the server; remove it promptly so it
      // cannot remain in browser history or be copied from the address bar.
      history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
    }
    return config;
  } catch {
    return null;
  }
}

export class BridgeClient {
  private baseUrl = '';
  private token = '';
  private eventSource: EventSource | null = null;
  private handlers: Map<string, Set<EventHandler>> = new Map();
  private requestId = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private connected = false;

  setConnection(config: BridgeConfig) {
    this.baseUrl = config.rpc_url;
    this.token = config.token;
  }

  clearConnection() {
    this.close();
    this.baseUrl = '';
    this.token = '';
  }

  isConfigured(): boolean {
    return Boolean(this.baseUrl && this.token);
  }

  async call<T = unknown>(method: string, params?: Record<string, unknown> | unknown[]): Promise<T> {
    if (!this.isConfigured()) {
      throw new Error('本次启动未配置 Python 桥接服务');
    }
    const id = ++this.requestId;
    const body = { jsonrpc: '2.0', id, method, params: params ?? {} };
    const resp = await fetch(`${this.baseUrl}/rpc`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        [TOKEN_HEADER]: this.token,
      },
      body: JSON.stringify(body),
      cache: 'no-store',
    });
    let json: any = {};
    try {
      json = await resp.json();
    } catch {
      // The status below still gives a useful error for a non-JSON proxy page.
    }
    if (!resp.ok) {
      throw new Error(json.error?.message || json.error || `桥接请求失败 (${resp.status})`);
    }
    if (json.error) {
      throw new Error(json.error?.message || '未知错误');
    }
    return json.result as T;
  }

  connectEvents(): void {
    if (!this.isConfigured()) return;
    if (this.eventSource) this.close();
    const url = `${this.baseUrl}/events?token=${encodeURIComponent(this.token)}`;
    this.eventSource = new EventSource(url);

    this.eventSource.onopen = () => {
      this.connected = true;
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
    };

    this.eventSource.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        this.emit('message', data);
      } catch { /* ignore malformed events */ }
    };

    const events = [
      'hello', 'task_added', 'progress', 'log', 'finished',
      'task_count_changed', 'ui_changed', 'login_code', 'login_status',
      'crash', 'game_started', 'game_exited',
      'ai.delta', 'ai.status', 'ai.confirm', 'ai.ask', 'ai.done', 'ai.fail',
    ];
    for (const event of events) {
      this.eventSource.addEventListener(event, (ev) => this.parseAndEmit(ev, event));
    }

    this.eventSource.onerror = () => {
      this.connected = false;
      this.close();
      if (!this.reconnectTimer && this.isConfigured()) {
        this.reconnectTimer = setTimeout(() => {
          this.reconnectTimer = null;
          this.connectEvents();
        }, 3000);
      }
    };
  }

  private parseAndEmit(ev: Event, eventName: string) {
    try {
      const data = JSON.parse((ev as MessageEvent).data);
      this.emit(eventName, data);
    } catch { /* ignore malformed events */ }
  }

  subscribe(event: string, handler: EventHandler): () => void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)!.add(handler);
    return () => this.handlers.get(event)?.delete(handler);
  }

  private emit(event: string, data: Record<string, unknown>) {
    const handlers = this.handlers.get(event);
    if (handlers) {
      handlers.forEach((handler) => handler(data));
    }
  }

  close() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    this.connected = false;
  }

  isConnected(): boolean {
    return this.connected;
  }
}

async function loadBridgeConfig(): Promise<BridgeConfig | null> {
  const fragmentConfig = runtimeConfigFromFragment();
  if (fragmentConfig) return fragmentConfig;
  try {
    const resp = await fetch('/bridge-config.json', { cache: 'no-store' });
    if (resp.ok) return parseBridgeConfig(await resp.json());
  } catch { /* The launcher will present a connection error below. */ }
  return null;
}

export const bridge = new BridgeClient();

export async function initBridge(): Promise<boolean> {
  const config = await loadBridgeConfig();
  const { store } = await import('./store');
  if (!config) {
    bridge.clearConnection();
    store.bridgeUrl = '';
    return false;
  }
  bridge.setConnection(config);
  store.bridgeUrl = config.rpc_url;
  return true;
}

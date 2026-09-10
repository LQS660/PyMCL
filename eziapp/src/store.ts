// 全局状态管理
export interface TaskInfo {
  taskId: string;
  title: string;
  current: number;
  total: number;
  message: string;
  success?: boolean;
  finishedMessage?: string;
  log: string[];
  /** 累计收到过的日志行数。log 是环形缓冲，靠它才能算出该补几行。 */
  logSeq: number;
  crashed?: boolean;
}

export interface InstanceInfo {
  name: string;
  versions: number;
  mc: string;
  pack: string;
  packVersion: string;
  mcVersion: string;
  java: string;
  javaLabel: string;
}

export interface VersionInfo {
  version: string;
  type: string;
  date: string;
}

export interface JavaInfo {
  name: string;
  major: string;
  path: string;
}

export interface AccountInfo {
  name: string;
  type: string;
  uuid: string;
  api: string;
  avatar: string;
  body: string;
  active: boolean;
}

export interface ModInfo {
  name: string;
  author: string;
  downloads: number;
  id?: string;
  slug?: string;
  source: string;
  description: string;
  tags: string[];
  updated: string;
}

export interface SettingsInfo {
  share_libraries: boolean;
  share_assets: boolean;
  download_threads: number;
  default_memory_mb: number;
  default_resolution: number[];
  ms_client_id: string;
  curseforge_api_key: string;
  ai_mode: string;
  ai_gateway_url: string;
  ai_base_url: string;
  ai_api_key: string;
  ai_model: string;
  root: string;
  feedback_url: string;
  feedback_heartbeat: boolean;
  feedback_consent: boolean;
  default_isolation: string;
  default_jvm_args: string;
  update_url: string;
  download_source: string;
  community_source: string;
  use_system_proxy: boolean;
  launcher_visibility: string;
  gc_preset: string;
  download_limit_kbps: number;
  auto_check_update: boolean;
  custom_homepage: string;
  homepage_mode: string;
  window_mode: string;
  game_dir: string;
  offline_skin: string;
}

export interface AIChat {
  id: string;
  title: string;
  messages?: { role: string; content: string }[];
}

type Listener = () => void;

// 这些键桥接的 get_settings/save_settings 不往返（纯前端外观偏好），
// 用 localStorage 做覆盖层，重启后仍然生效。
export const LOCAL_PREF_KEYS = [
  'theme_color', 'ui_background', 'ui_motion',
  'ui_fly_animation', 'ui_fly_duration_ms', 'ui_sidebar_width', 'skip_assets',
] as const;

const LOCAL_PREFS_KEY = 'pymcl.localPrefs';

// 一次安装里 progress/log 事件是几十上百每秒，每一条都同步重绘会把主线程占满。
// 攒到下一帧统一发一次，订阅方的开销就跟帧率挂钩而不是跟事件量挂钩。
export const MAX_TASK_LOG_LINES = 400;

export function loadLocalPrefs(): Record<string, unknown> {
  try {
    const raw = localStorage.getItem(LOCAL_PREFS_KEY);
    const data = raw ? JSON.parse(raw) : {};
    return data && typeof data === 'object' ? data : {};
  } catch {
    return {};
  }
}

export function saveLocalPrefs(patch: Record<string, unknown>) {
  const merged = { ...loadLocalPrefs(), ...patch };
  try {
    localStorage.setItem(LOCAL_PREFS_KEY, JSON.stringify(merged));
  } catch { /* storage may be full or blocked */ }
  return merged;
}

class Store {
  private listeners: Set<Listener> = new Set();
  private flushHandle = 0;

  tasks: Map<string, TaskInfo> = new Map();
  taskCount = 0;
  instances: InstanceInfo[] = [];
  versionList: VersionInfo[] = [];
  javaList: JavaInfo[] = [];
  accounts: AccountInfo[] = [];
  activeAccount = '离线模式';
  settings: SettingsInfo | null = null;
  localPrefs: Record<string, unknown> = loadLocalPrefs();
  pendingClipLink = '';
  aiChats: AIChat[] = [];
  aiActiveId = '';
  currentVersion: string = '';
  currentInstance: string = '';
  currentAccount: string = '离线模式';
  currentUsername: string = 'Player';
  currentMemory: number = 4096;
  currentWidth: number = 854;
  currentHeight: number = 480;
  currentJava: string = '自动选择';
  currentServer: string = '';
  launchLog: string[] = [];
  gameRunning = false;
  bridgeConnected = false;
  bridgeUrl: string = 'http://127.0.0.1:18080';

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /** 攒到下一帧再发。同一帧里调多少次都只重绘一次。 */
  notify() {
    if (this.flushHandle) return;
    this.flushHandle = requestAnimationFrame(() => {
      this.flushHandle = 0;
      this.flushNow();
    });
  }

  /** 立即发一次，并吃掉已排队的那一帧。渲染前取初值时用。 */
  flushNow() {
    if (this.flushHandle) {
      cancelAnimationFrame(this.flushHandle);
      this.flushHandle = 0;
    }
    this.listeners.forEach((fn) => fn());
  }

  updateTask(taskId: string, data: Partial<TaskInfo>) {
    const existing = this.tasks.get(taskId) || {
      taskId, title: '', current: 0, total: 0, message: '', log: [], logSeq: 0,
    };
    Object.assign(existing, data);
    this.tasks.set(taskId, existing);
    this.notify();
  }

  removeTask(taskId: string) {
    this.tasks.delete(taskId);
    this.notify();
  }

  addLog(taskId: string, text: string) {
    const task = this.tasks.get(taskId);
    if (!task) return;
    task.log.push(text);
    task.logSeq += 1;
    // 整合包安装能刷出上万行；不封顶的话光是把它拼成一整段就够卡住一帧。
    if (task.log.length > MAX_TASK_LOG_LINES) {
      task.log.splice(0, task.log.length - MAX_TASK_LOG_LINES);
    }
    this.notify();
  }

  setInstances(instances: InstanceInfo[]) {
    this.instances = instances;
    this.notify();
  }

  setVersionList(versions: VersionInfo[]) {
    this.versionList = versions;
    this.notify();
  }

  setJavaList(javas: JavaInfo[]) {
    this.javaList = javas;
    this.notify();
  }

  setAccounts(accounts: AccountInfo[]) {
    this.accounts = accounts;
    const active = accounts.find((a) => a.active);
    if (active) {
      this.activeAccount = active.name;
    }
    this.notify();
  }

  setSettings(settings: SettingsInfo) {
    this.settings = settings;
    this.notify();
  }

  /** 后端设置 + 本地外观覆盖层合并后的视图。 */
  mergedSettings(): Record<string, unknown> {
    return { ...(this.settings || {}), ...this.localPrefs };
  }

  setLocalPrefs(patch: Record<string, unknown>) {
    this.localPrefs = saveLocalPrefs(patch);
    this.notify();
  }

  setAIChats(chats: AIChat[], activeId?: string) {
    this.aiChats = chats;
    if (activeId) this.aiActiveId = activeId;
    this.notify();
  }

  deleteAccount(uuid: string) {
    this.accounts = this.accounts.filter(a => a.uuid !== uuid);
    this.notify();
  }
}

export const store = new Store();
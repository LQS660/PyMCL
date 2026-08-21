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

class Store {
  private listeners: Set<Listener> = new Set();

  tasks: Map<string, TaskInfo> = new Map();
  taskCount = 0;
  instances: InstanceInfo[] = [];
  versionList: VersionInfo[] = [];
  javaList: JavaInfo[] = [];
  accounts: AccountInfo[] = [];
  activeAccount = '离线模式';
  settings: SettingsInfo | null = null;
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
  launchLog: string[] = [];
  gameRunning = false;
  bridgeConnected = false;
  bridgeUrl: string = 'http://127.0.0.1:18080';

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  notify() {
    this.listeners.forEach((fn) => fn());
  }

  updateTask(taskId: string, data: Partial<TaskInfo>) {
    const existing = this.tasks.get(taskId) || {
      taskId, title: '', current: 0, total: 0, message: '', log: [],
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
    if (task) {
      task.log.push(text);
      this.notify();
    }
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
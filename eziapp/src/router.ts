// 简单路由管理
export type PageKey =
  | 'launch'
  | 'instances'
  | 'downloads'
  | 'vanilla'
  | 'mods'
  | 'modpacks'
  | 'datapacks'
  | 'resourcepacks'
  | 'shaders'
  | 'tasks'
  | 'accounts'
  | 'java'
  | 'servers'
  | 'playtime'
  | 'multiplayer'
  | 'ai'
  | 'settings'
  | 'feedback'
  | 'tools';

type Listener = (page: PageKey) => void;

class Router {
  private currentPage: PageKey = 'launch';
  private listeners: Set<Listener> = new Set();
  private history: PageKey[] = ['launch'];

  get page(): PageKey {
    return this.currentPage;
  }

  navigate(page: PageKey) {
    if (page === this.currentPage) return;
    this.history.push(page);
    this.currentPage = page;
    this.listeners.forEach((fn) => fn(page));
  }

  back() {
    if (this.history.length > 1) {
      this.history.pop();
      this.currentPage = this.history[this.history.length - 1];
      this.listeners.forEach((fn) => fn(this.currentPage));
    }
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }
}

export const router = new Router();
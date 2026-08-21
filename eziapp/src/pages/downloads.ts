// 下载中心：原版安装与 Mod/整合包/资源内容目录。
import { bridge } from '../bridge';
import { router, type PageKey } from '../router';
import { store, type InstanceInfo, type VersionInfo } from '../store';
import { registerPageCleanup, toast, flyToTasks } from '../ui';
import { errorMessage, escapeHtml, formatCount } from './common';

export type DownloadCategory = 'vanilla' | 'mods' | 'modpacks' | 'datapacks' | 'resourcepacks' | 'shaders';

interface CatalogEntry {
  name: string;
  author?: string;
  downloads?: number;
  id?: string | number;
  slug?: string;
  source?: string;
  description?: string;
  tags?: string[];
  updated?: string;
}

interface CatalogState {
  query: string;
  source: string;
  gameVersion: string;
  rows: CatalogEntry[];
}

const categoryMeta: Record<DownloadCategory, { label: string; icon: string; route: PageKey }> = {
  vanilla: { label: '原版游戏', icon: '🎮', route: 'vanilla' },
  mods: { label: '模组', icon: '🧩', route: 'mods' },
  modpacks: { label: '整合包', icon: '📚', route: 'modpacks' },
  datapacks: { label: '数据包', icon: '🗂️', route: 'datapacks' },
  resourcepacks: { label: '资源包', icon: '🖼️', route: 'resourcepacks' },
  shaders: { label: '光影包', icon: '✨', route: 'shaders' },
};

const catalogConfig: Record<Exclude<DownloadCategory, 'vanilla'>, {
  search: string;
  install: string;
  noun: string;
  placeholder: string;
}> = {
  mods: { search: 'search_mods', install: 'install_mod', noun: '模组', placeholder: '搜索模组名称，例如 Sodium' },
  modpacks: { search: 'search_modpacks', install: 'install_modpack', noun: '整合包', placeholder: '搜索整合包名称，例如 All the Mods' },
  datapacks: { search: 'search_datapacks', install: 'install_datapack', noun: '数据包', placeholder: '搜索数据包名称' },
  resourcepacks: { search: 'search_resourcepacks', install: 'install_resourcepack', noun: '资源包', placeholder: '搜索资源包名称' },
  shaders: { search: 'search_shaders', install: 'install_shader', noun: '光影包', placeholder: '搜索光影包名称，例如 Complementary' },
};

const catalogState: Record<Exclude<DownloadCategory, 'vanilla'>, CatalogState> = {
  mods: { query: '', source: 'Modrinth', gameVersion: '', rows: [] },
  modpacks: { query: '', source: 'Modrinth', gameVersion: '', rows: [] },
  datapacks: { query: '', source: 'Modrinth', gameVersion: '', rows: [] },
  resourcepacks: { query: '', source: 'Modrinth', gameVersion: '', rows: [] },
  shaders: { query: '', source: 'Modrinth', gameVersion: '', rows: [] },
};

let activeCategory: DownloadCategory = 'vanilla';
let renderToken = 0;

export async function renderDownloadPage(container: HTMLElement, requestedCategory: DownloadCategory = activeCategory) {
  activeCategory = requestedCategory;
  const token = ++renderToken;
  registerPageCleanup(() => {
    if (token === renderToken) renderToken += 1;
  });

  renderShell(container, requestedCategory);
  await loadBaseData(token);
  if (token !== renderToken || !container.isConnected) return;
  renderShell(container, requestedCategory);
}

function renderShell(container: HTMLElement, category: DownloadCategory) {
  const categoryTabs = (Object.keys(categoryMeta) as DownloadCategory[]).map((key) => {
    const meta = categoryMeta[key];
    return `<button class="tab ${key === category ? 'active' : ''}" data-download-route="${key}">${meta.icon} ${meta.label}</button>`;
  }).join('');

  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:16px;max-width:1120px">
      <div class="tabs" aria-label="下载分类">${categoryTabs}</div>
      <div id="download-panel"></div>
    </div>
  `;

  container.querySelectorAll<HTMLButtonElement>('[data-download-route]').forEach((button) => {
    button.addEventListener('click', () => {
      const next = button.dataset.downloadRoute as DownloadCategory;
      router.navigate(categoryMeta[next].route);
    });
  });

  const panel = container.querySelector<HTMLElement>('#download-panel');
  if (!panel) return;
  if (category === 'vanilla') renderVanilla(panel);
  else renderCatalog(panel, category);
}

async function loadBaseData(token: number) {
  const requests: Promise<void>[] = [];
  if (store.instances.length === 0) {
    requests.push(bridge.call<InstanceInfo[]>('get_instances').then((rows) => {
      if (token === renderToken) store.setInstances(rows);
    }).catch(() => undefined));
  }
  if (store.versionList.length === 0) {
    requests.push(bridge.call<VersionInfo[]>('get_version_list').then((rows) => {
      if (token === renderToken) store.setVersionList(rows);
    }).catch(() => undefined));
  }
  await Promise.all(requests);
}

function instanceOptions(): string {
  const instances = store.instances.length ? store.instances : [{ name: 'default' } as InstanceInfo];
  return instances.map((instance) => `<option value="${escapeHtml(instance.name)}">${escapeHtml(instance.name)}</option>`).join('');
}

function versionOptions(selected = ''): string {
  return store.versionList.map((version) => {
    const isSelected = version.version === selected ? 'selected' : '';
    return `<option value="${escapeHtml(version.version)}" ${isSelected}>${escapeHtml(version.version)}${version.type ? ` (${escapeHtml(version.type)})` : ''}</option>`;
  }).join('');
}

function renderVanilla(panel: HTMLElement) {
  const selectedVersion = store.currentVersion || store.versionList[0]?.version || '';
  panel.innerHTML = `
    <div class="card">
      <div class="card-header">🎮 安装 Minecraft</div>
      <div style="font-size:13px;color:var(--text-secondary);margin-bottom:16px">选择游戏版本和加载器，任务会在后台下载并显示在下载任务中。</div>
      <div class="form-row" style="align-items:flex-end">
        <div class="form-group" style="flex:2;min-width:220px">
          <label class="form-label">Minecraft 版本</label>
          <select class="select" id="vanilla-version" style="width:100%">${versionOptions(selectedVersion) || '<option value="">暂无本地版本清单</option>'}</select>
        </div>
        <div class="form-group" style="min-width:150px">
          <label class="form-label">版本类型</label>
          <select class="select" id="vanilla-type" style="width:100%">
            <option value="all">全部</option>
            <option value="release">正式版</option>
            <option value="snapshot">快照版</option>
          </select>
        </div>
        <button class="btn" id="vanilla-refresh">↻ 刷新清单</button>
      </div>
      <div class="form-row" style="align-items:flex-end">
        <div class="form-group" style="flex:1;min-width:160px">
          <label class="form-label">实例</label>
          <select class="select" id="vanilla-instance" style="width:100%">${instanceOptions()}</select>
        </div>
        <div class="form-group" style="flex:1;min-width:160px">
          <label class="form-label">加载器</label>
          <select class="select" id="vanilla-loader" style="width:100%">
            <option value="无">原版</option>
            <option value="Fabric">Fabric</option>
            <option value="Forge">Forge</option>
            <option value="NeoForge">NeoForge</option>
            <option value="Quilt">Quilt</option>
          </select>
        </div>
        <div class="form-group" style="flex:1;min-width:180px">
          <label class="form-label">加载器版本</label>
          <select class="select" id="vanilla-loader-version" style="width:100%" disabled><option value="">自动选择</option></select>
        </div>
      </div>
      <div class="form-row" style="margin-bottom:16px">
        <label style="display:flex;align-items:center;gap:6px;font-size:13px"><input type="checkbox" id="vanilla-optifine"> 同时安装 OptiFine</label>
        <label style="display:flex;align-items:center;gap:6px;font-size:13px"><input type="checkbox" id="vanilla-liteloader"> 同时安装 LiteLoader</label>
      </div>
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <button class="btn btn-primary" id="vanilla-install" ${selectedVersion ? '' : 'disabled'}>⬇ 安装游戏</button>
        <span id="vanilla-status" style="font-size:12px;color:var(--text-secondary)"></span>
      </div>
    </div>
  `;

  const versionSelect = panel.querySelector<HTMLSelectElement>('#vanilla-version')!;
  const typeSelect = panel.querySelector<HTMLSelectElement>('#vanilla-type')!;
  const loaderSelect = panel.querySelector<HTMLSelectElement>('#vanilla-loader')!;
  const loaderVersionSelect = panel.querySelector<HTMLSelectElement>('#vanilla-loader-version')!;
  const installButton = panel.querySelector<HTMLButtonElement>('#vanilla-install')!;
  const status = panel.querySelector<HTMLElement>('#vanilla-status')!;

  function populateVersions() {
    const previous = versionSelect.value;
    const type = typeSelect.value;
    const rows = type === 'all' ? store.versionList : store.versionList.filter((row) => row.type === type);
    versionSelect.innerHTML = rows.map((version) => `<option value="${escapeHtml(version.version)}">${escapeHtml(version.version)}${version.type ? ` (${escapeHtml(version.type)})` : ''}</option>`).join('') || '<option value="">没有匹配版本</option>';
    if (rows.some((row) => row.version === previous)) versionSelect.value = previous;
    installButton.disabled = !versionSelect.value;
  }

  async function refreshLoaderVersions() {
    const version = versionSelect.value;
    const loader = loaderSelect.value;
    loaderVersionSelect.disabled = true;
    loaderVersionSelect.innerHTML = '<option value="">自动选择</option>';
    if (!version || loader === '无') return;
    status.textContent = '正在读取加载器版本…';
    try {
      const rows = await bridge.call<Array<{ version?: string; id?: string; stable?: boolean }>>('list_loader_versions', { mc_version: version, loader });
      const values = rows.map((row) => String(row.version || row.id || '')).filter(Boolean);
      loaderVersionSelect.innerHTML = '<option value="">自动选择</option>' + values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
      loaderVersionSelect.disabled = false;
      status.textContent = values.length ? '' : '未找到该版本的加载器，将由后端自动选择。';
    } catch (error) {
      status.textContent = `读取加载器版本失败：${errorMessage(error, '未知错误')}`;
    }
  }

  typeSelect.addEventListener('change', populateVersions);
  versionSelect.addEventListener('change', () => {
    store.currentVersion = versionSelect.value;
    void refreshLoaderVersions();
  });
  loaderSelect.addEventListener('change', () => void refreshLoaderVersions());
  panel.querySelector<HTMLButtonElement>('#vanilla-refresh')!.addEventListener('click', async () => {
    status.textContent = '正在刷新官方版本清单…';
    try {
      const rows = await bridge.call<VersionInfo[]>('fetch_version_list');
      store.setVersionList(rows);
      populateVersions();
      status.textContent = `已更新 ${rows.length} 个版本。`;
    } catch (error) {
      status.textContent = `刷新失败：${errorMessage(error, '未知错误')}`;
    }
  });
  installButton.addEventListener('click', async () => {
    const version = versionSelect.value;
    if (!version) return;
    installButton.disabled = true;
    status.textContent = '正在创建下载任务…';
    try {
      await bridge.call<string>('install_game', {
        version,
        loader: loaderSelect.value,
        loader_version: loaderVersionSelect.value,
        instance: panel.querySelector<HTMLSelectElement>('#vanilla-instance')!.value,
        extra: {
          optifine: panel.querySelector<HTMLInputElement>('#vanilla-optifine')!.checked,
          liteloader: panel.querySelector<HTMLInputElement>('#vanilla-liteloader')!.checked,
        },
      });
      toast(`${version} 已加入下载任务`, 'success');
      await flyToTasks(installButton, version, '#2FA36B');
      router.navigate('tasks');
    } catch (error) {
      toast(errorMessage(error, '创建安装任务失败'), 'error');
      status.textContent = '';
      installButton.disabled = false;
    }
  });
}

function renderCatalog(panel: HTMLElement, category: Exclude<DownloadCategory, 'vanilla'>) {
  const config = catalogConfig[category];
  const state = catalogState[category];
  panel.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div class="card-header">${categoryMeta[category].icon} 浏览${config.noun}</div>
      <div class="form-row" style="align-items:flex-end">
        <div class="form-group" style="flex:1;min-width:230px">
          <label class="form-label">关键词</label>
          <input class="input" id="catalog-query" value="${escapeHtml(state.query)}" placeholder="${escapeHtml(config.placeholder)}" style="width:100%">
        </div>
        <div class="form-group" style="min-width:130px">
          <label class="form-label">来源</label>
          <select class="select" id="catalog-source" style="width:100%">
            <option value="Modrinth" ${state.source === 'Modrinth' ? 'selected' : ''}>Modrinth</option>
            <option value="CurseForge" ${state.source === 'CurseForge' ? 'selected' : ''}>CurseForge</option>
          </select>
        </div>
        <div class="form-group" style="min-width:140px">
          <label class="form-label">游戏版本</label>
          <select class="select" id="catalog-version" style="width:100%">
            <option value="">不限</option>
            ${versionOptions(state.gameVersion)}
          </select>
        </div>
        <button class="btn btn-primary" id="catalog-search">🔎 搜索</button>
      </div>
      <div id="catalog-status" style="font-size:12px;color:var(--text-secondary)"></div>
    </div>
    <div id="catalog-results">${renderCatalogResults(state.rows, config.noun)}</div>
  `;

  const queryInput = panel.querySelector<HTMLInputElement>('#catalog-query')!;
  const sourceSelect = panel.querySelector<HTMLSelectElement>('#catalog-source')!;
  const versionSelect = panel.querySelector<HTMLSelectElement>('#catalog-version')!;
  const searchButton = panel.querySelector<HTMLButtonElement>('#catalog-search')!;
  const status = panel.querySelector<HTMLElement>('#catalog-status')!;
  const results = panel.querySelector<HTMLElement>('#catalog-results')!;
  let requestNumber = 0;

  const bindResultActions = () => {
    results.querySelectorAll<HTMLButtonElement>('[data-install-index]').forEach((button) => {
      button.addEventListener('click', async () => {
        const item = state.rows[Number(button.dataset.installIndex)];
        if (!item) return;
        button.disabled = true;
        try {
          const instance = results.querySelector<HTMLSelectElement>('#catalog-install-instance')?.value
            || store.instances[0]?.name
            || 'default';
          const extra = { ...item, source: item.source || sourceSelect.value, instance, game_version: versionSelect.value };
          if (category === 'modpacks') {
            await bridge.call<string>(config.install, { name: item.name, source: extra.source, extra });
          } else {
            await bridge.call<string>(config.install, { name: item.name, instance, extra });
          }
          toast(`${item.name} 已加入下载任务`, 'success');
          await flyToTasks(button, item.name);
          router.navigate('tasks');
        } catch (error) {
          toast(errorMessage(error, `安装${config.noun}失败`), 'error');
          button.disabled = false;
        }
      });
    });
  };

  const search = async () => {
    state.query = queryInput.value.trim();
    state.source = sourceSelect.value;
    state.gameVersion = versionSelect.value;
    const request = ++requestNumber;
    searchButton.disabled = true;
    status.textContent = '正在搜索…';
    try {
      const rows = await bridge.call<CatalogEntry[]>(config.search, {
        query: state.query,
        source: state.source,
        extra: { game_version: state.gameVersion },
      });
      if (request !== requestNumber || !panel.isConnected) return;
      state.rows = Array.isArray(rows) ? rows : [];
      results.innerHTML = renderCatalogResults(state.rows, config.noun);
      bindResultActions();
      status.textContent = state.rows.length ? `找到 ${state.rows.length} 个结果。` : '没有找到匹配结果。';
    } catch (error) {
      if (request !== requestNumber || !panel.isConnected) return;
      status.textContent = `搜索失败：${errorMessage(error, '未知错误')}`;
      results.innerHTML = renderCatalogResults([], config.noun, '暂时无法连接目录服务。');
    } finally {
      if (request === requestNumber) searchButton.disabled = false;
    }
  };

  searchButton.addEventListener('click', () => void search());
  queryInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') void search();
  });
  bindResultActions();
}

function renderCatalogResults(rows: CatalogEntry[], noun: string, emptyText?: string): string {
  if (!rows.length) {
    return `<div class="empty-state"><div class="empty-state-icon">🔎</div><div>${escapeHtml(emptyText || `输入关键词以搜索${noun}`)}</div></div>`;
  }
  return `
    <div class="form-row" style="justify-content:space-between;margin-bottom:10px">
      <span style="font-size:12px;color:var(--text-secondary)">安装到</span>
      <select class="select" id="catalog-install-instance" style="min-width:180px">${instanceOptions()}</select>
    </div>
    <div class="grid-list">
      ${rows.map((item, index) => `
        <div class="grid-item">
          <div class="grid-item-title">${escapeHtml(item.name)}</div>
          <div class="grid-item-meta">
            <span>${escapeHtml(item.author || item.source || '未知作者')}</span>
            <span>⬇ ${formatCount(item.downloads)}</span>
            ${item.source ? `<span>${escapeHtml(item.source)}</span>` : ''}
          </div>
          ${item.description ? `<div style="font-size:12px;line-height:1.5;color:var(--text-secondary);margin-top:8px">${escapeHtml(item.description)}</div>` : ''}
          ${item.tags?.length ? `<div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:8px">${item.tags.slice(0, 4).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join('')}</div>` : ''}
          <div class="grid-item-actions"><button class="btn btn-sm btn-primary" data-install-index="${index}">⬇ 安装</button></div>
        </div>
      `).join('')}
    </div>
  `;
}

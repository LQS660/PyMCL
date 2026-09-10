import { bridge } from '../bridge';
import { router, type PageKey } from '../router';
import { store, type InstanceInfo, type VersionInfo } from '../store';
import { confirmDialog, inputDialog, registerPageCleanup, showSkeleton, toast, flyToTasks } from '../ui';
import { errorMessage, escapeHtml, formatDownloads } from './common';
import { pickCatalogFile } from './dialogs';

export type DownloadCategory = 'vanilla' | 'mods' | 'modpacks' | 'datapacks' | 'resourcepacks' | 'shaders' | 'worlds';

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
  icon_url?: string;
  filename?: string;
  enabled?: boolean;
  url?: string;
  path?: string;
}

const categoryMeta: Record<DownloadCategory, { label: string; icon: string; route: PageKey }> = {
  vanilla: { label: '原版游戏', icon: '🎮', route: 'vanilla' },
  mods: { label: 'Mod', icon: '🧩', route: 'mods-catalog' },
  modpacks: { label: '整合包', icon: '📚', route: 'modpacks' },
  datapacks: { label: '数据包', icon: '🗂️', route: 'datapacks' },
  resourcepacks: { label: '资源包', icon: '🖼️', route: 'resourcepacks' },
  shaders: { label: '光影包', icon: '✨', route: 'shaders' },
  worlds: { label: '世界', icon: '🌍', route: 'worlds' },
};

const catalogConfig: Record<Exclude<DownloadCategory, 'vanilla'>, {
  search: string; install: string; list: string; del: string; kind: string; noun: string; placeholder: string; types: string[];
}> = {
  mods: { search: 'search_mods', install: 'install_mod', list: 'get_installed_mods', del: 'delete_mod', kind: 'mod', noun: '模组', placeholder: '搜索模组，例如 Sodium', types: ['全部', '优化', '科技', '魔法', '冒险'] },
  modpacks: { search: 'search_modpacks', install: 'install_modpack', list: 'get_installed_modpacks', del: 'delete_modpack', kind: 'modpack', noun: '整合包', placeholder: '搜索整合包', types: ['全部', '生存', '空岛', '科技', '魔法'] },
  datapacks: { search: 'search_datapacks', install: 'install_datapack', list: 'get_installed_datapacks', del: 'delete_datapack', kind: 'datapack', noun: '数据包', placeholder: '搜索数据包', types: ['全部', '生存', '冒险', '装饰'] },
  resourcepacks: { search: 'search_resourcepacks', install: 'install_resourcepack', list: 'get_installed_resourcepacks', del: 'delete_resourcepack', kind: 'resourcepack', noun: '资源包', placeholder: '搜索资源包', types: ['全部', '16x', '32x', '64x', '写实'] },
  shaders: { search: 'search_shaders', install: 'install_shader', list: 'get_installed_shaders', del: 'delete_shader', kind: 'shader', noun: '光影包', placeholder: '搜索光影', types: ['全部', '写实', '卡通', '高性能', '光追'] },
  worlds: { search: 'search_worlds', install: 'install_world', list: 'list_saves', del: 'delete_save', kind: 'world', noun: '世界', placeholder: '搜索世界', types: ['全部', '生存', '冒险', '创造'] },
};

const catalogState: Record<string, { query: string; source: string; gameVersion: string; type: string; rows: CatalogEntry[]; mode: 'search' | 'installed' | 'favs' }> = {};
function stateOf(cat: string) {
  return catalogState[cat] ||= { query: '', source: cat === 'worlds' ? 'CurseForge' : '全部', gameVersion: '', type: '全部', rows: [], mode: 'search' };
}

let activeCategory: DownloadCategory = 'vanilla';
let renderToken = 0;

/** 数据包装进存档：等安装任务成功后调用 install_datapack_into_save。 */
function installIntoSaveAfter(taskId: string, instance: string, extra: Record<string, unknown>, saveName: string) {
  const unsub = bridge.subscribe('finished', (data: any) => {
    if (String(data.task_id || '') !== taskId) return;
    unsub();
    if (!data.success) return;
    void (async () => {
      try {
        const packs = await bridge.call<string[]>('get_installed_datapacks', { instance });
        const want = String(extra.filename || '').toLowerCase();
        const hit = (packs || []).find((p) => p.toLowerCase() === want)
          || (packs || []).find((p) => want && p.toLowerCase().includes(want.replace(/\.(zip|jar)$/i, '')))
          || (packs || [])[packs.length - 1];
        if (!hit) return;
        await bridge.call('install_datapack_into_save', { instance, filename: hit, save_name: saveName });
        toast(`已把数据包装进存档「${saveName}」`, 'success');
      } catch (e) { toast(errorMessage(e, '装进存档失败'), 'error'); }
    })();
  });
}

/** 安装成功后自动启动（对齐 Qt 版 queue_launch_after/_launch_installed 的版本挑选逻辑）。 */
function queueLaunchAfter(taskId: string, instance: string, version: string, loader: string) {
  const unsub = bridge.subscribe('finished', (data: any) => {
    if (String(data.task_id || '') !== taskId) return;
    unsub();
    if (!data.success) return;
    void (async () => {
      try {
        const ids = await bridge.call<string[]>('get_installed_versions', { instance });
        const pick = ids.includes(version) ? version
          : ids.find((i) => version && i.includes(version)) || '';
        if (!pick) return;
        store.currentInstance = instance;
        store.currentVersion = pick;
        store.notify();
        toast(`安装完成，正在启动 ${pick}`, 'success');
        router.navigate('launch');
        await bridge.call('launch_game', {
          instance, version: pick,
          account: store.currentAccount || '离线模式',
          username: store.currentUsername || 'Player',
          memory_mb: store.currentMemory || 4096,
          width: store.currentWidth || 854, height: store.currentHeight || 480,
          java: store.currentJava || '自动选择',
        });
      } catch (e) { toast(errorMessage(e, '自动启动失败'), 'error'); }
    })();
  });
}

export async function renderDownloadPage(container: HTMLElement, requestedCategory: DownloadCategory = activeCategory) {
  activeCategory = requestedCategory;
  const token = ++renderToken;
  registerPageCleanup(() => { if (token === renderToken) renderToken += 1; });
  renderShell(container, requestedCategory);
  await loadBaseData(token);
  if (token !== renderToken || !container.isConnected) return;
  renderShell(container, requestedCategory);
}

function renderShell(container: HTMLElement, category: DownloadCategory) {
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px;max-width:1180px">
      <div class="tabs">${(Object.keys(categoryMeta) as DownloadCategory[]).map((key) =>
        `<button class="tab ${key === category ? 'active' : ''}" data-download-route="${key}">${categoryMeta[key].icon} ${categoryMeta[key].label}</button>`).join('')}</div>
      <div id="download-panel"></div>
    </div>`;
  container.querySelectorAll<HTMLButtonElement>('[data-download-route]').forEach((button) => {
    button.addEventListener('click', () => router.navigate(categoryMeta[button.dataset.downloadRoute as DownloadCategory].route));
  });
  const panel = container.querySelector<HTMLElement>('#download-panel');
  if (!panel) return;
  if (category === 'vanilla') renderVanilla(panel);
  else renderCatalog(panel, category);
}

async function loadBaseData(token: number) {
  const requests: Promise<void>[] = [];
  if (!store.instances.length) requests.push(bridge.call<InstanceInfo[]>('get_instances').then((rows) => { if (token === renderToken) store.setInstances(rows); }).catch(() => undefined));
  if (!store.versionList.length) requests.push(bridge.call<VersionInfo[]>('get_version_list').then((rows) => { if (token === renderToken) store.setVersionList(rows); }).catch(() => undefined));
  await Promise.all(requests);
}

function instanceOptions(): string {
  return (store.instances.length ? store.instances : [{ name: 'default' } as InstanceInfo])
    .map((i) => `<option value="${escapeHtml(i.name)}">${escapeHtml(i.name)}</option>`).join('');
}

function renderVanilla(panel: HTMLElement) {
  panel.innerHTML = `
    <div class="card" style="margin-bottom:14px">
      <div class="card-header">安装 Minecraft</div>
      <div class="form-row" style="align-items:flex-end">
        <div class="form-group" style="flex:2;min-width:200px"><label class="form-label">搜索</label><input class="input" id="vanilla-q" placeholder="1.20.1 / 快照 / 远古" style="width:100%"></div>
        <div class="form-group"><label class="form-label">类型</label>
          <select class="select" id="vanilla-type"><option value="all">全部</option><option value="release">正式版</option><option value="snapshot">快照</option><option value="old">远古</option></select>
        </div>
        <div class="form-group"><label class="form-label">实例</label><select class="select" id="vanilla-instance">${instanceOptions()}</select></div>
        <div class="form-group"><label class="form-label">加载器</label>
          <select class="select" id="vanilla-loader"><option value="无">原版</option><option>Fabric</option><option>Forge</option><option>NeoForge</option><option>Quilt</option></select>
        </div>
        <div class="form-group"><label class="form-label">加载器版本</label><select class="select" id="vanilla-loader-version" disabled><option value="">自动选择</option></select></div>
        <button class="btn" id="vanilla-refresh">刷新清单</button>
      </div>
      <div class="form-row"><label class="check-row"><input type="checkbox" id="vanilla-optifine"> OptiFine</label><label class="check-row"><input type="checkbox" id="vanilla-liteloader"> LiteLoader</label><label class="check-row" title="重装时已下载过的资源文件不再校验"><input type="checkbox" id="vanilla-skip-assets" ${store.mergedSettings().skip_assets ? 'checked' : ''}> 跳过资源校验</label><label class="check-row" title="安装成功后自动启动"><input type="checkbox" id="vanilla-launch-after" checked> 完成后启动</label><span id="vanilla-status" style="font-size:12px;color:var(--text-secondary)"></span></div>
    </div>
    <div class="grid-list" id="vanilla-grid"></div>
    <button class="btn" id="vanilla-more" style="display:none">加载更多</button>`;

  const q = panel.querySelector<HTMLInputElement>('#vanilla-q')!;
  const type = panel.querySelector<HTMLSelectElement>('#vanilla-type')!;
  const loader = panel.querySelector<HTMLSelectElement>('#vanilla-loader')!;
  const loaderVer = panel.querySelector<HTMLSelectElement>('#vanilla-loader-version')!;
  const status = panel.querySelector('#vanilla-status')!;
  const grid = panel.querySelector('#vanilla-grid')!;
  let limit = 24;

  const filtered = () => {
    const text = q.value.trim().toLowerCase();
    const t = type.value;
    return store.versionList.filter((v) => {
      if (t === 'release' && v.type !== 'release') return false;
      if (t === 'snapshot' && v.type !== 'snapshot') return false;
      if (t === 'old' && !String(v.type).startsWith('old')) return false;
      return !text || v.version.toLowerCase().includes(text);
    });
  };
  const paint = () => {
    const rows = filtered();
    const show = rows.slice(0, limit);
    const colors: Record<string, string> = { release: '#2FA36B', snapshot: '#E8862E', old_alpha: '#7C5CD6', old_beta: '#7C5CD6' };
    grid.innerHTML = show.map((v) => {
      const tint = colors[v.type] || '#888888';
      return `<div class="grid-item"><div style="display:flex;justify-content:space-between;gap:8px"><div class="grid-item-title">${escapeHtml(v.version)}</div><span class="tag" style="color:${tint}">${escapeHtml(v.type)}</span></div><div class="grid-item-meta">${escapeHtml(v.date || '')}</div><div class="grid-item-actions"><button class="btn btn-sm btn-primary" data-install="${escapeHtml(v.version)}">安装</button></div></div>`;
    }).join('') || '<div class="empty-state"><div>没有匹配版本</div></div>';
    panel.querySelector<HTMLButtonElement>('#vanilla-more')!.style.display = rows.length > limit ? '' : 'none';
    grid.querySelectorAll<HTMLButtonElement>('[data-install]').forEach((btn) => btn.addEventListener('click', () => void install(btn.dataset.install || '', btn)));
  };
  const refreshLoader = async () => {
    loaderVer.disabled = true;
    loaderVer.innerHTML = '<option value="">自动选择</option>';
    if (loader.value === '无') return;
    try {
      const first = filtered()[0]?.version;
      if (!first) return;
      const rows = await bridge.call<any[]>('list_loader_versions', { mc_version: first, loader: loader.value });
      loaderVer.innerHTML = '<option value="">自动选择</option>' + (rows || []).map((r) => `<option>${escapeHtml(r.version || r.id || '')}</option>`).join('');
      loaderVer.disabled = false;
    } catch { /* ignore */ }
  };
  const install = async (version: string, btn: HTMLElement) => {
    const instance = panel.querySelector<HTMLSelectElement>('#vanilla-instance')!.value;
    const skipAssets = panel.querySelector<HTMLInputElement>('#vanilla-skip-assets')!.checked;
    const launchAfter = panel.querySelector<HTMLInputElement>('#vanilla-launch-after')!.checked;
    // 加载器版本按所点的 MC 版本取（对齐 Qt 版 InstallWizardDialog），页面顶部的下拉只是预选
    let loaderVersion = loaderVer.value;
    if (loader.value !== '无') {
      try {
        const rows = await bridge.call<any[]>('list_loader_versions', { mc_version: version, loader: loader.value });
        const options = (rows || []).map((r) => String(r.version || r.id || '')).filter(Boolean);
        if (options.length) {
          const { formDialog } = await import('../ui');
          const picked = await formDialog(`安装 ${version} + ${loader.value}`, [{
            id: 'lv', label: '加载器版本', type: 'select',
            value: loaderVersion && options.includes(loaderVersion) ? loaderVersion : '',
            options: [{ value: '', label: '自动选择（最新）' }, ...options.map((o) => ({ value: o, label: o }))],
          }]);
          if (picked === null) return;
          loaderVersion = picked.lv || '';
        }
      } catch { /* 拉取失败就用页面上的选择 */ }
    }
    try {
      const taskId = await bridge.call<string>('install_game', {
        version, loader: loader.value, loader_version: loaderVersion,
        instance,
        extra: { optifine: panel.querySelector<HTMLInputElement>('#vanilla-optifine')!.checked, liteloader: panel.querySelector<HTMLInputElement>('#vanilla-liteloader')!.checked },
      });
      // skip_assets 是后端持久键：顺手落盘，下次安装仍生效
      void bridge.call('save_settings', { skip_assets: skipAssets }).catch(() => undefined);
      store.setLocalPrefs({ skip_assets: skipAssets });
      toast(`${version} 已加入下载任务`, 'success');
      await flyToTasks(btn, version, '#2FA36B');
      if (launchAfter) queueLaunchAfter(taskId, instance, version, loader.value);
      router.navigate('tasks');
    } catch (e) { toast(errorMessage(e, '创建安装任务失败'), 'error'); }
  };
  q.addEventListener('input', () => { limit = 24; paint(); });
  type.addEventListener('change', () => { limit = 24; paint(); });
  loader.addEventListener('change', () => void refreshLoader());
  panel.querySelector('#vanilla-more')?.addEventListener('click', () => { limit += 24; paint(); });
  panel.querySelector('#vanilla-refresh')?.addEventListener('click', async () => {
    status.textContent = '刷新中…';
    try {
      store.setVersionList(await bridge.call<VersionInfo[]>('fetch_version_list'));
      paint();
      status.textContent = `已更新 ${store.versionList.length} 个版本`;
    } catch (e) { status.textContent = errorMessage(e, '刷新失败'); }
  });
  paint();
}

function renderCatalog(panel: HTMLElement, category: Exclude<DownloadCategory, 'vanilla'>) {
  const config = catalogConfig[category];
  const state = stateOf(category);
  const sources = category === 'worlds'
    ? '<option>CurseForge</option>'
    : `<option ${state.source === '全部' ? 'selected' : ''}>全部</option><option ${state.source === 'Modrinth' ? 'selected' : ''}>Modrinth</option><option ${state.source === 'CurseForge' ? 'selected' : ''}>CurseForge</option>`;
  panel.innerHTML = `
    <div class="card" style="margin-bottom:14px">
      <div class="card-header">${categoryMeta[category].icon} 浏览${config.noun}</div>
      <div class="form-row" style="align-items:flex-end">
        <div class="form-group" style="flex:1;min-width:200px"><label class="form-label">名称</label><input class="input" id="catalog-query" value="${escapeHtml(state.query)}" placeholder="${escapeHtml(config.placeholder)}" style="width:100%"></div>
        <div class="form-group"><label class="form-label">来源</label><select class="select" id="catalog-source">${sources}</select></div>
        <div class="form-group"><label class="form-label">版本</label><input class="input" id="catalog-version" value="${escapeHtml(state.gameVersion)}" placeholder="全部 / 1.20.1" style="width:120px"></div>
        <div class="form-group"><label class="form-label">类型</label><select class="select" id="catalog-type">${config.types.map((t) => `<option ${t === state.type ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
        <div class="form-group"><label class="form-label">安装到</label><select class="select" id="catalog-install-instance">${instanceOptions()}</select></div>
        <button class="btn btn-primary" id="catalog-search">搜索</button>
        <button class="btn" id="catalog-reset">重置</button>
      </div>
      <div class="form-row">
        <button class="tab ${state.mode === 'search' ? 'active' : ''}" data-mode="search">浏览</button>
        <button class="tab ${state.mode === 'installed' ? 'active' : ''}" data-mode="installed">已安装</button>
        <button class="tab ${state.mode === 'favs' ? 'active' : ''}" data-mode="favs">收藏</button>
        ${category === 'mods' ? '<select class="select" id="catalog-mods-target" style="display:none;max-width:190px"></select><button class="btn btn-sm" id="catalog-update" style="display:none">检查更新</button>' : ''}
        <button class="btn btn-sm" id="catalog-link">从链接安装</button>
        <button class="btn btn-sm" id="catalog-local">导入本地</button>
        <span id="catalog-status" style="font-size:12px;color:var(--text-secondary)"></span>
      </div>
    </div>
    <div id="catalog-results"></div>`;

  const queryInput = panel.querySelector<HTMLInputElement>('#catalog-query')!;
  const sourceSelect = panel.querySelector<HTMLSelectElement>('#catalog-source')!;
  const versionInput = panel.querySelector<HTMLInputElement>('#catalog-version')!;
  const typeSelect = panel.querySelector<HTMLSelectElement>('#catalog-type')!;
  const instSelect = panel.querySelector<HTMLSelectElement>('#catalog-install-instance')!;
  const status = panel.querySelector('#catalog-status')!;
  const results = panel.querySelector<HTMLElement>('#catalog-results')!;
  let requestNumber = 0;

  // 剪贴板里的 Modrinth/CurseForge 链接：自动填入搜索框（对齐 Qt 版 showEvent）
  if (store.pendingClipLink && !state.query) {
    queryInput.value = store.pendingClipLink;
    store.pendingClipLink = '';
    state.query = queryInput.value;
  }

  const doInstall = async (item: CatalogEntry, btn: HTMLElement) => {
    const instance = instSelect.value || 'default';
    let extra: Record<string, unknown> = { ...item, source: item.source || sourceSelect.value, instance, game_version: versionInput.value };
    if (item.slug || item.id) {
      const picked = await pickCatalogFile(extra, config.kind, versionInput.value);
      if (!picked) return;
      extra = picked;
    }
    // 数据包可选「装进存档」：装完后写进所选存档的 datapacks（对齐 Qt 版 _maybe_datapack_save）
    let saveName = '';
    if (category === 'datapacks') {
      try {
        const saves = await bridge.call<any[]>('list_saves', { instance });
        const names = (Array.isArray(saves) ? saves : []).map((s) => String(s.name || '')).filter(Boolean);
        if (names.length) {
          const { formDialog } = await import('../ui');
          const picked = await formDialog('装进存档（可选）', [{
            id: 'save', label: '选择存档', type: 'select', value: '',
            options: [{ value: '', label: '不装进存档，只放到 datapacks 目录' }, ...names.map((n) => ({ value: n, label: n }))],
          }]);
          if (picked === null) return;
          saveName = (picked.save || '').trim();
        }
      } catch { /* 读存档失败就只装到目录 */ }
    }
    try {
      let taskId = '';
      if (category === 'modpacks') taskId = await bridge.call<string>(config.install, { name: extra.name, source: extra.source, extra });
      else taskId = await bridge.call<string>(config.install, { name: extra.name, instance, extra });
      toast(`${item.name} 已加入下载任务`, 'success');
      await flyToTasks(btn, String(item.name || ''));
      if (saveName && taskId) installIntoSaveAfter(taskId, instance, extra, saveName);
      router.navigate('tasks');
    } catch (e) { toast(errorMessage(e, `安装${config.noun}失败`), 'error'); }
  };

  const paintSearch = (rows: CatalogEntry[]) => {
    if (!rows.length) {
      results.innerHTML = `<div class="empty-state"><div class="empty-state-icon">🔎</div><div>没有找到匹配${config.noun}</div></div>`;
      return;
    }
    results.innerHTML = rows.map((item, index) => `
      <div class="catalog-row">
        ${item.icon_url ? `<img class="thumb" src="${escapeHtml(item.icon_url)}" alt="">` : `<div class="thumb">${escapeHtml((item.name || '?').slice(0, 1))}</div>`}
        <div style="flex:1;min-width:0">
          <div class="grid-item-title">${escapeHtml(item.name)} ${(item.tags || []).slice(0, 3).map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join(' ')}</div>
          <div class="grid-item-meta"><span>${escapeHtml(item.author || item.source || '')}</span><span>⬇ ${formatDownloads(item.downloads)}</span><span>${escapeHtml(item.updated || '')}</span></div>
          ${item.description ? `<div style="font-size:12px;color:var(--text-secondary);margin-top:4px">${escapeHtml(item.description.slice(0, 110))}</div>` : ''}
        </div>
        <button class="btn btn-sm" data-fav="${index}">收藏</button>
        <button class="btn btn-sm btn-primary" data-install-index="${index}">选择版本</button>
      </div>`).join('');
    results.querySelectorAll<HTMLButtonElement>('[data-install-index]').forEach((btn) => btn.addEventListener('click', () => void doInstall(state.rows[Number(btn.dataset.installIndex)], btn)));
    results.querySelectorAll<HTMLButtonElement>('[data-fav]').forEach((btn) => btn.addEventListener('click', async () => {
      try { await bridge.call('toggle_favorite', { item: state.rows[Number(btn.dataset.fav)] }); toast('已更新收藏', 'success'); }
      catch (e) { toast(errorMessage(e, '收藏失败'), 'error'); }
    }));
  };

  const paintInstalled = async () => {
    const instance = instSelect.value || 'default';
    const targetSel = panel.querySelector<HTMLSelectElement>('#catalog-mods-target');
    const version = targetSel?.value || '';
    showSkeleton(results, 'rows', 4);
    try {
      const rows = config.list === 'get_installed_mods'
        ? await bridge.call<any[]>('get_installed_mod_entries', { instance, version })
        : await bridge.call<any[]>(config.list, { instance });
      const list = Array.isArray(rows) ? rows : [];
      if (!list.length) {
        results.innerHTML = `<div class="empty-state"><div>还没有安装${config.noun}</div></div>`;
        return;
      }
      results.innerHTML = list.map((row, i) => {
        const name = row.filename || row.name || String(row);
        return `<div class="catalog-row"><div style="flex:1">${escapeHtml(name)}</div><button class="btn btn-sm btn-danger" data-del="${i}">删除</button></div>`;
      }).join('');
      results.querySelectorAll<HTMLButtonElement>('[data-del]').forEach((btn) => btn.addEventListener('click', async () => {
        const row = list[Number(btn.dataset.del)];
        const name = row.filename || row.name || String(row);
        // 对齐 Qt 版：整合包删除 = 删整个实例；存档删除不可恢复，都需明确警告
        const warn = config.del === 'delete_modpack'
          ? `将删除整个实例「${instSelect.value}」及其文件，不可恢复。`
          : config.del === 'delete_save'
            ? `将永久删除世界「${name}」，其中的建筑与游戏进度都无法恢复。建议先在「存档管理」里备份。`
            : `将删除「${name}」。`;
        if (!await confirmDialog(config.del === 'delete_modpack' ? '删除整合包实例' : '删除确认', warn)) return;
        try {
          await bridge.call(config.del, config.del === 'delete_modpack' ? { instance, filename: name } : { instance, filename: name, name });
          toast('已删除', 'success');
          void paintInstalled();
        } catch (e) { toast(errorMessage(e, '删除失败'), 'error'); }
      }));
    } catch (e) { results.innerHTML = `<div class="empty-state">${escapeHtml(errorMessage(e, '读取失败'))}</div>`; }
  };

  const search = async () => {
    state.query = queryInput.value.trim();
    state.source = sourceSelect.value;
    state.gameVersion = versionInput.value.trim();
    state.type = typeSelect.value;
    const request = ++requestNumber;
    status.textContent = '正在搜索…';
    showSkeleton(results, 'rows', 5);
    try {
      const rows = await bridge.call<CatalogEntry[]>(config.search, {
        query: state.query, source: state.source,
        extra: { game_version: /^全部/.test(state.gameVersion) ? '' : state.gameVersion, category: state.type },
      });
      if (request !== requestNumber) return;
      state.rows = Array.isArray(rows) ? rows : [];
      paintSearch(state.rows);
      status.textContent = `找到 ${state.rows.length} 个结果`;
    } catch (e) {
      if (request !== requestNumber) return;
      status.textContent = errorMessage(e, '搜索失败');
    }
  };

  const setMode = (mode: typeof state.mode) => {
    state.mode = mode;
    panel.querySelectorAll('[data-mode]').forEach((el) => el.classList.toggle('active', (el as HTMLElement).dataset.mode === mode));
    // Mod 的「已安装」支持按版本隔离目录筛选 + 检查更新（对齐 Qt 版 installed_ver_box/update_btn）
    const targetSel = panel.querySelector<HTMLSelectElement>('#catalog-mods-target');
    const updateBtn = panel.querySelector<HTMLElement>('#catalog-update');
    if (targetSel && updateBtn) {
      const show = mode === 'installed';
      targetSel.style.display = show ? '' : 'none';
      updateBtn.style.display = show ? '' : 'none';
      if (show && !targetSel.options.length) {
        void bridge.call<any[]>('get_mods_targets', { instance: instSelect.value || 'default' }).then((rows) => {
          targetSel.innerHTML = (rows || []).map((t) => `<option value="${escapeHtml(t.value || '')}">${escapeHtml(t.label || '共享')}</option>`).join('');
        }).catch(() => undefined);
      }
    }
    if (mode === 'installed') void paintInstalled();
    else if (mode === 'favs') {
      showSkeleton(results, 'rows', 3);
      void bridge.call<CatalogEntry[]>('catalog_favorites').then((rows) => {
        state.rows = rows || [];
        paintSearch(state.rows);
        status.textContent = state.rows.length ? `收藏 ${state.rows.length} 项` : '还没有收藏';
      }).catch((e) => { status.textContent = errorMessage(e, '读取收藏失败'); });
    } else void search();
  };

  panel.querySelectorAll<HTMLButtonElement>('[data-mode]').forEach((btn) => btn.addEventListener('click', () => setMode(btn.dataset.mode as any)));
  panel.querySelector('#catalog-search')?.addEventListener('click', () => void search());
  panel.querySelector('#catalog-reset')?.addEventListener('click', () => {
    queryInput.value = '';
    sourceSelect.value = category === 'worlds' ? 'CurseForge' : '全部';
    versionInput.value = '';
    typeSelect.value = '全部';
    void search();
  });
  instSelect.addEventListener('change', () => {
    const targetSel = panel.querySelector<HTMLSelectElement>('#catalog-mods-target');
    if (targetSel) targetSel.innerHTML = '';
    if (state.mode === 'installed') setMode('installed');
  });
  panel.querySelector('#catalog-mods-target')?.addEventListener('change', () => void paintInstalled());
  panel.querySelector('#catalog-update')?.addEventListener('click', async () => {
    try {
      const taskId = await bridge.call<string>('start_mod_updates', { instance: instSelect.value || 'default' });
      toast('已开始检查更新', 'info');
      const unsub = bridge.subscribe('finished', (data: any) => {
        if (String(data.task_id || '') !== taskId) return;
        unsub();
        toast(String(data.message || (data.success ? '模组更新完成' : '检查更新失败')), data.success ? 'success' : 'error', 6000);
        if (data.success) void paintInstalled();
      });
    } catch (e) { toast(errorMessage(e, '检查更新失败'), 'error'); }
  });
  queryInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') void search(); });
  panel.querySelector('#catalog-link')?.addEventListener('click', async () => {
    const url = await inputDialog('从链接安装', 'https://…', '');
    if (!url) return;
    void doInstall({ name: url, url, source: sourceSelect.value }, panel.querySelector('#catalog-link')!);
  });
  panel.querySelector('#catalog-local')?.addEventListener('click', async () => {
    const path = await inputDialog('导入本地文件', '完整路径', '');
    if (!path) return;
    void doInstall({ name: path, path, source: '本地' } as CatalogEntry, panel.querySelector('#catalog-local')!);
  });
  if (state.mode === 'search' && !state.rows.length) void search();
  else if (state.mode === 'search') paintSearch(state.rows);
  else setMode(state.mode);
}

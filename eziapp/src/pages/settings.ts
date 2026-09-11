import { bridge } from '../bridge';
import { router } from '../router';
import { store } from '../store';
import { applyAppearance, confirmDialog, dismissOverlay, formDialog, inputDialog, showError, showSkeleton, toast } from '../ui';
import { escapeHtml, errorMessage } from './common';
import { showGlobalMods } from './dialogs';
import { requestLayoutEdit } from '../layout_bus';

export async function renderSettingsPage(container: HTMLElement) {
  showSkeleton(container, 'rows', 6);
  try {
    const [settings, multi, lang, langs, layout] = await Promise.all([
      bridge.call<any>('get_settings'),
      bridge.call<boolean>('allow_multi_instance').catch(() => false),
      bridge.call<string>('get_language').catch(() => 'zh_CN'),
      bridge.call<Record<string, string>>('available_languages').catch(() => ({ zh_CN: '简体中文' })),
      bridge.call<unknown>('get_layout').catch(() => null),
    ]);
    store.setSettings(settings);
    render(container, store.mergedSettings(), { multi: !!multi, lang, langs, layout: layoutState(layout) });
  } catch (e: any) {
    showError(container, '加载设置失败: ' + (e.message || '未知错误'), () => renderSettingsPage(container));
  }
}

function row(label: string, hint: string, control: string) {
  return `<div class="setting-row"><div class="setting-label">${label}${hint ? `<span class="setting-hint">${hint}</span>` : ''}</div><div class="setting-control">${control}</div></div>`;
}
function toggle(id: string, on: boolean) {
  return `<label class="toggle"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}><span class="toggle-slider"></span></label>`;
}

interface Extra { multi: boolean; lang: string; langs: Record<string, string>; layout: LayoutState | null }

/** get_layout / activate_layout_profile … 这一组 RPC 都回同一个结构，取出要用的两项。 */
interface LayoutState { profile: string; profiles: string[]; doc: unknown }
function layoutState(raw: unknown): LayoutState | null {
  if (!raw || typeof raw !== 'object') return null;
  const d = raw as Record<string, unknown>;
  return {
    profile: String(d.profile || ''),
    profiles: Array.isArray(d.profiles) ? d.profiles.map(String) : [],
    doc: d.doc,
  };
}

function render(container: HTMLElement, s: any, extra: Extra) {
  container.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:14px;max-width:860px">
      <div class="card"><div class="settings-section-title">版本隔离与存储</div>
        ${row('共享 libraries', '所有实例共享依赖库', toggle('share_libraries', !!s.share_libraries))}
        ${row('共享 assets', '所有实例共享资源', toggle('share_assets', !!s.share_assets))}
        ${row('新版本默认隔离', '安装新版本时写入隔离模式', `<select class="select" id="default_isolation">
          <option value="none" ${s.default_isolation === 'none' ? 'selected' : ''}>关闭</option>
          <option value="saves" ${s.default_isolation === 'saves' ? 'selected' : ''}>隔离存档</option>
          <option value="mods" ${s.default_isolation === 'mods' ? 'selected' : ''}>隔离 Mod</option>
          <option value="all" ${s.default_isolation === 'all' ? 'selected' : ''}>隔离全部</option></select>`)}
        ${row('游戏目录', '实例与版本所在文件夹', `<input class="input" id="game_dir" value="${escapeHtml(s.game_dir || '')}" style="width:260px">`)}
      </div>
      <div class="card"><div class="settings-section-title">界面</div>
        ${row('界面动画', '换页与进度条动效', toggle('ui_motion', s.ui_motion !== false))}
        ${row('下载飞入动画', '安装时飞入下载任务', toggle('ui_fly_animation', s.ui_fly_animation !== false))}
        ${row('飞入动画时长', '毫秒，建议 400–800', `<input class="input" id="ui_fly_duration_ms" type="number" value="${s.ui_fly_duration_ms || 620}" style="width:110px">`)}
        ${row('深色模式', '立即生效', toggle('ui_dark', !!s.ui_dark))}
        ${row('主题色', '例如 #2E9B6B', `<input class="input" id="theme_color" value="${escapeHtml(s.theme_color || '#2E9B6B')}" style="width:140px">`)}
        ${row('背景图', '本地图片路径或 http(s) 地址，可留空', `<input class="input" id="ui_background" value="${escapeHtml(s.ui_background || '')}" style="width:260px">`)}
        ${row('语言', '后端文案语言，重启后完全生效', `<select class="select" id="language">${Object.entries(extra.langs).map(([k, v]) => `<option value="${escapeHtml(k)}" ${k === extra.lang ? 'selected' : ''}>${escapeHtml(v)}</option>`).join('')}</select>`)}
        ${row('启动器可见性', '游戏启动后窗口怎么处理', `<select class="select" id="launcher_visibility">
          ${[['keep', '保持显示'], ['minimize', '最小化'], ['hide', '隐藏'], ['hide_reopen', '隐藏后重开'], ['close', '关闭启动器']].map(([k, l]) => `<option value="${k}" ${s.launcher_visibility === k ? 'selected' : ''}>${l}</option>`).join('')}</select>`)}
        ${row('启动页主页', '新闻 / 自定义 HTML / 空白', `<select class="select" id="homepage_mode">
          <option value="news" ${s.homepage_mode !== 'custom' && s.homepage_mode !== 'blank' ? 'selected' : ''}>Minecraft 新闻</option>
          <option value="custom" ${s.homepage_mode === 'custom' ? 'selected' : ''}>本地 HTML</option>
          <option value="blank" ${s.homepage_mode === 'blank' ? 'selected' : ''}>空白</option></select>`)}
        ${row('自定义主页', '本地 html 路径', `<input class="input" id="custom_homepage" value="${escapeHtml(s.custom_homepage || '')}" style="width:260px">`)}
        ${row('默认游戏窗口', '可被版本设置覆盖', `<select class="select" id="window_mode"><option value="window" ${s.window_mode !== 'maximize' ? 'selected' : ''}>窗口</option><option value="maximize" ${s.window_mode === 'maximize' ? 'selected' : ''}>全屏</option></select>`)}
        ${row('侧栏宽度', '140–320', `<input class="input" id="ui_sidebar_width" type="number" value="${s.ui_sidebar_width || 232}" style="width:110px">`)}
        <div class="form-row" style="margin-top:8px">
          <button class="btn" id="save-theme">保存当前主题</button>
          <button class="btn" id="load-theme">加载主题</button>
          <button class="btn" id="del-theme">删除主题</button>
          <button class="btn" id="import-theme">导入</button>
          <button class="btn" id="export-theme">导出</button>
        </div>
      </div>
      <div class="card"><div class="settings-section-title">个性化布局</div>
        ${row('启动页画布', '拖动、八向缩放、网格吸附、增删卡片', '<button class="btn" id="layout-edit">进入编辑</button>')}
        ${row('布局方案', '存多套摆法随时切换；与 Qt 版界面共用同一份', '<select class="select" id="layout_profile" style="min-width:180px"></select>')}
        <div class="form-row" style="margin-top:8px">
          <button class="btn" id="layout-save-as">另存为方案</button>
          <button class="btn" id="layout-del">删除方案</button>
          <button class="btn" id="layout-reset">重置为默认</button>
          <button class="btn" id="layout-import">导入</button>
          <button class="btn" id="layout-export">导出</button>
        </div>
      </div>
      <div class="card"><div class="settings-section-title">下载与性能</div>
        ${row('下载线程数', '同时下载的文件数量', `<input class="input" id="download_threads" type="number" value="${s.download_threads || 8}" style="width:90px">`)}
        ${row('默认内存 MB', '', `<input class="input" id="default_memory_mb" type="number" value="${s.default_memory_mb || 4096}" style="width:110px">`)}
        ${row('内存回收器', '启动时写入 JVM', `<select class="select" id="gc_preset">
          ${[['auto', 'G1（推荐）'], ['g1', 'G1'], ['g1_tuned', '调优 G1'], ['zgc', 'ZGC'], ['none', '不指定']].map(([k, l]) => `<option value="${k}" ${(s.gc_preset || 'auto') === k ? 'selected' : ''}>${l}</option>`).join('')}</select>`)}
        ${row('下载限速 KB/s', '0 表示不限制', `<input class="input" id="download_limit_kbps" type="number" value="${s.download_limit_kbps || 0}" style="width:110px">`)}
        ${row('文件下载源', '官方慢则 BMCLAPI', `<select class="select" id="download_source">
          <option value="auto" ${(s.download_source || 'auto') === 'auto' ? 'selected' : ''}>自动</option>
          <option value="official" ${s.download_source === 'official' ? 'selected' : ''}>仅官方</option>
          <option value="bmclapi" ${s.download_source === 'bmclapi' ? 'selected' : ''}>仅 BMCLAPI</option></select>`)}
        ${row('社区资源源', '模组 / 整合包镜像', `<select class="select" id="community_source">
          <option value="auto" ${(s.community_source || 'auto') === 'auto' ? 'selected' : ''}>自动</option>
          <option value="official" ${s.community_source === 'official' ? 'selected' : ''}>仅官方</option>
          <option value="mcim" ${s.community_source === 'mcim' ? 'selected' : ''}>仅 MCIM</option></select>`)}
        ${row('跟随系统代理', 'Clash 等代理会生效', toggle('use_system_proxy', s.use_system_proxy !== false))}
        ${row('跳过资源校验', '重装时已下载的资源不再重复校验', toggle('skip_assets', !!s.skip_assets))}
        ${row('默认 JVM 参数', '', `<input class="input" id="default_jvm_args" value="${escapeHtml(s.default_jvm_args || '')}" style="width:260px">`)}
        ${row('默认分辨率', '', `<input class="input" id="res_w" type="number" value="${(s.default_resolution || [854, 480])[0]}" style="width:80px"><span>×</span><input class="input" id="res_h" type="number" value="${(s.default_resolution || [854, 480])[1]}" style="width:80px">`)}
      </div>
      <div class="card"><div class="settings-section-title">账号与下载源</div>
        ${row('微软 Client ID', '一般无需修改', `<input class="input" id="ms_client_id" value="${escapeHtml(s.ms_client_id || '')}" style="width:260px">`)}
        ${row('CurseForge API Key', '镜像不可用时兜底', `<input class="input" id="curseforge_api_key" type="password" value="${escapeHtml(s.curseforge_api_key || '')}" style="width:260px">`)}
        ${row('离线皮肤', '离线账号默认皮肤', `<select class="select" id="offline_skin">
          ${[['default', '默认'], ['steve', 'Steve'], ['alex', 'Alex']].map(([k, l]) => `<option value="${k}" ${(s.offline_skin || 'default') === k ? 'selected' : ''}>${l}</option>`).join('')}</select>`)}
      </div>
      <div class="card"><div class="settings-section-title">维护</div>
        ${row('更新清单 URL', 'JSON：version / url / notes', `<input class="input" id="update_url" value="${escapeHtml(s.update_url || '')}" style="width:260px">`)}
        ${row('启动时检查更新', '', toggle('auto_check_update', s.auto_check_update !== false))}
        ${row('允许多开', '取消勾选则游戏运行时再次启动会提示', toggle('allow_multi_instance', extra.multi))}
        <div class="form-row">
          <button class="btn" id="migrate">官方启动器迁移</button>
          <button class="btn" id="recommend">智能推荐</button>
          <button class="btn" id="global-mods">全局 Mod</button>
          <button class="btn" id="goto-tools">维护工具</button>
          <button class="btn" id="goto-playtime">游玩时长</button>
        </div>
        <div style="font-size:11px;color:var(--text-disabled)">维护工具与游玩时长不再占用侧栏位置，从这里或启动页的快捷入口卡片进入。</div>
      </div>
      <div class="card"><div class="settings-section-title">AI 助手</div>
        ${row('接入方式', '公益接口已内置', `<select class="select" id="ai_mode"><option value="public" ${s.ai_mode !== 'custom' ? 'selected' : ''}>公益接口</option><option value="custom" ${s.ai_mode === 'custom' ? 'selected' : ''}>自定义 NewAPI</option></select>`)}
        ${row('自建网关', '一般留空', `<input class="input" id="ai_gateway_url" value="${escapeHtml(s.ai_gateway_url || '')}" style="width:260px">`)}
        ${row('NewAPI 地址', '自定义模式填到 /v1', `<input class="input" id="ai_base_url" value="${escapeHtml(s.ai_base_url || '')}" style="width:260px">`)}
        ${row('NewAPI 令牌', '', `<input class="input" id="ai_api_key" type="password" value="${escapeHtml(s.ai_api_key || '')}" style="width:260px">`)}
        ${row('模型名', '公益模式锁定 deepseek-v4-flash', `<input class="input" id="ai_model" value="${escapeHtml(s.ai_model || '')}" style="width:260px">`)}
      </div>
      <div class="card"><div class="settings-section-title">反馈与诊断</div>
        ${row('允许上传诊断数据', '', toggle('feedback_consent', !!s.feedback_consent))}
        ${row('反馈上报地址', '', `<input class="input" id="feedback_url" value="${escapeHtml(s.feedback_url || '')}" style="width:260px">`)}
        ${row('定时上报本机配置', '', toggle('feedback_heartbeat', s.feedback_heartbeat !== false))}
      </div>
      <div class="form-row" style="justify-content:flex-end">
        <button class="btn" id="test-ai">测试 AI 连接</button>
        <button class="btn btn-primary" id="btn-save-settings">保存设置</button>
      </div>
      <div style="font-size:11px;color:var(--text-disabled)">启动器目录：${escapeHtml(s.root || '')}</div>
    </div>`;

  const val = (id: string) => (document.getElementById(id) as HTMLInputElement | HTMLSelectElement).value;
  const chk = (id: string) => (document.getElementById(id) as HTMLInputElement).checked;
  // 桥接 save_settings 只认这批键；外观类走本地覆盖层
  const collectBackend = () => ({
    share_libraries: chk('share_libraries'), share_assets: chk('share_assets'),
    default_isolation: val('default_isolation'),
    instances_dir: val('game_dir').trim(),
    ui_dark: chk('ui_dark'),
    launcher_visibility: val('launcher_visibility'), homepage_mode: val('homepage_mode'),
    custom_homepage: val('custom_homepage'), window_mode: val('window_mode'),
    download_threads: parseInt(val('download_threads')) || 8,
    default_memory_mb: parseInt(val('default_memory_mb')) || 4096,
    gc_preset: val('gc_preset'), download_limit_kbps: parseInt(val('download_limit_kbps')) || 0,
    download_source: val('download_source'), community_source: val('community_source'),
    use_system_proxy: chk('use_system_proxy'), skip_assets: chk('skip_assets'),
    default_jvm_args: val('default_jvm_args'),
    default_resolution: [parseInt(val('res_w')) || 854, parseInt(val('res_h')) || 480],
    ms_client_id: val('ms_client_id'), curseforge_api_key: val('curseforge_api_key'),
    offline_skin: val('offline_skin'),
    update_url: val('update_url'), auto_check_update: chk('auto_check_update'),
    ai_mode: val('ai_mode'), ai_gateway_url: val('ai_gateway_url'), ai_base_url: val('ai_base_url'),
    ai_api_key: val('ai_api_key'), ai_model: val('ai_model'),
    feedback_consent: chk('feedback_consent'), feedback_url: val('feedback_url'),
    feedback_heartbeat: chk('feedback_heartbeat'),
  });
  const collectLocal = () => ({
    theme_color: val('theme_color').trim() || '#2E9B6B',
    ui_background: val('ui_background').trim(),
    ui_motion: chk('ui_motion'),
    ui_fly_animation: chk('ui_fly_animation'),
    ui_fly_duration_ms: parseInt(val('ui_fly_duration_ms')) || 620,
    ui_sidebar_width: parseInt(val('ui_sidebar_width')) || 232,
    skip_assets: chk('skip_assets'),
  });

  const applyLive = () => {
    store.setLocalPrefs(collectLocal());
    applyAppearance(store.mergedSettings() as any);
  };
  // 深色开关文案写「立即生效」，就必须立刻落盘（对齐 Qt 版 _on_dark_toggled）
  document.getElementById('ui_dark')?.addEventListener('change', () => {
    applyLive();
    void bridge.call('save_settings', { ui_dark: chk('ui_dark') }).catch(() => undefined);
  });
  document.getElementById('theme_color')?.addEventListener('change', applyLive);
  document.getElementById('ui_background')?.addEventListener('change', applyLive);
  document.getElementById('ui_motion')?.addEventListener('change', applyLive);

  document.getElementById('btn-save-settings')?.addEventListener('click', async () => {
    const payload = collectBackend();
    const local = collectLocal();
    const lang = val('language');
    const multi = chk('allow_multi_instance');
    try {
      await bridge.call('save_settings', payload);
      // 这两个键 save_settings 不处理，走专用 RPC
      await bridge.call('set_multi_instance', { allow: multi }).catch(() => undefined);
      if (lang !== extra.lang) {
        await bridge.call('set_language', { lang }).catch(() => undefined);
        toast('语言已切换，重启后界面文案完全生效', 'info', 5000);
      }
      store.setLocalPrefs(local);
      store.setSettings({ ...(store.settings || {}), ...payload } as any);
      applyAppearance(store.mergedSettings() as any);
      toast('设置已保存', 'success');
    } catch (e: any) { toast(e.message || '保存失败', 'error'); }
  });
  document.getElementById('test-ai')?.addEventListener('click', async () => {
    const btn = document.getElementById('test-ai') as HTMLButtonElement;
    btn.disabled = true;
    btn.textContent = '测试中…';
    try {
      // 用表单里还没保存的值试连，不必先落盘（对齐 Qt 版 _test_ai）
      const msg = await bridge.call<string>('test_ai_connection', {
        settings: {
          ai_mode: val('ai_mode'), ai_gateway_url: val('ai_gateway_url'),
          ai_base_url: val('ai_base_url'), ai_api_key: val('ai_api_key'), ai_model: val('ai_model'),
        },
      });
      toast(msg || 'AI 连接正常', 'success');
    } catch (e) { toast(errorMessage(e, 'AI 连接失败'), 'error', 6000); }
    finally { btn.disabled = false; btn.textContent = '测试 AI 连接'; }
  });
  wireLayout(extra.layout);
  document.getElementById('global-mods')?.addEventListener('click', () => void showGlobalMods());
  document.getElementById('goto-tools')?.addEventListener('click', () => router.navigate('tools'));
  document.getElementById('goto-playtime')?.addEventListener('click', () => router.navigate('playtime'));
  document.getElementById('recommend')?.addEventListener('click', async () => {
    try {
      const data = await bridge.call<any>('get_smart_recommendation');
      showRecommendation(data || {});
    } catch (e) { toast(errorMessage(e, '获取失败'), 'error'); }
  });
  document.getElementById('migrate')?.addEventListener('click', async () => {
    try {
      const found = await bridge.call<boolean>('detect_official_launcher');
      if (!found) { toast('未检测到官方启动器目录', 'warning'); return; }
      const versions = await bridge.call<string[]>('scan_official_versions').catch(() => [] as string[]);
      const hint = versions.length ? `检测到 ${versions.length} 个版本：${versions.slice(0, 4).join('、')}${versions.length > 4 ? ' 等' : ''}` : '未发现可导入的版本';
      if (!await confirmDialog('官方启动器迁移', `${hint}。从官方 .minecraft 导入版本到当前实例？`)) return;
      await bridge.call('migrate_official_launcher', { instance: store.currentInstance || 'default' });
      toast('已开始迁移，进度见下载任务页', 'success');
      router.navigate('tasks');
    } catch (e) { toast(errorMessage(e, '迁移失败'), 'error'); }
  });
  document.getElementById('save-theme')?.addEventListener('click', async () => {
    const name = await inputDialog('保存主题', '主题名称', '我的主题');
    if (!name) return;
    try { await bridge.call('save_theme', { name }); toast('主题已保存', 'success'); }
    catch (e) { toast(errorMessage(e, '保存失败'), 'error'); }
  });
  document.getElementById('load-theme')?.addEventListener('click', async () => {
    try {
      const themes = await bridge.call<any[]>('list_themes');
      if (!themes?.length) { toast('还没有保存的主题', 'info'); return; }
      const picked = await formDialog('加载主题', [{
        id: 'name', label: '选择主题', type: 'select', value: themes[0]?.name || '',
        options: themes.map((t) => ({ value: String(t.name || ''), label: String(t.name || '?') })),
      }]);
      if (!picked?.name) return;
      const loaded = await bridge.call<any>('load_theme', { name: picked.name });
      // 主题包里的外观键同样落到本地覆盖层
      const patch: Record<string, unknown> = {};
      for (const k of ['theme_color', 'ui_background', 'ui_dark'] as const) {
        if (loaded && loaded[k] !== undefined) patch[k] = loaded[k];
      }
      if (Object.keys(patch).length) store.setLocalPrefs(patch);
      store.setSettings({ ...(store.settings || {}), ...loaded } as any);
      applyAppearance(store.mergedSettings() as any);
      toast('主题已加载', 'success');
      renderSettingsPage(container);
    } catch (e) { toast(errorMessage(e, '加载失败'), 'error'); }
  });
  document.getElementById('del-theme')?.addEventListener('click', async () => {
    const name = await inputDialog('删除主题', '主题名称', '');
    if (!name) return;
    try { await bridge.call('delete_theme', { name }); toast('已删除', 'success'); }
    catch (e) { toast(errorMessage(e, '删除失败'), 'error'); }
  });
  document.getElementById('import-theme')?.addEventListener('click', async () => {
    const path = await inputDialog('导入主题包', '主题文件完整路径（.json）', '');
    if (!path?.trim()) return;
    try { const name = await bridge.call<string>('import_theme', { path: path.trim() }); toast(`已导入主题「${name || path}」`, 'success'); }
    catch (e) { toast(errorMessage(e, '导入失败'), 'error'); }
  });
  document.getElementById('export-theme')?.addEventListener('click', async () => {
    const values = await formDialog('导出主题包', [
      { id: 'name', label: '主题名称', placeholder: '我的主题' },
      { id: 'dest', label: '导出到（完整路径，留空用默认 exports 目录）', placeholder: 'D:\\themes\\my.json' },
    ]);
    if (!values?.name?.trim()) return;
    try {
      const out = await bridge.call<string>('export_theme', { name: values.name.trim(), dest: (values.dest || '').trim() });
      toast(out ? `已导出：${out}` : '已导出主题', 'success');
    } catch (e) { toast(errorMessage(e, '导出失败'), 'error'); }
  });
}

/** 导出：浏览器直接下地，不走后端文件对话框（对齐 Qt 版 export_current_layout 的产物格式）。 */
function downloadJson(filename: string, data: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** 导入：<input type=file> + FileReader，同样不必经过后端。取消选择时 resolve(null)。 */
function pickJsonFile(): Promise<string | null> {
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,application/json';
    input.style.display = 'none';
    const done = (value: string | null) => { input.remove(); resolve(value); };
    input.addEventListener('cancel', () => done(null));
    input.addEventListener('change', () => {
      const file = input.files?.[0];
      if (!file) { done(null); return; }
      const reader = new FileReader();
      reader.onload = () => done(String(reader.result || ''));
      reader.onerror = () => done(null);
      reader.readAsText(file, 'utf-8');
    });
    document.body.appendChild(input);
    input.click();
  });
}

/**
 * 「个性化布局」组：方案切换 / 另存 / 删除 / 重置 / 导入导出 + 进入编辑。
 * 这几个 RPC 回的都是完整的布局状态，拿回来直接重画下拉，不必再读一次。
 */
function wireLayout(initial: LayoutState | null) {
  const select = document.getElementById('layout_profile') as HTMLSelectElement | null;
  if (!select) return;
  let state: LayoutState = initial || { profile: '', profiles: [], doc: null };

  const paint = () => {
    select.innerHTML = '<option value="">默认（未命名）</option>'
      + state.profiles.map((n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`).join('');
    select.value = state.profiles.includes(state.profile) ? state.profile : '';
  };
  paint();

  /** 跑一个会改动布局的 RPC，成功就用回执刷新本组状态。 */
  const run = async (method: string, params: Record<string, unknown>, ok: string, fail: string) => {
    try {
      const next = layoutState(await bridge.call<unknown>(method, params));
      if (next) { state = next; paint(); }
      toast(ok, 'success');
      return true;
    } catch (e) {
      toast(errorMessage(e, fail), 'error');
      paint(); // 切换失败时把下拉拨回真正生效的那个
      return false;
    }
  };

  document.getElementById('layout-edit')?.addEventListener('click', () => {
    // 画布只活在启动页：不在那儿就先记下请求，切过去后它自己进编辑态
    if (!requestLayoutEdit()) router.navigate('launch');
  });
  select.addEventListener('change', () => {
    const name = select.value;
    void run('activate_layout_profile', { name }, name ? `已切换到「${name}」` : '已切回默认布局', '切换失败');
  });
  document.getElementById('layout-save-as')?.addEventListener('click', async () => {
    const name = await inputDialog('另存为布局方案', '方案名称', state.profile || '我的布局');
    if (!name?.trim()) return;
    await run('save_layout_profile', { name: name.trim() }, `已保存方案「${name.trim()}」`, '保存失败');
  });
  document.getElementById('layout-del')?.addEventListener('click', async () => {
    if (!state.profile) { toast('当前用的是默认布局，没有可删除的方案', 'warning'); return; }
    const name = state.profile;
    if (!await confirmDialog('删除布局方案', `删除方案「${name}」？当前生效的布局本身不会变。`)) return;
    await run('delete_layout_profile', { name }, `已删除方案「${name}」`, '删除失败');
  });
  document.getElementById('layout-reset')?.addEventListener('click', async () => {
    if (!await confirmDialog('重置启动页布局', '恢复成内置默认摆法？当前未另存为方案的改动会丢失。')) return;
    await run('reset_layout', {}, '布局已重置', '重置失败');
  });
  document.getElementById('layout-export')?.addEventListener('click', async () => {
    try {
      const cur = layoutState(await bridge.call<unknown>('get_layout'));
      if (!cur?.doc) { toast('没有可导出的布局', 'warning'); return; }
      downloadJson(`pymcl-layout-${cur.profile || 'default'}.json`, cur.doc);
      toast('布局已导出', 'success');
    } catch (e) { toast(errorMessage(e, '导出失败'), 'error'); }
  });
  document.getElementById('layout-import')?.addEventListener('click', async () => {
    const text = await pickJsonFile();
    if (text === null) return;
    let doc: unknown;
    try { doc = JSON.parse(text); }
    catch { toast('这不是一份有效的 JSON 文件', 'error'); return; }
    await run('import_layout', { doc }, '布局已导入，回到启动页即可看到', '导入失败');
  });
}

function showRecommendation(data: Record<string, unknown>) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  const rows = Object.entries(data)
    .filter(([, v]) => v !== undefined && v !== null && String(v) !== '')
    .map(([k, v]) => `<div class="setting-row"><div class="setting-label" style="font-family:var(--font-mono);font-size:12px">${escapeHtml(k)}</div><div style="font-size:13px;max-width:60%;text-align:right;overflow-wrap:anywhere">${escapeHtml(typeof v === 'object' ? JSON.stringify(v) : String(v))}</div></div>`)
    .join('');
  overlay.innerHTML = `
    <div class="modal" style="width:min(560px, calc(100vw - 32px))">
      <div class="modal-title">智能推荐</div>
      <div style="font-size:12px;color:var(--text-secondary);margin-bottom:10px">根据本机硬件给出的内存与 Java 建议，可到「下载与性能」里套用。</div>
      <div style="max-height:50vh;overflow:auto">${rows || '<div class="empty-state">暂无建议</div>'}</div>
      <div class="modal-actions"><button class="btn btn-primary" id="rec-close">关闭</button></div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('#rec-close')?.addEventListener('click', () => dismissOverlay(overlay));
  overlay.addEventListener('click', (e) => { if (e.target === overlay) dismissOverlay(overlay); });
}

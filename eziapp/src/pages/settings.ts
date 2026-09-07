import { bridge } from '../bridge';
import { router } from '../router';
import { store } from '../store';
import { applyAppearance, confirmDialog, inputDialog, showError, showLoading, toast } from '../ui';
import { escapeHtml, errorMessage } from './common';
import { showGlobalMods } from './dialogs';

export async function renderSettingsPage(container: HTMLElement) {
  showLoading(container);
  try {
    const settings = await bridge.call<any>('get_settings');
    store.setSettings(settings);
    render(container, settings);
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

function render(container: HTMLElement, s: any) {
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
        ${row('背景图', '本地图片路径，可留空', `<input class="input" id="ui_background" value="${escapeHtml(s.ui_background || '')}" style="width:260px">`)}
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
        ${row('默认 JVM 参数', '', `<input class="input" id="default_jvm_args" value="${escapeHtml(s.default_jvm_args || '')}" style="width:260px">`)}
        ${row('默认分辨率', '', `<input class="input" id="res_w" type="number" value="${(s.default_resolution || [854, 480])[0]}" style="width:80px"><span>×</span><input class="input" id="res_h" type="number" value="${(s.default_resolution || [854, 480])[1]}" style="width:80px">`)}
      </div>
      <div class="card"><div class="settings-section-title">账号与下载源</div>
        ${row('微软 Client ID', '一般无需修改', `<input class="input" id="ms_client_id" value="${escapeHtml(s.ms_client_id || '')}" style="width:260px">`)}
        ${row('CurseForge API Key', '镜像不可用时兜底', `<input class="input" id="curseforge_api_key" type="password" value="${escapeHtml(s.curseforge_api_key || '')}" style="width:260px">`)}
      </div>
      <div class="card"><div class="settings-section-title">维护</div>
        ${row('更新清单 URL', 'JSON：version / url / notes', `<input class="input" id="update_url" value="${escapeHtml(s.update_url || '')}" style="width:260px">`)}
        ${row('启动时检查更新', '', toggle('auto_check_update', s.auto_check_update !== false))}
        ${row('允许多开', '取消勾选则游戏运行时再次启动会提示', toggle('allow_multi_instance', !!s.allow_multi_instance))}
        <div class="form-row">
          <button class="btn" id="migrate">官方启动器迁移</button>
          <button class="btn" id="recommend">智能推荐</button>
          <button class="btn" id="global-mods">全局 Mod</button>
          <button class="btn" id="goto-tools">维护工具</button>
        </div>
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
  const collect = () => ({
    share_libraries: chk('share_libraries'), share_assets: chk('share_assets'),
    default_isolation: val('default_isolation'), game_dir: val('game_dir'),
    ui_motion: chk('ui_motion'), ui_fly_animation: chk('ui_fly_animation'),
    ui_fly_duration_ms: parseInt(val('ui_fly_duration_ms')) || 620,
    ui_dark: chk('ui_dark'), theme_color: val('theme_color'), ui_background: val('ui_background'),
    launcher_visibility: val('launcher_visibility'), homepage_mode: val('homepage_mode'),
    custom_homepage: val('custom_homepage'), window_mode: val('window_mode'),
    ui_sidebar_width: parseInt(val('ui_sidebar_width')) || 232,
    download_threads: parseInt(val('download_threads')) || 8,
    default_memory_mb: parseInt(val('default_memory_mb')) || 4096,
    gc_preset: val('gc_preset'), download_limit_kbps: parseInt(val('download_limit_kbps')) || 0,
    download_source: val('download_source'), community_source: val('community_source'),
    use_system_proxy: chk('use_system_proxy'), default_jvm_args: val('default_jvm_args'),
    default_resolution: [parseInt(val('res_w')) || 854, parseInt(val('res_h')) || 480],
    ms_client_id: val('ms_client_id'), curseforge_api_key: val('curseforge_api_key'),
    update_url: val('update_url'), auto_check_update: chk('auto_check_update'),
    allow_multi_instance: chk('allow_multi_instance'),
    ai_mode: val('ai_mode'), ai_gateway_url: val('ai_gateway_url'), ai_base_url: val('ai_base_url'),
    ai_api_key: val('ai_api_key'), ai_model: val('ai_model'),
    feedback_consent: chk('feedback_consent'), feedback_url: val('feedback_url'),
    feedback_heartbeat: chk('feedback_heartbeat'),
  });

  const applyLive = () => {
    const next = collect();
    store.setSettings({ ...(store.settings || {}), ...next } as any);
    applyAppearance(next as any);
  };
  document.getElementById('ui_dark')?.addEventListener('change', applyLive);
  document.getElementById('theme_color')?.addEventListener('change', applyLive);
  document.getElementById('ui_background')?.addEventListener('change', applyLive);

  document.getElementById('btn-save-settings')?.addEventListener('click', async () => {
    const settings = collect();
    try {
      await bridge.call('save_settings', settings);
      store.setSettings({ ...(store.settings || {}), ...settings } as any);
      applyAppearance(settings as any);
      toast('设置已保存', 'success');
    } catch (e: any) { toast(e.message || '保存失败', 'error'); }
  });
  document.getElementById('test-ai')?.addEventListener('click', async () => {
    try {
      await bridge.call('ai_list_chats');
      toast('AI 会话服务可用，可到 AI 页发消息验证模型', 'success');
    } catch (e) { toast(errorMessage(e, '测试失败'), 'error'); }
  });
  document.getElementById('global-mods')?.addEventListener('click', () => void showGlobalMods());
  document.getElementById('goto-tools')?.addEventListener('click', () => router.navigate('tools'));
  document.getElementById('recommend')?.addEventListener('click', async () => {
    try {
      const data = await bridge.call<any>('get_smart_recommendation');
      toast(JSON.stringify(data).slice(0, 180), 'info', 6000);
    } catch (e) { toast(errorMessage(e, '获取失败'), 'error'); }
  });
  document.getElementById('migrate')?.addEventListener('click', async () => {
    if (!await confirmDialog('官方启动器迁移', '从官方 .minecraft 导入版本和账号？')) return;
    try {
      await bridge.call('migrate_official_launcher', { instance: store.currentInstance || 'default' });
      toast('已开始迁移', 'success');
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
      const name = await inputDialog('加载主题', themes.map((t) => t.name).join(' / ') || '没有主题', themes[0]?.name || '');
      if (!name) return;
      const loaded = await bridge.call<any>('load_theme', { name });
      store.setSettings({ ...(store.settings || {}), ...loaded } as any);
      applyAppearance(loaded);
      toast('主题已加载，建议再点保存设置', 'success');
    } catch (e) { toast(errorMessage(e, '加载失败'), 'error'); }
  });
  document.getElementById('del-theme')?.addEventListener('click', async () => {
    const name = await inputDialog('删除主题', '主题名称', '');
    if (!name) return;
    try { await bridge.call('delete_theme', { name }); toast('已删除', 'success'); }
    catch (e) { toast(errorMessage(e, '删除失败'), 'error'); }
  });
}

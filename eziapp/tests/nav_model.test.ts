/**
 * 侧栏编排模型的用例。跑法（Node 22+ 直接吃 TS）：
 *
 *   node eziapp/tests/nav_model.test.ts
 *
 * 这里守的是「一个页面永远点得到」这类规则本身；与 Qt 版逐条同不同，
 * 由 tests/test_nav_parity.py 拿真配置两边对算来判。
 */

import {
  ALL_SUB_KEYS, DEFAULT_NAV_HIDDEN, DEFAULT_NAV_ORDER, DEFAULT_NAV_PINNED,
  NAV_STYLE_COMPACT, NAV_STYLE_GROUPED, SECTION_IDS, TOP_KEYS,
  defaultNavPatch, mergeNavOrder, navItemsFromConfig, navStyle, navUntouched,
  pinNavConfig, pinnedFromConfig, reorderNavConfig, sectionMembersFromConfig,
  sidebarSequence, unpinNavConfig, visibleSections, type NavConfig,
} from '../src/nav_model.ts';

const failures: string[] = [];

function check(name: string, ok: boolean, detail = '') {
  if (ok) return;
  failures.push(`${name}${detail ? `: ${detail}` : ''}`);
}

function eq(name: string, actual: unknown, expected: unknown) {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  check(name, a === b, `${a} != ${b}`);
}

const keysOf = (cfg: NavConfig) => sidebarSequence(cfg);

// 出厂：没有任何配置时就是分组排法，与 Qt 的 _GROUPED_NAV 同一套
{
  eq('empty config → grouped', navStyle({}), NAV_STYLE_GROUPED);
  eq('grouped sequence', keysOf({}),
    ['account', 'launch', 'instance', 'download', 'settings', 'multiplayer', 'ai', 'more', 'tasks']);
  check('grouped has headers',
    navItemsFromConfig({}).filter((it) => it.kind === 'header').length === 3);
  // 分组排法里这些子页算「已固定」，不该再长在分区横条上
  const members = sectionMembersFromConfig({});
  for (const key of ['account', 'instance', 'settings', 'multiplayer']) {
    check('grouped pinned leaves sections', !members.download.includes(key) && !members.more.includes(key), key);
  }
  check('every section still has members', SECTION_IDS.every((sec) => members[sec].length > 0));
}

// 隐藏整组：组标题跟着消失，剩下的项照旧都在
{
  const cfg: NavConfig = { ui_nav_hidden: ['account'] };
  const items = navItemsFromConfig(cfg);
  check('hidden lone member drops its header',
    !items.some((it) => it.kind === 'header' && it.label === '账户'));
  check('account gone', !keysOf(cfg).includes('account'));
}

// 精简排法：一级项按 ui_nav_order 排，沉底那一撮前面有分隔
{
  const cfg: NavConfig = {
    ui_nav_style: NAV_STYLE_COMPACT,
    ui_nav_order: ['launch', 'download', 'instance', 'more', 'settings', 'tasks'],
    ui_nav_pinned: ['instance', 'settings'],
    ui_nav_hidden: ['ai'],
  };
  eq('compact sequence', keysOf(cfg), ['launch', 'download', 'instance', 'more', 'settings', 'tasks']);
  const items = navItemsFromConfig(cfg);
  const stretchAt = items.findIndex((it) => it.kind === 'stretch');
  const moreAt = items.findIndex((it) => it.kind === 'item' && it.key === 'more');
  check('stretch sits right before the bottom group', stretchAt >= 0 && stretchAt === moreAt - 1,
    `stretch=${stretchAt} more=${moreAt}`);
  check('hidden top key is gone', !keysOf(cfg).includes('ai'));
  check('pinned pages are not section members',
    !sectionMembersFromConfig(cfg).more.includes('settings'));
}

// 一级键缺席也补得回来：配置里只写了一个键，其余仍然在侧栏上
{
  const cfg: NavConfig = { ui_nav_style: NAV_STYLE_COMPACT, ui_nav_order: ['tasks'] };
  const seq = keysOf(cfg);
  for (const key of TOP_KEYS) {
    if (key === 'ai') continue; // 这一档没隐藏任何键，ai 也该在
    check('missing top key restored', seq.includes(key), key);
  }
  eq('first stays first', seq[0], 'tasks');
}

// 固定项没进 order：插在「更多」之前，不会掉到末尾
{
  const cfg: NavConfig = {
    ui_nav_style: NAV_STYLE_COMPACT,
    ui_nav_order: ['launch', 'download', 'ai', 'more', 'tasks'],
    ui_nav_pinned: ['account'],
  };
  const seq = keysOf(cfg);
  check('late pinned lands before more', seq.indexOf('account') === seq.indexOf('more') - 1, seq.join(','));
}

// 取消固定：落点必须是点得到的分区
{
  const cfg: NavConfig = {
    ui_nav_style: NAV_STYLE_COMPACT,
    ui_nav_pinned: ['settings'],
    ui_nav_hidden: ['more'],
  };
  const landed = unpinNavConfig(cfg, 'settings');
  check('unpin returns a landing', !!landed);
  eq('hidden section rejected', landed?.section, 'download');
  const next = { ...cfg, ...(landed?.patch || {}) } as NavConfig;
  check('page is reachable again', sectionMembersFromConfig(next).download.includes('settings'));
  check('visible sections exclude the hidden one', !visibleSections(cfg).includes('more'));
  eq('unpinning a free page does nothing', unpinNavConfig(cfg, 'servers'), null);
}

// 两个分区都藏了：把落点那一栏放出来，否则这一页落地即失踪
{
  const cfg: NavConfig = {
    ui_nav_style: NAV_STYLE_COMPACT,
    ui_nav_pinned: ['settings'],
    ui_nav_hidden: ['more', 'download'],
  };
  const landed = unpinNavConfig(cfg, 'settings');
  const hidden = (landed?.patch.ui_nav_hidden as string[]) || [];
  check('landing section gets unhidden', !!landed && !hidden.includes(landed.section),
    `${landed?.section} hidden=${hidden.join(',')}`);
}

// 固定：移动语义，原分区里不再显示；只剩一项的分区拒绝移走
{
  const cfg: NavConfig = { ui_nav_style: NAV_STYLE_COMPACT };
  const out = pinNavConfig(cfg, 'servers');
  check('pin produced a patch', !!out && 'patch' in out);
  const patch = (out && 'patch' in out) ? out.patch : {};
  const next = { ...cfg, ...patch } as NavConfig;
  check('pinned now', pinnedFromConfig(next).includes('servers'));
  check('left the section', !sectionMembersFromConfig(next).more.includes('servers'));

  const lonely: NavConfig = {
    ui_nav_style: NAV_STYLE_COMPACT,
    ui_section_members: { download: ['java'], more: ['servers'] },
    // 其余子页全固定走，两栏各剩一个
    ui_nav_pinned: [...ALL_SUB_KEYS].filter((k) => k !== 'java' && k !== 'servers'),
  };
  const refused = pinNavConfig(lonely, 'java');
  check('last member of a section cannot be pinned away', !!refused && 'error' in refused);
}

// 分组档也能拖：固定 / 取消固定 / 重排都落在 ui_nav_groups 上。
// 以前这一档的分组是写死的，上面三件事全程静默失败——配置照写、侧栏照重建，
// 重建时又按常量重新生成，刚写进去的东西一点不剩。
{
  const pinned = pinNavConfig({}, 'servers');
  check('grouped pin produced a patch', !!pinned && 'patch' in pinned);
  const afterPin = { ...((pinned && 'patch' in pinned) ? pinned.patch : {}) } as NavConfig;
  check('grouped pin sticks', pinnedFromConfig(afterPin).includes('servers'));
  check('grouped pin lands before 更多',
    keysOf(afterPin).indexOf('servers') === keysOf(afterPin).indexOf('more') - 1,
    keysOf(afterPin).join(','));
  check('grouped pin leaves the section',
    !sectionMembersFromConfig(afterPin).more.includes('servers'));

  const moved = reorderNavConfig(afterPin, 'servers', 'account', true);
  const afterMove = { ...afterPin, ...(moved || {}) } as NavConfig;
  eq('grouped reorder crosses groups', keysOf(afterMove)[0], 'servers');

  const landed = unpinNavConfig(afterMove, 'servers');
  const afterUnpin = { ...afterMove, ...(landed?.patch || {}) } as NavConfig;
  check('grouped unpin drops it from the groups', !keysOf(afterUnpin).includes('servers'));
  check('grouped unpin puts it back in a section',
    sectionMembersFromConfig(afterUnpin).more.includes('servers'));
}

// 拖动排序：写回的是完整混合序列，pinned 只留子页
{
  const cfg: NavConfig = {
    ui_nav_style: NAV_STYLE_COMPACT,
    ui_nav_order: ['launch', 'download', 'instance', 'more', 'settings', 'tasks'],
    ui_nav_pinned: ['instance', 'settings'],
  };
  const patch = reorderNavConfig(cfg, 'instance', 'launch', true);
  // ai 没写进 ui_nav_order，补在末尾（对齐 Qt：一级键缺席自动补到最后）
  eq('reordered', patch?.ui_nav_order,
    ['instance', 'launch', 'download', 'more', 'settings', 'tasks', 'ai']);
  eq('pinned stays sub-pages only', patch?.ui_nav_pinned, ['instance', 'settings']);
  eq('no-op when target missing', reorderNavConfig(cfg, 'instance', 'nope', true), null);
}

// 编辑器合并：一级项换新顺序，固定子页保持它们在侧栏里的相对位置
{
  const cfg: NavConfig = {
    ui_nav_style: NAV_STYLE_COMPACT,
    ui_nav_order: ['launch', 'instance', 'download', 'ai', 'more', 'settings', 'tasks'],
    ui_nav_pinned: ['instance', 'settings'],
  };
  const merged = mergeNavOrder(cfg, ['download', 'launch', 'ai', 'more', 'tasks'], ['instance', 'settings']);
  eq('merge keeps pinned slots', merged,
    ['download', 'instance', 'launch', 'ai', 'more', 'settings', 'tasks']);
}

// 出厂判定与默认补写
{
  check('factory config is untouched', navUntouched({
    ui_nav_order: DEFAULT_NAV_ORDER, ui_nav_pinned: DEFAULT_NAV_PINNED,
    ui_nav_hidden: DEFAULT_NAV_HIDDEN,
  }));
  check('empty config counts as untouched', navUntouched({}));
  check('user order counts as touched', !navUntouched({ ui_nav_order: ['tasks', 'launch'] }));
  eq('default patch style', defaultNavPatch().ui_nav_style, NAV_STYLE_GROUPED);
}

if (failures.length) {
  console.error(`NAV MODEL: ${failures.length} failed`);
  for (const line of failures) console.error(`  [FAIL] ${line}`);
  process.exit(1);
}
console.log('NAV MODEL OK');

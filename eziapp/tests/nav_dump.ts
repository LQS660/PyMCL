/**
 * 把 nav_model 对一组配置算出来的侧栏结构打印成 JSON，供 Python 侧做一致性对照
 * （tests/test_nav_parity.py 拿它跟 Qt 版 app/main_window.py 的结果逐条比）。
 *
 *   echo '[{"ui_nav_style":"compact"}]' | node eziapp/tests/nav_dump.ts
 */

import {
  navItemsFromConfig, navStyle, pinnedFromConfig, sectionMembersFromConfig,
  sidebarSequence, unpinNavConfig, type NavConfig, type SectionId,
} from '../src/nav_model.ts';

interface Case {
  config: NavConfig;
  /** 可选：额外算一次「取消固定这个键」的结果。 */
  unpin?: { key: string; section?: SectionId | null; index?: number };
}

function describe(input: Case) {
  const cfg = input.config || {};
  const items = navItemsFromConfig(cfg).map((entry) => (
    entry.kind === 'item' ? ['item', entry.key, entry.label]
      : entry.kind === 'header' ? ['header', entry.label]
        : ['stretch']));
  const out: Record<string, unknown> = {
    style: navStyle(cfg),
    items,
    pinned: pinnedFromConfig(cfg),
    members: sectionMembersFromConfig(cfg),
    sequence: sidebarSequence(cfg),
  };
  if (input.unpin) {
    const landed = unpinNavConfig(cfg, input.unpin.key, input.unpin.section ?? null,
      input.unpin.index ?? -1);
    out.unpin = landed ? { section: landed.section, patch: landed.patch } : null;
  }
  return out;
}

const chunks: Buffer[] = [];
process.stdin.on('data', (chunk) => chunks.push(chunk as Buffer));
process.stdin.on('end', () => {
  const cases: Case[] = JSON.parse(Buffer.concat(chunks).toString('utf8') || '[]');
  process.stdout.write(JSON.stringify(cases.map(describe)));
});

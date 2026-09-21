# -*- coding: utf-8 -*-
"""AI 权限：模式 + 规则引擎 + 判权 + 规则落盘。

判定顺序照抄 ZCode，安全优先：
1. plan 模式硬约束：非只读工具一律 DENY（allow 规则也翻不过来）
2. 命中 behavior=DENY 规则 → DENY
3. 命中 behavior=ALLOW 规则 → ALLOW
4. 命中 behavior=ASK 规则 → ASK
5. 无规则命中 → 按 mode + 工具元数据给默认
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from enum import Enum

from mclauncher import utils


class PermissionMode(str, Enum):
    DEFAULT             = "default"             # 写操作一律问
    PLAN                = "plan"                # 只读，禁止一切写
    EDIT                = "edit"                # 允许文件类写，其他问
    ACCEPT_EDITS        = "acceptEdits"         # 写直接执行，删除仍问
    AUTO                = "auto"                # 同 acceptEdits，语义偏「自动」
    DONT_ASK            = "dontAsk"             # 不弹窗，会问的操作直接拒绝并说明
    AUTO_EDIT           = "autoEdit"            # 兼容旧 full
    YOLO                = "yolo"                # 全部直接执行
    BYPASS_PERMISSIONS  = "bypassPermissions"   # 同 yolo，留作显式后门
    BUILD               = "build"               # 允许安装/下载类


class Behavior(str, Enum):
    ALLOW = "allow"
    DENY  = "deny"
    ASK   = "ask"


class Decision(str, Enum):
    ALLOW    = "allow"
    DENY     = "deny"
    ASK      = "ask"        # 施工清单 W1-4 的伪代码用到 Decision.ASK，但 W1-1 枚举漏了它
    ESCALATE = "escalate"
    MODIFY   = "modify"


# ruleContent 从工具入参里按固定优先级取第一个非空字符串（判定顺序照抄 ZCode）。
# 前五个是 ZCode 的原键；后面几个是启动器工具真正用的标识：模组 slug / 名字、
# 模组文件名、游戏版本、Java 大版本。没有它们，「始终允许」会落成整个工具级
# （勾一次 delete_mod 以后删任何模组都不问），与卡片上写的「同一项不再询问」不符。
RULE_CONTENT_KEYS = ("command", "url", "file_path", "path", "pattern",
                     "filename", "slug", "name", "version", "major")

# 规则记忆范围：只记到当前实例，或记成全局
SCOPE_INSTANCE = "instance"
SCOPE_GLOBAL = "global"


@dataclass
class Rule:
    tool_name: str
    rule_content: str | None = None
    behavior: Behavior = Behavior.ALLOW
    # 只在「始终允许」回传时有意义：决定 append_rule 落到 per_instance 还是 global
    scope: str = SCOPE_INSTANCE

    def key(self) -> str:
        return f"{self.tool_name}\0{self.rule_content or ''}"


@dataclass
class PermissionResult:
    decision: Decision
    reason: str = ""
    modified_input: dict | None = None
    new_rules: list = field(default_factory=list)   # 对应 ZCode 的 addRules
    rule_id: str = ""
    escalated: bool = False


def rule_content_from_input(args: dict) -> str | None:
    """按 RULE_CONTENT_KEYS 顺序取第一个非空串；没有就 None（整工具级规则）。"""
    for key in RULE_CONTENT_KEYS:
        val = (args or {}).get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def dedupe_rules(rules) -> list:
    out, seen = [], set()
    for r in rules or []:
        if not isinstance(r, Rule):
            r = _coerce_rule(r)
            if r is None:
                continue
        k = r.key()
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def apply_updates(rules, new_rules) -> list:
    return dedupe_rules(list(rules or []) + list(new_rules or []))


def _coerce_rule(raw) -> Rule | None:
    if isinstance(raw, dict):
        try:
            return Rule(
                tool_name=str(raw.get("toolName") or raw.get("tool_name") or ""),
                rule_content=raw.get("ruleContent") if raw.get("ruleContent") else None,
                behavior=Behavior(str(raw.get("behavior") or "allow")),
            )
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------- 判权

def _norm_content(text) -> str:
    """规则内容比对前的归一：去首尾空白、压掉连续空白、忽略大小写。

    以前是精确字符串相等：用户定的 deny 规则 `name="jei"` 挡不住 `name="JEI"` /
    `"jei "`；default 档下只是回落成 ASK，但 acceptEdits 档下回落成 ALLOW——模型换个
    大小写就绕过了用户的禁用规则。模组 slug / 文件名 / 版本号都不区分大小写，
    Windows 路径也不区分，所以统一 casefold 比对。
    """
    return " ".join(str(text or "").split()).casefold()


def _matches(rule: Rule, tname: str, content: str | None) -> bool:
    if rule.tool_name != tname:
        return False
    if not rule.rule_content:
        return True
    return _norm_content(rule.rule_content) == _norm_content(content)


def decide(tool_meta, args, mode, rules) -> PermissionResult:
    """tool_meta: tools.TOOL_META 里的条目（或带 readonly/side_effect/risk 的对象）。"""
    meta = tool_meta
    readonly = bool(getattr(meta, "readonly", False))
    side_effect = getattr(meta, "side_effect", "") or "write_local"
    risk = getattr(meta, "risk", "medium") or "medium"
    tname = getattr(meta, "name", "") or ""
    content = rule_content_from_input(args)
    mode = _norm_mode(mode)

    # 1. plan 硬约束：只读模式连 allow 规则都翻不过来
    if mode == PermissionMode.PLAN and not readonly:
        return PermissionResult(
            Decision.DENY,
            reason="当前是「只看不动」模式，不能执行这类操作")

    # 2-4. 规则判定：deny > allow > ask。
    # 注意这里不做跨 behavior 去重——allow 和 deny 允许同时存在，deny 赢。
    norm = []
    for r in rules or []:
        if not isinstance(r, Rule):
            r = _coerce_rule(r)
        if r is not None:
            norm.append(r)
    matched = [r for r in norm if _matches(r, tname, content)]
    for behavior, decision in ((Behavior.DENY, Decision.DENY),
                               (Behavior.ALLOW, Decision.ALLOW),
                               (Behavior.ASK, Decision.ASK)):
        for r in matched:
            if r.behavior == behavior:
                if decision == Decision.ALLOW and not r.rule_content \
                        and side_effect == "delete":
                    # 删除类不吃「整工具级」放行：delete_mod / delete_instance 的参数键
                    # （filename / name）不在 RULE_CONTENT_KEYS 里，确认卡上勾一次
                    # 「以后都允许」生成的就是这种无 ruleContent 的规则，照单全收等于
                    # 以后删什么都不问。带具体目标的放行规则仍然有效。
                    continue
                rid = f"rule.{r.tool_name}.{r.behavior.value}"
                if decision == Decision.DENY:
                    return PermissionResult(Decision.DENY, reason="这条操作被你的规则禁止",
                                            rule_id=rid)
                if decision == Decision.ALLOW:
                    return PermissionResult(Decision.ALLOW, reason="规则允许", rule_id=rid)
                return PermissionResult(Decision.ASK, reason="规则要求先询问", rule_id=rid)

    # 只读工具在任何模式下都放行（规则说要问/禁的上面已经拦过了）
    if readonly:
        return PermissionResult(Decision.ALLOW, reason="只读操作")

    # 5. 模式默认
    if mode in (PermissionMode.YOLO, PermissionMode.BYPASS_PERMISSIONS):
        return PermissionResult(Decision.ALLOW, reason="免确认模式")
    if mode in (PermissionMode.ACCEPT_EDITS, PermissionMode.AUTO, PermissionMode.AUTO_EDIT):
        if side_effect == "delete":
            return PermissionResult(Decision.ASK, reason="删除操作仍需确认")
        return PermissionResult(Decision.ALLOW, reason="写操作直接执行")
    if mode == PermissionMode.BUILD:
        if side_effect in ("delete", "launch"):
            return PermissionResult(Decision.ASK, reason="删除/启动操作仍需确认")
        return PermissionResult(Decision.ALLOW, reason="安装/下载类直接执行")
    if mode == PermissionMode.EDIT:
        if side_effect == "write_local":
            return PermissionResult(Decision.ALLOW, reason="文件类修改直接执行")
        return PermissionResult(Decision.ASK, reason="这类操作需要确认")
    if mode == PermissionMode.DONT_ASK:
        return PermissionResult(Decision.DENY, reason="用户开启了「不询问」模式")
    if risk == "high":
        return PermissionResult(Decision.ASK, reason="高风险操作需要确认")
    return PermissionResult(Decision.ASK, reason="写操作需要确认")


def _norm_mode(mode) -> PermissionMode:
    if isinstance(mode, PermissionMode):
        return mode
    try:
        return PermissionMode(str(mode or "default"))
    except ValueError:
        return PermissionMode.DEFAULT


# ---------------------------------------------------------------- 旧值映射（W1-3）

def normalize_permission_mode(raw_mode, confirm_writes: bool = True) -> str:
    """旧配置平滑映射：standard→default、full→acceptEdits、ai_confirm_writes=False→yolo。

    免确认优先于档位：老用户 mode=full 且关了确认开关，说明意图是全自动。
    """
    mode = str(raw_mode or "").strip()
    if mode in ("", "standard"):
        return "default" if confirm_writes else "yolo"
    if mode == "full":
        return "acceptEdits" if confirm_writes else "yolo"
    if mode == "custom":
        # UI 概念：default 档 + 用户自定义规则；decide() 里按 default 处理
        return "custom"
    try:
        PermissionMode(mode)
        return mode
    except ValueError:
        return "default" if confirm_writes else "yolo"


def permission_note(settings: dict) -> str:
    """把权限档位同步给模型（原 agent._permission_note，按新模式重写）。"""
    mode = normalize_permission_mode((settings or {}).get("ai_permission_mode"),
                                     bool((settings or {}).get("ai_confirm_writes", True)))
    if mode in (PermissionMode.YOLO.value, PermissionMode.BYPASS_PERMISSIONS.value):
        return (
            "[权限设置] 用户选了「全自动」：写操作直接执行，不会弹确认。"
            "你仍要先用一句话说明将要做什么。"
        )
    if mode == PermissionMode.PLAN.value:
        return "[权限设置] 用户选了「只看不动」：你只能查看和诊断，不能安装/删除/改配置。"
    if mode in (PermissionMode.ACCEPT_EDITS.value, PermissionMode.AUTO.value,
                PermissionMode.AUTO_EDIT.value, PermissionMode.BUILD.value):
        return (
            "[权限设置] 写操作会直接执行；删除实例、删除模组前仍会先询问，要等用户点了才执行。"
        )
    if mode == PermissionMode.DONT_ASK.value:
        return "[权限设置] 用户选了「不询问」：需要确认的写操作会被直接拒绝，只读查看照常。"
    if mode == PermissionMode.EDIT.value:
        return "[权限设置] 文件类修改直接执行；安装、删除、启动前会弹确认，要等用户点了才执行。"
    # default / custom：每一步写操作都会弹确认
    return (
        "[权限设置] 安装、删除、禁用、改配置、启动这类写操作执行前都会弹确认，"
        "用户点了才会真的执行；查看类操作不弹。被拒绝时不要重复发起同一操作，改为说明原因。"
    )


# ---------------------------------------------------------------- 规则落盘（W1-5）

PERMISSIONS_FILE = None   # None = 默认 utils.ROOT/ai_permissions.json；测试可覆盖
_STORE_VERSION = 1
# 规则库的读-改-写要在一把锁里做：agent 线程点「以后都允许」(append_rule) 与 UI 线程
# 在权限对话框增删规则 (append_rule / remove_rule) 各自整库快照再落盘，后落盘者会
# 吞掉对方的改动。进程内一把可重入锁就够（两端后端都是单进程多线程）。
_STORE_LOCK = threading.RLock()


def _store_path():
    return PERMISSIONS_FILE if PERMISSIONS_FILE is not None \
        else utils.ROOT / "ai_permissions.json"


def _blank_store() -> dict:
    return {
        "version": _STORE_VERSION,
        "global": {"allow": [], "deny": [], "ask": []},
        "per_instance": {},
    }


def load_rule_store() -> dict:
    with _STORE_LOCK:
        data = utils.read_json(_store_path(), None)
    if not isinstance(data, dict):
        return _blank_store()
    store = _blank_store()
    for bucket in ("allow", "deny", "ask"):
        vals = (data.get("global") or {}).get(bucket)
        if isinstance(vals, list):
            store["global"][bucket] = vals
    per = data.get("per_instance")
    if isinstance(per, dict):
        store["per_instance"] = {
            str(k): {b: (v.get(b) if isinstance(v, dict) and isinstance(v.get(b), list) else [])
                     for b in ("allow", "deny", "ask")}
            for k, v in per.items() if isinstance(v, dict)
        }
    return store


def save_rule_store(store: dict):
    with _STORE_LOCK:
        utils.write_json(_store_path(), store)


def _rules_of(store: dict, section: dict) -> list:
    out = []
    for bucket, behavior in (("allow", Behavior.ALLOW), ("deny", Behavior.DENY),
                             ("ask", Behavior.ASK)):
        for raw in section.get(bucket) or []:
            r = _coerce_rule(raw)
            if r is not None:
                r.behavior = behavior
                out.append(r)
    return out


def load_rules(instance: str | None = None) -> list:
    """先合并 global，再叠加 per_instance[instance]。"""
    store = load_rule_store()
    rules = _rules_of(store, store["global"])
    if instance:
        rules += _rules_of(store, store["per_instance"].get(instance) or {})
    return dedupe_rules(rules)


def append_rule(rule: Rule, instance: str | None = None):
    """把一条规则写进 store：有实例名进 per_instance，否则进 global。"""
    with _STORE_LOCK:
        store = load_rule_store()
        bucket = rule.behavior.value
        entry = {"toolName": rule.tool_name}
        if rule.rule_content:
            entry["ruleContent"] = rule.rule_content
        target = store["per_instance"].setdefault(instance, {"allow": [], "deny": [], "ask": []}) \
            if instance else store["global"]
        lst = target.setdefault(bucket, [])
        keys = {f"{r.get('toolName')}\0{r.get('ruleContent') or ''}" for r in lst}
        if rule.key() not in keys:
            lst.append(entry)
        save_rule_store(store)


def rules_to_json(rules) -> list:
    out = []
    for r in dedupe_rules(rules):
        entry = {"toolName": r.tool_name, "behavior": r.behavior.value}
        if r.rule_content:
            entry["ruleContent"] = r.rule_content
        out.append(entry)
    return out


_BEHAVIOR_LABELS = {Behavior.ALLOW: "允许", Behavior.DENY: "禁止", Behavior.ASK: "每次问"}


def list_stored_rules() -> list:
    """平铺 store 里的规则（global + per_instance），供设置界面展示。

    每行带 instance（全局为空串）让前端自己拼范围文案；scope 是现成的中文标签，
    Qt 端直接用。
    """
    store = load_rule_store()
    out = []
    for bucket, behavior in (("allow", Behavior.ALLOW), ("deny", Behavior.DENY),
                             ("ask", Behavior.ASK)):
        for raw in store["global"].get(bucket) or []:
            r = _coerce_rule(raw)
            if r is None:
                continue
            r.behavior = behavior
            out.append({
                "key": r.key(), "toolName": r.tool_name,
                "ruleContent": r.rule_content or "",
                "behavior": behavior.value,
                "behavior_label": _BEHAVIOR_LABELS[behavior],
                "instance": "",
                "scope": "全局",
            })
    for inst, section in store["per_instance"].items():
        for bucket, behavior in (("allow", Behavior.ALLOW), ("deny", Behavior.DENY),
                                 ("ask", Behavior.ASK)):
            for raw in (section or {}).get(bucket) or []:
                r = _coerce_rule(raw)
                if r is None:
                    continue
                r.behavior = behavior
                out.append({
                    "key": r.key(), "toolName": r.tool_name,
                    "ruleContent": r.rule_content or "",
                    "behavior": behavior.value,
                    "behavior_label": _BEHAVIOR_LABELS[behavior],
                    "instance": inst,
                    "scope": f"实例 {inst}",
                })
    return out


def remove_rule(key: str, instance: str | None = None) -> bool:
    """按 Rule.key() 删规则。

    instance 为 None 时在所有段里找（旧行为）；传 "" 只删全局那条，传实例名只删
    该实例那条——同一条规则可能全局、实例各存一份，界面上点删哪行就该只删哪行。
    返回是否删到了。
    """
    with _STORE_LOCK:
        store = load_rule_store()
        if instance is None:
            sections = [store["global"]] + list(store["per_instance"].values())
        elif instance == "":
            sections = [store["global"]]
        else:
            sections = [store["per_instance"].get(instance) or {}]
        removed = False
        for section in sections:
            for bucket in ("allow", "deny", "ask"):
                lst = section.get(bucket) or []
                keep = []
                for raw in lst:
                    r = _coerce_rule(raw)
                    if r is not None and r.key() == key:
                        removed = True
                        continue
                    keep.append(raw)
                section[bucket] = keep
        if removed:
            save_rule_store(store)
        return removed

# -*- coding: utf-8 -*-
"""LLM function-calling 工具：只包 BackendAPI / 诊断 / 冲突 / 配置。"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from mclauncher import mods as mods_mod
from mclauncher.config import CONFIG
from mclauncher.downloader import DownloadManager
from mclauncher.i18n import tr
from mclauncher.instances import JAVA_AUTO, Instance, unique_instance_name
from mclauncher.mods import detect_loader, detect_mc_version

from . import artifacts
from . import conflict as conflict_mod
from . import diagnose as diagnose_mod
from . import modconfig as modconfig_mod
from . import trace
from .defaults import MAX_TOOL_RESULT


@dataclass(frozen=True)
class ToolMeta:
    name: str
    readonly: bool
    # none | read | network | write_local | write_external | delete | launch
    side_effect: str
    risk: str = "low"          # low | medium | high
    long_running: bool = False


# 并行依据：readonly and side_effect in ("none", "read", "network")
# 独占依据：side_effect in ("delete", "launch") 或 name == "ask_user"
TOOL_META: dict = {}


def _schema(name, desc, props, required=None, *,
            readonly: bool, side_effect: str, risk: str = "low",
            long_running: bool = False):
    TOOL_META[name] = ToolMeta(name=name, readonly=readonly,
                               side_effect=side_effect, risk=risk,
                               long_running=long_running)
    params = {
        "type": "object",
        "properties": props,
    }
    if required:
        params["required"] = required
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": params,
        },
    }


TOOL_SCHEMAS = [
    _schema("ask_user",
            "向用户弹出结构化选择题。需要用户选实例、加载器、搜到多个结果、冲突留哪个时必须用这个，不要只在文字里问。"
            "界面会自动加「其他」让用户自己填。没选完之前不要调用 install_*。"
            "用户选完后你必须立刻再调对应工具，不能结束。",
            {
                "title": {"type": "string", "description": "可选，整组题的小标题"},
                "prompt": {"type": "string", "description": "单题时的问题"},
                "allow_multiple": {"type": "boolean", "description": "单题时是否可多选，默认 false"},
                "options": {
                    "type": "array",
                    "description": "单题选项。每项可以是字符串，或 {id, label}",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                        },
                    },
                },
                "questions": {
                    "type": "array",
                    "description": "多题时用。每题 {id, prompt, allow_multiple, options:[{id,label}]}，至少 2 个选项",
                    "items": {"type": "object"},
                },
            },
            readonly=True, side_effect="none"),
    _schema("get_launcher_state", "查看实例、已装版本、Java、模组数量等当前状态", {},
            readonly=True, side_effect="none"),
    _schema("list_instances", "列出全部实例", {},
            readonly=True, side_effect="none"),
    _schema("list_installed_versions", "列出某实例已安装的游戏版本", {
        "instance": {"type": "string", "description": "实例名，空则用默认"},
    }, readonly=True, side_effect="none"),
    _schema("search_versions", "搜索可下载的 Minecraft 版本号", {
        "query": {"type": "string", "description": "如 1.20.1 或 25w"},
        "kind": {"type": "string", "description": "release / snapshot / all"},
    }, ["query"], readonly=True, side_effect="network"),
    _schema("search_mods",
            "搜索模组（支持中文名）。同一轮用户请求只调用一次；搜完必须 ask_user 让用户选，禁止换词再搜。", {
        "query": {"type": "string"},
        "source": {"type": "string", "description": "全部 / Modrinth / CurseForge"},
    }, ["query"], readonly=True, side_effect="network"),
    _schema("search_modpacks",
            "搜索整合包（支持中文名）。同一轮只调用一次，搜完 ask_user，禁止换词再搜。", {
        "query": {"type": "string"},
        "source": {"type": "string", "description": "全部 / Modrinth / CurseForge"},
    }, ["query"], readonly=True, side_effect="network"),
    _schema("list_mods", "列出实例已装模组（含禁用）", {
        "instance": {"type": "string"},
    }, readonly=True, side_effect="read"),
    _schema("install_game",
            "真正开始下载/安装 Minecraft。用户已选定版本后必须调用这个，否则不会下载。"
            "纯原版 loader 填「无」。", {
        "version": {"type": "string", "description": "如 1.20.1"},
        "loader": {"type": "string", "description": "无 / Fabric / Forge / Quilt / NeoForge。纯原版必须填 无"},
        "loader_version": {"type": "string"},
        "instance": {"type": "string"},
    }, ["version"], readonly=False, side_effect="write_local", risk="high",
        long_running=True),
    _schema("install_mod", "安装模组。优先传搜索结果里的 slug 或 id", {
        "name": {"type": "string", "description": "显示名或 slug"},
        "instance": {"type": "string"},
        "source": {"type": "string"},
        "slug": {"type": "string"},
        "id": {"type": "string", "description": "CurseForge 数字 id"},
    }, ["name"], readonly=False, side_effect="write_local", risk="medium",
        long_running=True),
    _schema("install_modpack", "安装整合包。建议先 create_instance", {
        "name": {"type": "string"},
        "instance": {"type": "string"},
        "source": {"type": "string"},
        "slug": {"type": "string"},
        "id": {"type": "string"},
    }, ["name"], readonly=False, side_effect="write_local", risk="high",
        long_running=True),
    _schema("install_shader", "安装光影包", {
        "name": {"type": "string"}, "instance": {"type": "string"},
        "source": {"type": "string"}, "slug": {"type": "string"},
    }, ["name"], readonly=False, side_effect="write_local", risk="low",
        long_running=True),
    _schema("install_resourcepack", "安装资源包", {
        "name": {"type": "string"}, "instance": {"type": "string"},
        "source": {"type": "string"}, "slug": {"type": "string"},
    }, ["name"], readonly=False, side_effect="write_local", risk="low",
        long_running=True),
    _schema("install_datapack", "安装数据包", {
        "name": {"type": "string"}, "instance": {"type": "string"},
        "source": {"type": "string"}, "slug": {"type": "string"},
    }, ["name"], readonly=False, side_effect="write_local", risk="low",
        long_running=True),
    _schema("search_content",
            "搜索光影 / 资源包 / 数据包（支持中文名）。装之前先用它拿 slug 或 id。", {
        "kind": {"type": "string", "description": "shader / resourcepack / datapack"},
        "query": {"type": "string"},
        "source": {"type": "string", "description": "全部 / Modrinth / CurseForge"},
    }, ["kind", "query"], readonly=True, side_effect="network"),
    _schema("search_worlds", "搜索地图存档（CurseForge 世界）", {
        "query": {"type": "string"},
        "source": {"type": "string"},
    }, ["query"], readonly=True, side_effect="network"),
    _schema("install_world", "安装地图存档到实例的 saves", {
        "name": {"type": "string"}, "instance": {"type": "string"},
        "source": {"type": "string"}, "slug": {"type": "string"},
        "id": {"type": "string", "description": "CurseForge 数字 id"},
    }, ["name"], readonly=False, side_effect="write_local", risk="medium",
        long_running=True),
    _schema("create_instance", "新建隔离实例，装整合包前建议先建", {
        "name": {"type": "string"},
    }, ["name"], readonly=False, side_effect="write_local", risk="medium"),
    _schema("delete_instance", "删除整个实例（危险）", {
        "name": {"type": "string"},
    }, ["name"], readonly=False, side_effect="delete", risk="high"),
    _schema("delete_mod", "删除模组文件", {
        "filename": {"type": "string"}, "instance": {"type": "string"},
    }, ["filename"], readonly=False, side_effect="delete", risk="high"),
    _schema("disable_mod", "禁用模组（改名为 .disabled，可恢复）", {
        "filename": {"type": "string"}, "instance": {"type": "string"},
    }, ["filename"], readonly=False, side_effect="write_local", risk="medium"),
    _schema("enable_mod", "重新启用已禁用模组", {
        "filename": {"type": "string"}, "instance": {"type": "string"},
    }, ["filename"], readonly=False, side_effect="write_local", risk="medium"),
    _schema("get_java_list", "列出已安装 Java", {},
            readonly=True, side_effect="none"),
    _schema("download_java", "下载 Adoptium Java", {
        "major": {"type": "string", "description": "8 / 11 / 17 / 21"},
    }, ["major"], readonly=False, side_effect="write_local", risk="medium",
        long_running=True),
    _schema("launch_game", "启动游戏。不填则用默认实例和已装版本", {
        "instance": {"type": "string"},
        "version": {"type": "string"},
        "username": {"type": "string"},
        "memory_mb": {"type": "integer"},
    }, readonly=False, side_effect="launch", risk="high"),
    _schema("diagnose_launch", "分析启动失败：规则扫 latest.log 和崩溃报告", {
        "instance": {"type": "string"},
    }, readonly=True, side_effect="read"),
    _schema("get_latest_log", "读取 latest.log 末尾", {
        "instance": {"type": "string"},
    }, readonly=True, side_effect="read"),
    _schema("get_crash_report", "读取最新崩溃报告", {
        "instance": {"type": "string"},
    }, readonly=True, side_effect="read"),
    _schema("scan_mod_conflicts", "扫描模组冲突、缺依赖、加载器不匹配", {
        "instance": {"type": "string"},
    }, readonly=True, side_effect="read"),
    _schema("inspect_mod", "解析单个模组 jar 的元数据", {
        "filename": {"type": "string"}, "instance": {"type": "string"},
    }, ["filename"], readonly=True, side_effect="read"),
    _schema("list_mod_configs", "列出实例 config 下的配置文件", {
        "instance": {"type": "string"},
        "prefix": {"type": "string", "description": "子目录或文件名前缀"},
    }, readonly=True, side_effect="read"),
    _schema("read_mod_config", "读取某个配置文件", {
        "path": {"type": "string", "description": "相对 config/ 的路径"},
        "instance": {"type": "string"},
    }, ["path"], readonly=True, side_effect="read"),
    _schema("write_mod_config", "写入配置文件（会先备份 .bak）", {
        "path": {"type": "string"},
        "content": {"type": "string", "description": "完整文件内容"},
        "instance": {"type": "string"},
    }, ["path", "content"], readonly=False, side_effect="write_local", risk="high"),
    _schema("read_artifact", "回读之前被存盘的超长工具结果。传结果摘要里给的文件名", {
        "artifact_id": {"type": "string",
                        "description": "如 20260918-221533-a1b2c3.txt"},
        "offset": {"type": "integer", "description": "起始行（0 起）"},
        "limit": {"type": "integer", "description": "读取行数，默认 200"},
    }, ["artifact_id"], readonly=True, side_effect="read"),
    _schema("dispatch_subagent",
            "派发一个独立的子任务给只读子代理去跑（查状态、搜资料、读日志、扫冲突这类），"
            "子代理跑完把结论带回来。多步骤的调研活用它，别把主对话搞成一长串中间步骤。", {
        "task": {"type": "string", "description": "子任务一句话说清楚要干什么"},
        "context": {"type": "string", "description": "相关背景（实例名/报错原文等），可选"},
    }, ["task"], readonly=True, side_effect="none"),
    _schema("update_plan",
            "维护本次任务的待办清单并在界面展示。三步以上的活先出计划再动手；"
            "每次更新都传完整清单，状态只能是 pending / in_progress / completed。", {
        "items": {
            "type": "array",
            "description": "完整待办列表",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "这一步要干什么"},
                    "status": {"type": "string",
                               "description": "pending / in_progress / completed"},
                },
            },
        },
    }, ["items"], readonly=True, side_effect="none"),
]


def is_write_tool(name: str) -> bool:
    meta = TOOL_META.get(name)
    return not (meta and meta.readonly) if name in TOOL_META else False


# ---------------------------------------------------------------- 工具按需加载
# 每轮全量声明 34 个 schema 的固定开销太大（见改造报告实测：全量 ≈5.3k token）。
# 策略：高频核心常驻，其余按对话关键词整组追加；选漏了由 agent 全量重发兜底，
# 宁可多声明也不能让模型的调用悬空。

_CORE_TOOLS = (
    "ask_user", "get_launcher_state", "list_instances", "list_mods",
    "search_mods", "install_mod", "install_modpack", "create_instance",
    "launch_game", "diagnose_launch", "get_latest_log", "get_crash_report",
    "write_mod_config", "dispatch_subagent", "update_plan",
)

# (关键词组, 追加工具组)：命中任一关键词就整组声明
_KEYWORD_TOOLS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("版本", "快照", "version", "snapshot", "release", "更新到", "升级到"),
     ("search_versions", "list_installed_versions", "install_game")),
    (("整合包", "modpack", "难必安", "RLCraft"),
     ("search_modpacks", "install_modpack")),
    (("光影", "shader", "BSL", "Complementary"),
     ("search_content", "install_shader")),
    (("资源包", "材质", "resourcepack", "texture"),
     ("search_content", "install_resourcepack")),
    (("数据包", "datapack"),
     ("search_content", "install_datapack")),
    (("地图", "存档", "world", "saves"),
     ("search_worlds", "install_world")),
    (("java", "Java", "JAVA", "运行时", "JRE"),
     ("get_java_list", "download_java")),
    (("冲突", "缺依赖", "不兼容", "conflict", "inspect"),
     ("scan_mod_conflicts", "inspect_mod")),
    (("配置", "toml", ".ini", ".cfg", "选项文件"),
     ("list_mod_configs", "read_mod_config", "write_mod_config")),
    (("删除", "删掉", "卸载", "移除", "delete", "uninstall", "remove"),
     ("delete_mod", "delete_instance", "disable_mod", "enable_mod")),
    (("禁用", "启用", "disable", "enable"),
     ("disable_mod", "enable_mod", "list_mods")),
)


def _selection_text(messages: list, limit_per: int = 4000, last_n: int = 12) -> str:
    """拼关键词扫描面：最近若干条 user / tool 消息的正文。"""
    rows = []
    for m in (messages or [])[-last_n:]:
        if not isinstance(m, dict):
            continue
        if m.get("role") in ("user", "tool"):
            rows.append(str(m.get("content") or "")[:limit_per])
    return "\n".join(rows)


def select_tool_schemas(messages: list, settings: dict | None = None,
                        force_all: bool = False) -> list:
    """按对话内容声明本轮需要的工具 schema（2.2 按需加载）。

    子代理模式（settings.ai_subagent）：只声明只读工具，且不带 dispatch_subagent
    本身——子代理不再派生子代理，也不写磁盘。
    兜底：核心集为空或过滤后一无所有时回退全量——选择器永远只降开销，不降能力。
    """
    subagent = bool((settings or {}).get("ai_subagent"))
    if force_all:
        wanted = {s["function"]["name"] for s in TOOL_SCHEMAS}
    else:
        text = _selection_text(messages)
        names: list[str] = list(_CORE_TOOLS)
        for keys, extra in _KEYWORD_TOOLS:
            if any(k in text for k in keys):
                for t in extra:
                    if t not in names:
                        names.append(t)
        # 上一轮结果过长存了文件 → 必须能 read_artifact 回读
        if "cache/ai_results/" in text or "[结果过长" in text:
            if "read_artifact" not in names:
                names.append("read_artifact")
        wanted = set(names)
    if subagent:
        wanted = {n for n in wanted if n in TOOL_META and TOOL_META[n].readonly}
        wanted.discard("dispatch_subagent")
    out = [s for s in TOOL_SCHEMAS if s["function"]["name"] in wanted]
    if out:
        return out
    if subagent:
        # 只读兜底：核心里的只读工具
        ro_core = [s["function"]["name"] for s in TOOL_SCHEMAS
                   if s["function"]["name"] in _CORE_TOOLS
                   and TOOL_META.get(s["function"]["name"])
                   and TOOL_META[s["function"]["name"]].readonly
                   and s["function"]["name"] != "dispatch_subagent"]
        return [s for s in TOOL_SCHEMAS if s["function"]["name"] in ro_core] \
            or [TOOL_SCHEMAS[0]]
    return list(TOOL_SCHEMAS)


def is_ask_tool(name: str) -> bool:
    return name == "ask_user"


def normalize_ask_args(args: dict) -> list[dict]:
    """统一成 [{id, prompt, allow_multiple, options:[{id,label}]}]，「其他」永远在最后。"""
    raw = (args or {}).get("questions")
    if not raw:
        raw = [{
            "id": (args or {}).get("id") or "q1",
            "prompt": (args or {}).get("prompt") or (args or {}).get("title") or "请选择",
            "allow_multiple": bool((args or {}).get("allow_multiple")),
            "options": (args or {}).get("options") or [],
        }]
    out = []
    for i, q in enumerate(raw if isinstance(raw, list) else [raw]):
        if not isinstance(q, dict):
            continue
        opts = []
        for j, o in enumerate(q.get("options") or []):
            if isinstance(o, str):
                oid, label = f"opt_{j}", o.strip()
            elif isinstance(o, dict):
                oid = str(o.get("id") or f"opt_{j}")
                label = str(o.get("label") or o.get("name") or oid).strip()
            else:
                continue
            if not label:
                continue
            opts.append({"id": oid, "label": label})
        has_other = any(
            x["id"] == "other" or x["label"].rstrip("。.") in ("其他", "其它")
            for x in opts
        )
        if not has_other:
            opts.append({"id": "other", "label": "其他"})
        if len(opts) < 2:
            opts.insert(0, {"id": "skip", "label": "先不选"})
        out.append({
            "id": str(q.get("id") or f"q{i + 1}"),
            "prompt": str(q.get("prompt") or q.get("title") or "请选择"),
            "allow_multiple": bool(q.get("allow_multiple")),
            "options": opts,
        })
    if not out:
        out.append({
            "id": "q1",
            "prompt": str((args or {}).get("prompt") or "请选择"),
            "allow_multiple": False,
            "options": [
                {"id": "skip", "label": "先不选"},
                {"id": "other", "label": "其他"},
            ],
        })
    return out


def normalize_ask_answer(questions: list, answered):
    """把两端形状不同的 ask_user 应答归一成一种，再喂给模型。

    Qt 发 ``{qid: {ids, labels, other_text}}``，WPF 发 ``{qid: {picked: [{id,label}], other}}``；
    以前原样 json.dumps 给模型，没有 schema，模型两边都要猜。统一成
    ``{"answers": {qid: {ids, labels, other_text}}, "summary": "问题: 选项, …"}``。
    字符串 / None 原样返回（None = 用户取消）。
    """
    if answered is None or isinstance(answered, str):
        return answered
    if not isinstance(answered, dict):
        return answered
    qmap = {}
    for q in questions or []:
        if isinstance(q, dict):
            qmap[str(q.get("id") or "")] = q
    answers = {}
    lines = []
    for qid, val in answered.items():
        ids: list[str] = []
        labels: list[str] = []
        other = ""
        picked = None
        if isinstance(val, dict):
            if "picked" in val:
                picked = val.get("picked") or []
            else:
                ids = [str(x) for x in (val.get("ids") or [])]
                labels = [str(x) for x in (val.get("labels") or [])]
            other = str(val.get("other_text") or val.get("other") or "").strip()
        elif isinstance(val, list):
            picked = val
        elif val is not None:
            ids = [str(val)]
        if picked is not None:
            for p in picked:
                if isinstance(p, dict):
                    pid = str(p.get("id") or "")
                    ids.append(pid)
                    labels.append(str(p.get("label") or pid))
                elif p is not None:
                    ids.append(str(p))
        q = qmap.get(str(qid)) or {}
        opt_labels = {
            str(o.get("id") or ""): str(o.get("label") or "")
            for o in (q.get("options") or []) if isinstance(o, dict)
        }
        if len(labels) < len(ids):
            labels = [opt_labels.get(i) or i for i in ids]
        if other and "other" not in ids:
            ids.append("other")
            labels.append(opt_labels.get("other") or tr("其他"))
        answers[str(qid)] = {"ids": ids, "labels": labels, "other_text": other}
        prompt = str(q.get("prompt") or qid)
        shown = ", ".join(x for x in labels if x) or "（未选）"
        if other:
            shown += f"（补充：{other}）"
        lines.append(f"{prompt}: {shown}")
    return {"answers": answers, "summary": "\n".join(lines)}


def _clip(obj, tool_name: str = "") -> str:
    if isinstance(obj, str):
        text = obj
    else:
        text = json.dumps(obj, ensure_ascii=False, indent=2)
    if len(text) > MAX_TOOL_RESULT:
        # 超长结果落盘，给模型路径 + 前 120 行；细节用 read_artifact 回读
        return artifacts.store(text, tool_name)
    return text


def _cjk(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in (s or ""))


def _inst_name(backend, args) -> str:
    name = (args.get("instance") or "").strip()
    return name or CONFIG.get("default_instance", "default") or "default"


def _inst(backend, args) -> Instance:
    return backend._instance(_inst_name(backend, args))


def affected_paths(backend, name: str, args: dict) -> list:
    """写/删工具将会触及的路径；目录条目按「目录范围」快照（回滚清新增项）。

    checkpoint 快照用；返回空 = 该工具没有已知的落盘目标（如老后端缺方法）。
    """
    args = args or {}
    try:
        inst = _inst(backend, args)
        inst_dir = inst.path
    except Exception:  # noqa: BLE001
        inst_dir = None
    if inst_dir is None:
        return []
    mods_dir = inst_dir / "mods"
    if name == "write_mod_config":
        rel = str(args.get("path") or "").replace("\\", "/").lstrip("/")
        if not rel or ".." in Path(rel).parts:
            return []
        return [inst_dir / "config" / rel]
    if name == "delete_mod":
        fname = str(args.get("filename") or "")
        return [mods_dir / fname, mods_dir / (fname + ".disabled")]
    if name in ("disable_mod", "enable_mod"):
        fname = str(args.get("filename") or "")
        return [mods_dir / fname, mods_dir / (fname + ".disabled")]
    if name == "delete_instance":
        return [inst_dir]
    if name == "create_instance":
        try:
            return [inst_dir.parent / unique_instance_name(str(args.get("name") or "游戏"))]
        except Exception:  # noqa: BLE001
            return []
    if name == "install_mod":
        return [mods_dir]
    if name == "install_shader":
        return [inst_dir / "shaderpacks"]
    if name == "install_resourcepack":
        return [inst_dir / "resourcepacks"]
    if name == "install_datapack":
        return [inst_dir / "datapacks"]
    if name == "install_world":
        return [inst_dir / "saves"]
    if name == "install_modpack":
        return [inst_dir]
    if name == "install_game":
        return [inst.versions_dir()]
    if name == "download_java":
        try:
            return [CONFIG.java_dir]
        except Exception:  # noqa: BLE001
            return []
    return []


def _merge_cache(old, rows):
    out = list(old or [])
    seen = {(r.get("source"), r.get("id") or r.get("slug") or r.get("name")) for r in out}
    for r in rows or []:
        mark = (r.get("source"), r.get("id") or r.get("slug") or r.get("name"))
        if mark in seen:
            continue
        seen.add(mark)
        out.append(r)
    return out[-80:]


def _trim_hits(rows, n=12):
    out = []
    for r in rows[:n]:
        out.append({
            "name": r.get("name"),
            "source": r.get("source"),
            "slug": r.get("slug"),
            "id": r.get("id"),
            "author": r.get("author"),
            "downloads": r.get("downloads"),
            "description": (r.get("description") or "")[:160],
        })
    return out


def _count_mod_jars(inst: Instance) -> int:
    mods_dir = inst.path / "mods"
    n = 0
    try:
        with os.scandir(mods_dir) as it:
            for e in it:
                name = e.name.lower()
                if name.endswith(".jar") or name.endswith(".jar.disabled") or name.endswith(".disabled"):
                    n += 1
    except OSError:
        return 0
    return n


def runtime_context(backend) -> str:
    try:
        insts = backend.get_instances()
        default = CONFIG.get("default_instance", "default")
        javs = backend.get_java_list(False)
        lines = [f"默认实例: {default}", f"已装 Java: {len(javs)} 个"]
        for row in insts[:8]:
            name = row.get("name")
            n_mods = 0
            loader = None
            mc = row.get("mc_version") or None
            try:
                inst = backend._instance(name)
                n_mods = _count_mod_jars(inst)
                loader = detect_loader(inst)
                if not mc:
                    mc = detect_mc_version(inst)
            except Exception:
                pass
            lines.append(
                f"- {name}: MC {mc or '?'} / {loader or '原版'} / "
                f"版本{row.get('versions')}个 / 模组{n_mods}个"
                + (f" / 整合包 {row.get('pack')}" if row.get("pack") else "")
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"状态读取失败: {exc}"


_CJK_DM = None


def _cjk_downloader() -> DownloadManager:
    """中文搜索用的下载器：整个进程复用一个，别每搜一次就新建一个 Session。"""
    global _CJK_DM
    if _CJK_DM is None:
        _CJK_DM = DownloadManager(threads=2)
    return _CJK_DM


def _search_mods(backend, query, source):
    src = source or "全部"
    rows = []
    if _cjk(query):
        try:
            hits = mods_mod.search_mods_chinese(
                _cjk_downloader(), query, limit=20, api_key=CONFIG.get("curseforge_api_key"))
            for h in hits:
                rows.append({
                    "name": h.get("title") or h.get("name"),
                    "source": h.get("source"),
                    "slug": h.get("slug"),
                    "id": h.get("id"),
                    "author": h.get("author"),
                    "downloads": h.get("downloads"),
                    "description": h.get("description") or h.get("summary") or "",
                })
        except Exception:
            rows = []
    if rows:
        backend._mod_cache = _merge_cache(getattr(backend, "_mod_cache", None), rows)
        return _trim_hits(rows)
    if src in ("全部", "all", ""):
        seen = set()
        merged = []
        for s in ("Modrinth", "CurseForge"):
            for r in backend.search_mods(query, s):
                mark = (r.get("source"), r.get("id") or r.get("slug") or r.get("name"))
                if mark in seen:
                    continue
                seen.add(mark)
                merged.append(r)
        backend._mod_cache = _merge_cache(getattr(backend, "_mod_cache", None), merged)
        return _trim_hits(merged)
    rows = backend.search_mods(query, src)
    backend._mod_cache = _merge_cache(getattr(backend, "_mod_cache", None), rows)
    return _trim_hits(rows)


def _search_modpacks(backend, query, source):
    src = source or "全部"
    if src in ("全部", "all", ""):
        seen = set()
        merged = []
        for s in ("Modrinth", "CurseForge"):
            for r in backend.search_modpacks(query, s):
                mark = (r.get("source"), r.get("id") or r.get("slug") or r.get("name"))
                if mark in seen:
                    continue
                seen.add(mark)
                merged.append(r)
        return _trim_hits(merged)
    return _trim_hits(backend.search_modpacks(query, src))


# 「离线模式」是两端后端共用的协议哨兵：Qt 门面比对 tr() 后的译文，桥两种都认。
# 这里两种写法都排除，英文界面下才不会把 "Offline mode" 当成一个正版账号选中。
_OFFLINE_KEY = "离线模式"


def _is_offline_name(name) -> bool:
    text = str(name or "")
    return not text or text == _OFFLINE_KEY or text == tr(_OFFLINE_KEY)


def _default_account(backend, accounts) -> str:
    """launch_game 没指明账号时的选法：当前激活账号 > 第一个非离线账号 > 离线。"""
    mgr = getattr(backend, "accounts", None)
    get_active = getattr(mgr, "get_active", None)
    if callable(get_active):
        try:
            acc = get_active()
        except Exception:
            acc = None
        name = acc.get("name") if isinstance(acc, dict) else ""
        if name and not _is_offline_name(name) and name in (accounts or []):
            return name
    ms = [a for a in (accounts or []) if not _is_offline_name(a)]
    return ms[0] if ms else tr(_OFFLINE_KEY)


def confirm_label(name: str, args: dict) -> str:
    """确认卡上的一句话。原样透传到 Qt / WPF 的确认卡，所以在这里就要按界面语言翻好。"""
    inst = args.get("instance") or tr("默认实例")
    fmt = {
        "install_game": tr("安装游戏 {version} {loader} → {inst}"),
        "install_mod": tr("安装模组 {name} → {inst}"),
        "install_modpack": tr("安装整合包 {name} → {inst}"),
        "install_shader": tr("安装光影 {name} → {inst}"),
        "install_resourcepack": tr("安装资源包 {name} → {inst}"),
        "install_datapack": tr("安装数据包 {name} → {inst}"),
        "install_world": tr("安装地图 {name} → {inst}"),
        "download_java": tr("下载 Java {major}"),
        "launch_game": tr("启动 {version} @ {inst}"),
        "create_instance": tr("新建实例 {name}"),
        "delete_instance": tr("删除实例 {name}（不可恢复）"),
        "delete_mod": tr("删除模组 {filename} @ {inst}"),
        "disable_mod": tr("禁用模组 {filename} @ {inst}"),
        "enable_mod": tr("启用模组 {filename} @ {inst}"),
        "write_mod_config": tr("改配置 {path} @ {inst}"),
        "plan_approval": tr("批准这份计划并继续？{n} 项待办"),
    }
    if name == "ask_user":
        return args.get("prompt") or args.get("title") or tr("请选择")
    template = fmt.get(name)
    if template is None:
        return tr("执行 {name}").format(name=name)
    fields = {
        "inst": inst,
        "version": args.get("version") or (tr("当前版本") if name == "launch_game" else ""),
        "loader": args.get("loader") or "",
        "name": args.get("name") or "",
        "major": args.get("major") or "",
        "filename": args.get("filename") or "",
        "path": args.get("path") or "",
        "n": len(args.get("items") or []) if name == "plan_approval" else "",
    }
    try:
        return " ".join(template.format(**fields).split())
    except (KeyError, IndexError, ValueError):
        return template


def execute_tool(backend, name: str, args: dict, wait=True, cancelled=None):
    args = args or {}
    inst_name = _inst_name(backend, args)

    if name == "ask_user":
        return "ask_user 由界面处理"
    if name == "get_launcher_state":
        return runtime_context(backend)
    if name == "list_instances":
        return backend.get_instances()
    if name == "list_installed_versions":
        return backend.get_installed_versions(inst_name)
    if name == "search_versions":
        q = (args.get("query") or "").lower()
        kind = (args.get("kind") or "all").lower()
        rows = backend.get_version_list() or []
        if not rows:
            rows = backend.fetch_version_list()
        out = []
        for r in rows:
            vid = str(r.get("version") or "")
            if q and q not in vid.lower():
                continue
            if kind not in ("", "all") and (r.get("type") or "") != kind:
                continue
            out.append(r)
            if len(out) >= 20:
                break
        return out or "没有匹配版本"
    if name == "search_mods":
        return _search_mods(backend, args.get("query") or "", args.get("source") or "全部")
    if name == "search_modpacks":
        rows = _search_modpacks(backend, args.get("query") or "", args.get("source") or "全部")
        backend._pack_cache = _merge_cache(getattr(backend, "_pack_cache", None), rows if isinstance(rows, list) else [])
        return rows
    if name == "list_mods":
        return mods_mod.list_instance_mod_entries(backend._instance(inst_name))
    if name == "install_game":
        # 不装加载器就传空串：两个后端和 game_install 都认 ""，而硬编码「无」在英文
        # 界面下会原样拼进任务标题（"Install game 1.20.1 + 无"）。
        loader = str(args.get("loader") or "").strip()
        if loader.lower() in ("无", "none", "vanilla"):
            loader = ""
        tid = backend.install_game(
            args.get("version"), loader,
            args.get("loader_version") or "", inst_name)
        return backend.wait_task(tid, cancelled=cancelled) if wait else {"task_id": tid, "queued": True}
    if name == "install_mod":
        extra = {
            "instance": inst_name,
            "source": args.get("source") or "",
            "slug": args.get("slug") or "",
            "id": args.get("id") or "",
            "name": args.get("name"),
        }
        tid = backend.install_mod(args.get("name"), inst_name, extra)
        return backend.wait_task(tid, cancelled=cancelled) if wait else {"task_id": tid, "queued": True}
    if name == "install_modpack":
        extra = {
            "instance": inst_name,
            "source": args.get("source") or "",
            "slug": args.get("slug") or "",
            "id": args.get("id") or "",
            "name": args.get("name"),
        }
        src = extra.get("source") or "Modrinth"
        tid = backend.install_modpack(args.get("name"), src, extra)
        return backend.wait_task(tid, cancelled=cancelled) if wait else {"task_id": tid, "queued": True}
    if name == "install_shader":
        extra = {"instance": inst_name, "source": args.get("source") or "", "slug": args.get("slug") or ""}
        tid = backend.install_shader(args.get("name"), inst_name, extra)
        return backend.wait_task(tid, cancelled=cancelled) if wait else {"task_id": tid, "queued": True}
    if name == "install_resourcepack":
        extra = {"instance": inst_name, "source": args.get("source") or "", "slug": args.get("slug") or ""}
        tid = backend.install_resourcepack(args.get("name"), inst_name, extra)
        return backend.wait_task(tid, cancelled=cancelled) if wait else {"task_id": tid, "queued": True}
    if name == "install_datapack":
        extra = {"instance": inst_name, "source": args.get("source") or "", "slug": args.get("slug") or ""}
        tid = backend.install_datapack(args.get("name"), inst_name, extra)
        out = backend.wait_task(tid, cancelled=cancelled) if wait else {"task_id": tid, "queued": True}
        note = "数据包在实例 datapacks 目录。进游戏后还要拷进对应存档的 datapacks 才会生效。"
        if isinstance(out, dict):
            out["hint"] = note
            return out
        return f"{out}\n{note}"
    if name == "search_content":
        kind = str(args.get("kind") or "shader").lower()
        finder = {
            "shader": getattr(backend, "search_shaders", None),
            "shaderpack": getattr(backend, "search_shaders", None),
            "resourcepack": getattr(backend, "search_resourcepacks", None),
            "datapack": getattr(backend, "search_datapacks", None),
        }.get(kind)
        if not callable(finder):
            return f"未知内容类型: {kind}"
        rows = finder(args.get("query") or "", args.get("source") or "全部", {})
        return _trim_hits(rows) if rows else "没有搜到匹配内容"
    if name == "search_worlds":
        rows = backend.search_worlds(
            args.get("query") or "", args.get("source") or "CurseForge", {})
        return _trim_hits(rows) if rows else "没有搜到匹配地图"
    if name == "install_world":
        extra = {
            "instance": inst_name,
            "source": args.get("source") or "CurseForge",
            "slug": args.get("slug") or "",
            "id": args.get("id") or "",
            "name": args.get("name"),
        }
        tid = backend.install_world(args.get("name"), inst_name, extra)
        return backend.wait_task(tid, cancelled=cancelled) if wait else {"task_id": tid, "queued": True}
    # 建实例 / 禁用 / 启用一律走 backend 的同名方法（和 delete_mod 一样）：
    # 两个后端都有，而且各自负责通知界面刷新。以前这里直接 backend.ui_changed.emit()，
    # 桥的 BackendAPI 没有这个 Signal，动作做完才 AttributeError，模型收到「工具失败」
    # 就会重试——实例建两个、模组「不存在」。
    if name == "create_instance":
        raw = args.get("name") or "游戏"
        new_name = unique_instance_name(raw)
        backend.create_instance(new_name)
        return f"已创建实例 {new_name}"
    if name == "delete_instance":
        backend.delete_instance(args.get("name"))
        return f"已删除实例 {args.get('name')}"
    if name == "delete_mod":
        backend.delete_mod(inst_name, args.get("filename"))
        return f"已删除 {args.get('filename')}"
    if name == "disable_mod":
        new = backend.disable_mod(inst_name, args.get("filename"))
        return f"已禁用 → {new}"
    if name == "enable_mod":
        new = backend.enable_mod(inst_name, args.get("filename"))
        return f"已启用 → {new}"
    if name == "get_java_list":
        return backend.get_java_list(False)
    if name == "download_java":
        tid = backend.download_java(str(args.get("major")))
        return backend.wait_task(tid, cancelled=cancelled) if wait else {"task_id": tid, "queued": True}
    if name == "launch_game":
        prefs = getattr(backend, "_ui_launch", None) or {}
        versions = backend.get_installed_versions(inst_name)
        version = args.get("version") or prefs.get("version") or (versions[-1] if versions else "")
        accounts = backend.get_accounts()
        account = args.get("account") or prefs.get("account") or ""
        if not account:
            account = _default_account(backend, accounts)
        username = args.get("username") or prefs.get("username") or "Player"
        memory = int(args.get("memory_mb") or prefs.get("memory_mb") or CONFIG.get("memory_mb") or 4096)
        width = int(prefs.get("width") or CONFIG.get("width") or 854)
        height = int(prefs.get("height") or CONFIG.get("height") or 480)
        java = prefs.get("java") or JAVA_AUTO
        inst = args.get("instance") or prefs.get("instance") or inst_name
        tid = backend.launch_game(
            inst, version, account, username, memory, width, height, java,
        )
        return f"已开始启动 {version}（任务 {tid}），日志在「启动」页"
    if name == "diagnose_launch":
        return diagnose_mod.diagnose(_inst(backend, args))
    if name == "get_latest_log":
        return diagnose_mod.log_excerpt(_inst(backend, args), "latest")
    if name == "get_crash_report":
        return diagnose_mod.log_excerpt(_inst(backend, args), "crash")
    if name == "scan_mod_conflicts":
        return conflict_mod.scan_conflicts(_inst(backend, args))
    if name == "inspect_mod":
        inst = _inst(backend, args)
        mods_dir = (inst.path / "mods").resolve()
        p = (mods_dir / (args.get("filename") or "")).resolve()
        if p.parent != mods_dir or not p.is_file():
            return f"找不到 {args.get('filename')}"
        return conflict_mod.inspect_jar(p)
    if name == "list_mod_configs":
        return modconfig_mod.list_configs(_inst(backend, args), args.get("prefix") or "")
    if name == "read_mod_config":
        return modconfig_mod.read_config(_inst(backend, args), args.get("path"))
    if name == "write_mod_config":
        return modconfig_mod.write_config(
            _inst(backend, args), args.get("path"), args.get("content") or "")
    if name == "read_artifact":
        return artifacts.read_artifact(
            args.get("artifact_id"), args.get("offset") or 0, args.get("limit") or 200)
    return f"未知工具: {name}"


class ToolCancelled(Exception):
    """用户点了停止：工具执行里抛出，agent 捕获后转 StopReason.CANCELLED。"""


# ---------------------------------------------------------------- 5.2 错误面

class ToolErrorCode(str, Enum):
    """内置工具的错误码枚举（批次 5.2）：错误面统一走 结构化回执，不再把
    原始异常字符串直接喂给模型。完整堆栈留在 trace（tool_exception）。"""

    BAD_ARGUMENTS = "bad_arguments"
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    IO_ERROR = "io_error"
    UPSTREAM_ERROR = "upstream_error"
    UNKNOWN = "unknown"


_ERROR_READABLE = {
    ToolErrorCode.BAD_ARGUMENTS: "工具参数不合法",
    ToolErrorCode.NOT_FOUND: "目标不存在",
    ToolErrorCode.PERMISSION_DENIED: "没有权限执行",
    ToolErrorCode.TIMEOUT: "执行超时",
    ToolErrorCode.CANCELLED: "已被用户停止",
    ToolErrorCode.IO_ERROR: "读写文件失败",
    ToolErrorCode.UPSTREAM_ERROR: "上游服务出错",
    ToolErrorCode.UNKNOWN: "执行失败",
}


def classify_exception(exc: BaseException) -> ToolErrorCode:
    if isinstance(exc, ToolCancelled):
        return ToolErrorCode.CANCELLED
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired if False else TimeoutError)):
        return ToolErrorCode.TIMEOUT
    if isinstance(exc, (FileNotFoundError, LookupError)):
        return ToolErrorCode.NOT_FOUND
    if isinstance(exc, PermissionError):
        return ToolErrorCode.PERMISSION_DENIED
    if isinstance(exc, OSError):
        return ToolErrorCode.IO_ERROR
    if isinstance(exc, (json.JSONDecodeError, ValueError, KeyError)):
        return ToolErrorCode.UPSTREAM_ERROR
    return ToolErrorCode.UNKNOWN


def tool_error_payload(exc: BaseException, name: str,
                       code: ToolErrorCode | None = None) -> str:
    """异常 → 结构化回执（错误码 + 用户可读文案 + 一句短原因）。堆栈只进 trace。"""
    code = code or classify_exception(exc)
    payload = {
        "ok": False,
        "error_code": code.value,
        "message": _ERROR_READABLE[code],
        "detail": f"{type(exc).__name__}: {exc}"[:200],
        "tool": name,
    }
    return json.dumps(payload, ensure_ascii=False)


def bad_args_payload(name: str, message: str) -> str:
    return json.dumps({"ok": False, "error_code": ToolErrorCode.BAD_ARGUMENTS.value,
                       "message": message, "tool": name}, ensure_ascii=False)


def run_tool(backend, name: str, raw_args, wait=True, cancelled=None) -> str:
    if cancelled is not None and cancelled():
        raise ToolCancelled("已停止")
    args, parse_err = parse_args(raw_args, name)
    if parse_err:
        trace.record("tool_bad_args", tool_name=name, detail=parse_err[:200])
        return bad_args_payload(name, parse_err)
    try:
        result = execute_tool(backend, name, args, wait=wait, cancelled=cancelled)
        if cancelled is not None and cancelled():
            raise ToolCancelled("已停止")
        return _clip(result, name)
    except ToolCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        trace.record("tool_exception", tool_name=name, exc=exc)
        return tool_error_payload(exc, name)


# ---- 5.1 参数校验：不合 schema 返回结构化错误（含字段名），不再以空参数静默执行

_TYPE_CHECK = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def _schema_of(name: str) -> dict | None:
    for s in TOOL_SCHEMAS:
        if s["function"]["name"] == name:
            return s["function"].get("parameters") or {}
    return None


def _validate_schema(name: str, args: dict) -> str | None:
    """按 schema 校验入参。返回 None = 通过；否则给含字段名的错误描述。"""
    params = _schema_of(name)
    if not params:
        return None
    required = params.get("required") or []
    missing = [k for k in required if k not in args or args[k] in (None, "")]
    if missing:
        return f"缺少必填字段: {', '.join(missing)}。请补齐后重新调用 {name}。"
    props = params.get("properties") or {}
    wrong = []
    for key, spec in props.items():
        if key not in args or not isinstance(spec, dict):
            continue
        want = spec.get("type")
        check = _TYPE_CHECK.get(want)
        if check and not check(args[key]):
            got = type(args[key]).__name__
            wrong.append(f"{key}（应为 {want}，实际 {got}）")
    if wrong:
        return "字段类型不对: " + "; ".join(wrong) + f"。请修正后重新调用 {name}。"
    return None


def parse_args(raw, name: str = "") -> tuple[dict, str | None]:
    """解析模型给的工具参数。返回 (args, error)：error 非 None 就是给模型的结构化错误。

    - JSON 截断 / 非法：不再静默 {}；key=value 风格抢救出来但明确要求重发；
    - 值带多余空格：字符串自动去首尾空白（回执里不用提，直接修好）；
    - 缺必填 / 类型错：按 schema 给含字段名的错误。
    """
    if isinstance(raw, dict):
        args = dict(raw)
        err = None
    elif raw is None or not str(raw).strip():
        args, err = {}, None
    else:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                args, err = data, None
            else:
                args, err = {}, f"参数必须是 JSON 对象，收到的是 {type(data).__name__}。请用 {{}} 包裹字段重发。"
        except json.JSONDecodeError:
            # 模型有时吐出 key=value（name="jei"）或半截 JSON：先抢救，再明确
            # 告诉模型这不算数、要按标准 JSON 重发
            out = {}
            for m in re.finditer(r'"?(\w+)"?\s*[:=]\s*"([^"]*)"', raw):
                out.setdefault(m.group(1), m.group(2))
            for m in re.finditer(r'"?(\w+)"?\s*[:=]\s*([-\w.]+)', raw):
                out.setdefault(m.group(1), m.group(2))
            if out:
                args = out
                err = (f"参数不是合法 JSON，已按 key=value 抢救出 {len(out)} 个字段"
                       f"（{', '.join(sorted(out))}）。请改用标准 JSON 重新调用。")
            else:
                args, err = {}, "参数不是合法 JSON（疑似被截断）。请把参数作为合法 JSON 对象重发。"
    if err is None and args:
        args = {k: (v.strip() if isinstance(v, str) else v) for k, v in args.items()}
        err = _validate_schema(name, args)
    return args, err

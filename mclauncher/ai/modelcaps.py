# -*- coding: utf-8 -*-
"""模型能力表：按模型 ID 自动判定是否支持图片（多模态）。

数据源是 ZCode 内置的 provider 配置（resources/config/provider/zcode-builtin.json，
schemaVersion 1 / revision 30）里的 modelConfigRules，原样搬进 model_rules.json。

ZCode 的判定语义（照抄自 resources/glm/zcode.cjs 的 ModelConfigRules.resolve）：

1. ``modelMatch`` 是**全匹配**正则——ZCode 校验器把它包成 ``^(?:…)$``，
   这里用 ``re.fullmatch`` 等价实现（且大小写不敏感，对应 ZCode 的 "i" flag）。
2. 规则按顺序叠加，**后者覆盖前者**——``overlayValue(t,n){return n===undefined?t:n}``
   即目标字段非 None 才覆盖；``inputFormat`` 这类嵌套对象是逐字段递归覆盖，
   所以只写 ``supportsImage`` 的规则不会把 ``supportsText`` 抹掉。
3. 第一条 ``modelMatch: ".*"`` 是兜底：200k 上下文、不支持图片。

用户可在 settings 里放 ``ai_model_caps_overrides`` 覆盖内置表，形如::

    {"my-model-v2": {"inputFormat": {"supportsImage": true}, "contextWindow": 128000}}

覆盖规则排在最后，语义与内置表一致（同样是 overlay）。
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

from mclauncher.utils import read_json

_RULES_FILE = "model_rules.json"

# 兜底能力：没命中任何规则时用它。与 ZCode 第一条 ".*" 规则保持一致。
_FALLBACK = {
    "contextWindow": 200000,
    "inputFormat": {
        "supportsText": True,
        "supportsImage": False,
        "supportsVideo": False,
        "supportsAudio": False,
        "supportsPdf": False,
    },
    "outputFormat": {"supportsText": True},
    "supportsToolCall": True,
}

_lock = threading.Lock()
_cache = None

# 只看这些字段：其余（supportsJsonSchemaOutput 等）PyMCL 用不上，留着只是噪音
_PROP_KEYS = ("contextWindow", "inputFormat", "outputFormat", "supportsToolCall")

_INPUT_KEYS = ("supportsText", "supportsImage", "supportsVideo",
               "supportsAudio", "supportsPdf")


def _rules_path():
    return Path(__file__).resolve().parent / _RULES_FILE


def _load():
    global _cache
    if _cache is not None:
        return _cache
    with _lock:
        if _cache is not None:
            return _cache
        data = read_json(_rules_path(), None)
        if not isinstance(data, dict):
            # 数据文件缺失/损坏时不能把多模态整体打哑：退回兜底能力，
            # 但图片入口仍由 supports_image() 判定为 False（安全侧）。
            data = {}
        compiled = []
        for layer in ("modelRules", "modelApiRules", "providerSiteRules"):
            for rule in data.get(layer) or []:
                if not isinstance(rule, dict):
                    continue
                entry = _compile_rule(rule, layer)
                if entry is not None:
                    compiled.append(entry)
        _cache = compiled
        return _cache


def _compile_rule(rule, layer):
    match = rule.get("modelMatch")
    if not isinstance(match, str) or not match:
        return None
    try:
        # ZCode: new RegExp(`^(?:${e})$`, "i") —— 全匹配 + 大小写不敏感
        rx = re.compile(match, re.IGNORECASE)
    except re.error:
        return None
    cfg = rule.get("config") or {}
    props = _slim_props(cfg.get("properties"))
    if not props:
        return None
    return {
        "layer": layer,
        "rx": rx,
        "apiTypeMatch": rule.get("apiTypeMatch"),
        "baseUrlMatch": rule.get("baseUrlMatch"),
        "props": props,
    }


def _slim_props(props):
    if not isinstance(props, dict):
        return None
    out = {}
    for key in _PROP_KEYS:
        val = props.get(key)
        if val is None:
            continue
        if key in ("inputFormat", "outputFormat") and isinstance(val, dict):
            inner = {k: bool(v) for k, v in val.items()
                     if k in _INPUT_KEYS and v is not None}
            if inner:
                out[key] = inner
        elif key == "contextWindow":
            try:
                out[key] = int(val)
            except (TypeError, ValueError):
                continue
        else:
            out[key] = bool(val)
    return out or None


def _fullmatch(rx, text):
    """ZCode 的 ^(?:…)$ 语义。re.fullmatch 等价，但这里显式包一层防止
    正则自身带 ^ $ 时 fullmatch 语义偏移。"""
    if text is None:
        return False
    return rx.fullmatch(str(text)) is not None


def normalize_base_url(url):
    """ZCode normalizeBaseURLForRuleMatch：去掉尾部斜杠，保留 query/hash。

    JS 的 URL 解析在 Python 侧没有等价物，这里按同样的可见效果处理：
    去掉末尾斜杠（query/hash 之前的路径部分）。解析失败返回 None（=不参与匹配）。
    """
    if not url:
        return None
    text = str(url).strip()
    if not text:
        return None
    try:
        from urllib.parse import urlsplit, urlunsplit
        parts = urlsplit(text)
        if not parts.scheme:
            return text.rstrip("/")
        path = parts.path.rstrip("/")
        return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))
    except Exception:  # noqa: BLE001
        return text.rstrip("/")


def _overlay(base, patch):
    """ZCode overlayValue / overlayConfig：patch 里非 None 的值覆盖 base。

    嵌套 dict（inputFormat）递归合并，而不是整体替换——这是 ZCode
    ``overlayConfig`` 的行为，照搬以免「只声明 supportsImage 的规则
    把 supportsText 抹成未定义」。
    """
    if patch is None:
        return base
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return patch
    out = dict(base)
    for key, val in patch.items():
        if val is None:
            continue
        cur = out.get(key)
        if isinstance(cur, dict) and isinstance(val, dict):
            out[key] = _overlay(cur, val)
        else:
            out[key] = val
    return out


def _overrides(settings):
    """用户覆盖表：settings['ai_model_caps_overrides']。

    支持两种写法：模型名 → 能力对象；也允许 "modelMatch" 正则作为键。
    匹配同样是全匹配 + 大小写不敏感。
    """
    if not isinstance(settings, dict):
        return []
    raw = settings.get("ai_model_caps_overrides")
    if not isinstance(raw, dict):
        return []
    out = []
    for pattern, props in raw.items():
        if not isinstance(pattern, str) or not isinstance(props, dict):
            continue
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error:
            continue
        slim = _slim_props(props)
        if slim:
            out.append({"rx": rx, "props": slim})
    return out


def resolve(model_id, *, api_type=None, base_url=None, settings=None) -> dict:
    """算出模型的完整能力。等价于 ZCode ModelConfigRules.resolve。

    :param model_id: 模型 ID（如 "glm-4.6v-flash"）
    :param api_type: 可选，如 "openai-chat-completions"
    :param base_url: 可选，服务商 base url
    :param settings: 可选，含 ai_model_caps_overrides 的 settings
    :return: {"contextWindow": int, "inputFormat": {...}, "outputFormat": {...},
              "supportsToolCall": bool}
    """
    model = (str(model_id or "")).strip()
    base = normalize_base_url(base_url)
    cfg = dict(_FALLBACK)
    cfg["inputFormat"] = dict(_FALLBACK["inputFormat"])
    cfg["outputFormat"] = dict(_FALLBACK["outputFormat"])

    for entry in _load():
        if not _fullmatch(entry["rx"], model):
            continue
        api_pat = entry.get("apiTypeMatch")
        if api_pat is not None:
            if api_type is None or not _match_any(api_pat, api_type):
                continue
        url_pat = entry.get("baseUrlMatch")
        if url_pat is not None:
            if base is None or not _match_any(url_pat, base):
                continue
        cfg = _overlay(cfg, entry["props"])

    for entry in _overrides(settings):
        if _fullmatch(entry["rx"], model):
            cfg = _overlay(cfg, entry["props"])

    return cfg


def _match_any(pattern, text):
    try:
        return re.compile(pattern, re.IGNORECASE).fullmatch(str(text)) is not None
    except re.error:
        return False


def supports_image(model_id, *, api_type=None, base_url=None, settings=None) -> bool:
    """模型是否支持图片输入（多模态）。UI 的上传入口开关就认这个。"""
    cfg = resolve(model_id, api_type=api_type, base_url=base_url, settings=settings)
    fmt = cfg.get("inputFormat") or {}
    return bool(fmt.get("supportsImage"))


def supports_pdf(model_id, *, api_type=None, base_url=None, settings=None) -> bool:
    cfg = resolve(model_id, api_type=api_type, base_url=base_url, settings=settings)
    return bool((cfg.get("inputFormat") or {}).get("supportsPdf"))


def _matched_specific(model_id, *, api_type=None, base_url=None, settings=None) -> bool:
    """模型是否命中了「具体」规则（排除纯 `.*` 兜底）。

    用来区分「表里认识这个模型」和「只被兜底规则接住」：前者用表里的精确
    上下文窗口，后者让用户的 ai_context_window 配置说了算。
    """
    model = (str(model_id or "")).strip()
    base = normalize_base_url(base_url)
    for entry in _load():
        if entry["rx"].pattern == ".*":
            continue
        if not _fullmatch(entry["rx"], model):
            continue
        api_pat = entry.get("apiTypeMatch")
        if api_pat is not None and (api_type is None
                                    or not _match_any(api_pat, api_type)):
            continue
        url_pat = entry.get("baseUrlMatch")
        if url_pat is not None and (base is None
                                    or not _match_any(url_pat, base)):
            continue
        if "contextWindow" in entry["props"]:
            return True
    for entry in _overrides(settings):
        if "contextWindow" in entry["props"] and _fullmatch(entry["rx"], model):
            return True
    return False


def context_window(model_id, *, fallback=None, settings=None, api_type=None,
                   base_url=None) -> int:
    """模型上下文窗口。

    优先级：用户覆盖表 > 内置表（表里认识这个模型）> fallback
    （settings 里的 ai_context_window）> 表内兜底 200k。

    fallback 只在「表里不认识这个模型」时生效：对内置表收录的模型，
    精确值比用户手填的通用值可信；对表外的新模型，用户填的值才是唯一线索。
    """
    cfg = resolve(model_id, api_type=api_type, base_url=base_url, settings=settings)
    known = _matched_specific(model_id, api_type=api_type, base_url=base_url,
                              settings=settings)
    if not known and fallback:
        try:
            return max(8192, int(fallback))
        except (TypeError, ValueError):
            pass
    try:
        val = int(cfg.get("contextWindow"))
        if val > 0:
            return val
    except (TypeError, ValueError):
        pass
    return int(_FALLBACK["contextWindow"])


def capabilities(model_id, *, api_type=None, base_url=None, settings=None) -> dict:
    """给 UI 用的一行摘要：{"image": bool, "video": bool, "pdf": bool, "context": int}"""
    cfg = resolve(model_id, api_type=api_type, base_url=base_url, settings=settings)
    fmt = cfg.get("inputFormat") or {}
    return {
        "image": bool(fmt.get("supportsImage")),
        "video": bool(fmt.get("supportsVideo")),
        "audio": bool(fmt.get("supportsAudio")),
        "pdf": bool(fmt.get("supportsPdf")),
        "context": context_window(model_id, settings=settings, api_type=api_type,
                                  base_url=base_url),
    }


def describe(model_id, *, settings=None) -> str:
    """能力徽章文案，例：``上下文 200K · 图片 ✓ · 视频 ✗``。"""
    caps = capabilities(model_id, settings=settings)
    ctx = caps["context"]
    if ctx >= 1_000_000:
        # 1048576 → 1M（不写成 1048K，那个数没人会念）
        val = ctx / 1_000_000
        ctx_text = f"{val:.1f}M".replace(".0M", "M")
    elif ctx >= 1000:
        val = ctx / 1000
        ctx_text = f"{val:.0f}K" if val >= 100 else f"{val:.1f}K".replace(".0K", "K")
    else:
        ctx_text = str(ctx)
    marks = [f"上下文 {ctx_text}", f"图片 {'✓' if caps['image'] else '✗'}"]
    if caps["video"]:
        marks.append("视频 ✓")
    if caps["pdf"]:
        marks.append("PDF ✓")
    return " · ".join(marks)


def api_type_for_mode(mode) -> str | None:
    """PyMCL 只有 OpenAI 兼容通道；两种模式都走 chat-completions。

    ZCode 用 apiTypeMatch 区分 anthropic-messages / openai-responses 等，
    PyMCL 侧固定返回 openai-chat-completions，让带该条件的规则正常参与匹配。
    """
    return "openai-chat-completions"


_TAIL_RX = re.compile(r"\(\?:\[[^\]]*\]\.\*\)\?$")


def image_models(limit: int = 8) -> list:
    """内置表里支持图片的模型名（去掉正则包装，仅供 UI 提示用）。

    规则里的 modelMatch 是给机器看的（``.*glm-4\\.6v(?:[.\\-:/\\[].*)?``），
    这里把它还原成人能读的模型名。还原不出来的（含交替分支等复杂结构）跳过，
    宁可不提示也不要给用户一个 ``gpt-5.6-sol|terra|luna)`` 这样的残片。
    """
    names = []
    for entry in _load():
        if entry.get("layer") != "modelRules":
            continue
        props = entry.get("props") or {}
        if not (props.get("inputFormat") or {}).get("supportsImage"):
            continue
        text = entry["rx"].pattern
        if "|" in text:          # 交替分支还原不可靠，跳过
            continue
        text = re.sub(r"^\.\*", "", text)     # 去开头 .*
        text = _TAIL_RX.sub("", text)         # 去版本尾缀 (?:[.\-:/\[].*)?
        text = text.replace("\\", "").strip("^$")
        text = re.sub(r"\(\?:", "", text).replace(")?", "").replace(".*", "")
        text = text.strip("().")
        if text and len(text) < 40 and not re.search(r"[\[\](){}*+?]", text):
            names.append(text)
    seen = set()
    out = []
    for n in names:
        if n.lower() in seen:
            continue
        seen.add(n.lower())
        out.append(n)
        if len(out) >= limit:
            break
    return out


def reset_cache():
    """测试用：清掉规则缓存。"""
    global _cache
    with _lock:
        _cache = None

# -*- coding: utf-8 -*-
"""OpenAI 兼容客户端：公益网关 / 自定义 NewAPI。"""

from __future__ import annotations

import json
from typing import Iterator

import requests
from requests.exceptions import ReadTimeout, ChunkedEncodingError

from mclauncher.net import apply_direct_to_session

from . import builtin
from .defaults import (
    CLIENT_HEADER, DEFAULT_GATEWAY_URL, DEFAULT_MODEL,
    ONCE_TIMEOUT, STREAM_CONNECT_TIMEOUT, STREAM_READ_TIMEOUT,
)


def _categorize(message: str, status: int) -> str:
    """错误分类（关键词集照抄 ZCode 的超时/网络/流错误三类）。"""
    msg = (message or "").lower()
    if status in (401, 403) or "令牌无效" in msg or "unauthorized" in msg:
        return "auth"
    if status == 429 or "rate limit" in msg or "限制" in msg or "额度" in msg:
        return "rate_limited"
    if "timed out" in msg or "timeout" in msg or "超时" in msg:
        return "provider_timeout"
    if any(key in msg for key in ("econnreset", "epipe", "etimedout", "connection",
                                  "连不上", "network", "getaddrinfo", "网络")):
        return "provider_network_error"
    if "stream" in msg or "stalled" in msg or "sse" in msg:
        return "provider_stream_error"
    return "unknown"


class AIClientError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = int(status or 0)
        self.category = _categorize(message, self.status)

    def fatal(self) -> bool:
        # 只有认证/权限类才致命；429 是限流，走退避重试而不是终止对话
        return self.status in (401, 403) or self.category == "auth"

    def retryable(self) -> bool:
        if self.status in (429, 500, 502, 503, 504):
            return True
        return self.category in ("provider_timeout", "provider_network_error",
                                 "provider_stream_error", "rate_limited")


class HttpCancel:
    """从 UI 线程关掉正在进行的 HTTP，让停止键真正生效。"""

    def __init__(self):
        self.flag = False
        self._resp = None
        self._sess = None

    def bind(self, session=None, resp=None):
        if session is not None:
            self._sess = session
        if resp is not None:
            self._resp = resp
        if self.flag:
            self.abort()

    def abort(self):
        self.flag = True
        for obj in (self._resp, self._sess):
            if obj is None:
                continue
            try:
                obj.close()
            except Exception:
                pass

    def cancelled(self) -> bool:
        return self.flag


# 上游报「塞不下」的关键词：命中即触发 reactive compact（批次 4）
_OVERFLOW_KEYS = (
    "maximum context length", "context length exceeded", "context_length_exceeded",
    "prompt too long", "too many input tokens", "input length exceeds",
    "上下文长度", "上下文过长", "输入过长", "请求过长", "超出长度",
)


def is_context_overflow(message: str) -> bool:
    msg = (message or "").lower()
    return any(key.lower() in msg for key in _OVERFLOW_KEYS)


def max_output_tokens(settings: dict) -> int:
    """max_tokens 可配置：默认 8192（原 2048，讲排错方案必撞顶）。"""
    try:
        return max(512, int((settings or {}).get("ai_max_tokens") or 8192))
    except (TypeError, ValueError):
        return 8192


def normalize_base(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if u.endswith("/v1"):
        return u
    return u + "/v1"


def resolve_endpoint(settings: dict) -> dict:
    """返回 {mode, url, headers, model, public}。"""
    mode = (settings.get("ai_mode") or "public").strip().lower()
    model = (settings.get("ai_model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    if mode in ("custom", "newapi", "自定义"):
        base = normalize_base(settings.get("ai_base_url") or "")
        key = (settings.get("ai_api_key") or "").strip()
        if not base:
            raise AIClientError("请在设置里填写自定义 NewAPI 地址（到 /v1 为止）")
        if not key:
            raise AIClientError("请在设置里填写 NewAPI 令牌")
        return {
            "mode": "custom",
            "url": base + "/chat/completions",
            "models_url": base + "/models",
            "headers": {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            "model": model,
            "public": False,
        }
    builtin_ep = builtin.public_endpoint()
    gateway = (settings.get("ai_gateway_url") or DEFAULT_GATEWAY_URL or "").strip().rstrip("/")
    if gateway:
        return {
            "mode": "public",
            "url": gateway + "/pymcl/chat",
            "models_url": gateway + "/health",
            "headers": {
                "Content-Type": "application/json",
                "X-PyMCL-Client": CLIENT_HEADER,
            },
            "model": builtin_ep["model"],
            "public": True,
        }
    # 4.1：分发包内不再内置可用上游令牌。没配网关就明确报错给用户，
    # 不静默失败、不偷偷走什么内置通道。
    raise AIClientError(
        "还没有配置 AI 网关：请到「设置 → AI 助手」填入自建公益网关地址，"
        "或切到「自定义 NewAPI」模式填地址与令牌。搭建方法见 ai_gateway/README.md。")


def _session() -> requests.Session:
    """代理策略跟全项目一致（net.py：默认跟随系统代理，用户关掉才直连）。

    以前这里三处硬写 proxies={"http": None, "https": None}，AI 成了唯一强制直连的
    模块：走代理的用户下载正常、AI 连不上。
    """
    session = requests.Session()
    apply_direct_to_session(session)
    return session


def test_connection(settings: dict) -> str:
    ep = resolve_endpoint(settings)
    r = _session().get(ep["models_url"], headers=ep["headers"], timeout=15)
    if r.status_code >= 400:
        raise AIClientError(_err_text(r), r.status_code)
    try:
        data = r.json()
    except Exception:
        return "已连通"
    if ep["public"]:
        if data.get("service"):
            return f"公益接口正常（{data.get('service')}）"
        models = data.get("data") or []
        names = [m.get("id") for m in models if isinstance(m, dict) and m.get("id")]
        locked = ep.get("model") or DEFAULT_MODEL
        if locked in names or not names:
            return f"公益接口正常，模型 {locked}"
        return f"公益接口已连通，但列表里没有 {locked}（当前有 {names[0]}）"
    models = data.get("data") or []
    names = [m.get("id") for m in models if isinstance(m, dict) and m.get("id")]
    if names:
        return f"NewAPI 正常，可用模型 {len(names)} 个，例如 {names[0]}"
    return "NewAPI 已连通"


def _err_text(resp) -> str:
    code = getattr(resp, "status_code", 0) or 0
    prefix = f"HTTP {code} " if code else ""
    try:
        resp.encoding = "utf-8"
    except Exception:
        pass
    def _out(text: str) -> str:
        return (prefix + _decode_sse_line(text or "接口错误"))[:800]

    try:
        data = resp.json()
    except Exception:
        return _out(resp.text or "接口错误")
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        msg = err.get("message") or err.get("msg") or err.get("code") or ""
        extra = err.get("type") or err.get("code") or ""
        rid = ""
        for key in ("request_id", "requestId", "id"):
            if data.get(key) or err.get(key):
                rid = str(data.get(key) or err.get(key))
                break
        parts = [str(msg).strip()]
        if extra and str(extra) not in parts[0]:
            parts.append(str(extra))
        if rid and rid not in parts[0]:
            parts.append(f"request id: {rid}")
        text = " ".join(p for p in parts if p)
        return _out(text or json.dumps(err, ensure_ascii=False))
    if isinstance(err, str) and err.strip():
        return _out(err)
    if isinstance(data, dict):
        msg = data.get("message") or data.get("msg")
        if msg:
            return _out(str(msg))
    return _out(resp.text or "接口错误")


def _decode_sse_line(raw) -> str:
    """SSE 常不带 charset；Windows 上 decode_unicode 会按 latin-1 把中文解成乱码。"""
    if raw is None:
        return ""
    if isinstance(raw, str):
        # 已经是 str 的，只在「像被 latin-1 错解的 UTF-8 字节串」时才反解：
        # 全部字符 ≤ 0xFF 且含 ≥ 0x80 的；反解成功后还要么原文里带 C1 控制符
        # （0x80–0x9F，正常文本不会出现，UTF-8 续字节常落在这一段），要么解出了
        # 中文，才采纳。否则 "café" / "Â©" 这类正常拉丁文会被改坏。
        if not raw or any(ord(ch) > 0xFF for ch in raw) or all(ord(ch) < 0x80 for ch in raw):
            return raw
        try:
            fixed = raw.encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return raw
        looks_mojibake = any(0x80 <= ord(ch) <= 0x9F for ch in raw) \
            or any("\u4e00" <= ch <= "\u9fff" for ch in fixed)
        return fixed if looks_mojibake else raw
    return raw.decode("utf-8", errors="replace")


def _args_complete(raw: str) -> bool:
    s = (raw or "").strip()
    if not s:
        return True
    try:
        json.loads(s)
        return True
    except json.JSONDecodeError:
        return False


def _flush_complete_tools(acc: dict) -> list | None:
    out = _flush_tools(acc)
    if not out:
        return None
    if all(_args_complete((t.get("function") or {}).get("arguments") or "") for t in out):
        return out
    return None


def _assemble_stream(resp, expect_usage: bool = False) -> Iterator[dict]:
    tool_acc = {}
    got_delta = False
    pending_done = None
    last_usage = None
    resp.encoding = "utf-8"
    try:
        lines = resp.iter_lines(decode_unicode=False)
        for raw in lines:
            if not raw:
                continue
            line = _decode_sse_line(raw).strip()
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line:
                continue   # 空载荷 / 心跳行不是流结束，只有 [DONE] 才是
            if line == "[DONE]":
                tools = _flush_complete_tools(tool_acc) if tool_acc else None
                if tools:
                    yield {"type": "tool_calls", "tool_calls": tools}
                    return
                if tool_acc:
                    yield {"type": "error", "message": "工具参数不完整，正在换一次非流式"}
                    return
                if pending_done:
                    if last_usage:
                        yield {"type": "usage", "usage": last_usage}
                    yield pending_done
                else:
                    yield {"type": "done"}
                return
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            if chunk.get("error"):
                err = chunk["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                yield {"type": "error", "message": msg}
                return
            usage = chunk.get("usage")
            if isinstance(usage, dict) and usage:
                last_usage = usage
            choices = chunk.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            text = delta.get("content")
            if text:
                got_delta = True
                yield {"type": "delta", "text": _decode_sse_line(text)}
            for tc in delta.get("tool_calls") or []:
                idx = tc.get("index", 0)
                slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["arguments"] += fn["arguments"]
            reason = choice.get("finish_reason")
            if reason == "tool_calls":
                tools = _flush_complete_tools(tool_acc)
                if tools:
                    yield {"type": "tool_calls", "tool_calls": tools}
                    return
                yield {"type": "error", "message": "工具参数不完整，正在换一次非流式"}
                return
            if reason in ("stop", "length"):
                # 请求了 usage 时等 [DONE]：usage 包在最后一个内容包之后
                if expect_usage:
                    pending_done = {"type": "done", "finish_reason": reason}
                    continue
                yield {"type": "done", "finish_reason": reason}
                return
        tools = _flush_complete_tools(tool_acc) if tool_acc else None
        if tools:
            yield {"type": "tool_calls", "tool_calls": tools}
            return
        if tool_acc:
            yield {"type": "error", "message": "工具参数不完整，正在换一次非流式"}
            return
        if pending_done:
            if last_usage:
                yield {"type": "usage", "usage": last_usage}
            yield pending_done
            return
        if got_delta:
            yield {"type": "done"}
            return
        yield {"type": "error", "message": "接口没有返回内容"}
    except (ReadTimeout, ChunkedEncodingError):
        tools = _flush_complete_tools(tool_acc) if tool_acc else None
        if tools:
            yield {"type": "tool_calls", "tool_calls": tools}
            return
        yield {"type": "error", "message": "接口超时，正在换一次非流式"}
        return


def _flush_tools(acc: dict) -> list:
    out = []
    for idx in sorted(acc):
        item = acc[idx]
        out.append({
            "id": item.get("id") or f"call_{idx}",
            "type": "function",
            "function": {
                "name": item.get("name") or "",
                "arguments": item.get("arguments") or "{}",
            },
        })
    return out


def _http_error(exc, http_cancel):
    if http_cancel and http_cancel.cancelled():
        return AIClientError("已停止")
    return AIClientError(f"连不上接口: {exc}")


def chat_stream(settings: dict, messages: list, tools: list | None = None,
                temperature: float = 0.3, http_cancel=None) -> Iterator[dict]:
    ep = resolve_endpoint(settings)
    body = {
        "model": ep["model"],
        "messages": messages,
        "temperature": temperature,
        "stream": True,
        "max_tokens": max_output_tokens(settings),
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    expect_usage = False
    if not ep["public"]:
        # 公益网关是纯字节转发拿不到 usage；自定义 NewAPI 直连才请求计量
        body["stream_options"] = {"include_usage": True}
        expect_usage = True
    session = _session()
    if http_cancel:
        http_cancel.bind(session)
        if http_cancel.cancelled():
            raise AIClientError("已停止")
    try:
        resp = session.post(
            ep["url"], headers=ep["headers"], json=body,
            stream=True, timeout=(STREAM_CONNECT_TIMEOUT, STREAM_READ_TIMEOUT),
        )
    except requests.RequestException as exc:
        raise _http_error(exc, http_cancel) from exc
    if http_cancel:
        http_cancel.bind(session, resp)
        if http_cancel.cancelled():
            raise AIClientError("已停止")
    if resp.status_code >= 400:
        raise AIClientError(_err_text(resp), resp.status_code)
    yield from _assemble_stream(resp, expect_usage=expect_usage)


def chat_once(settings: dict, messages: list, tools: list | None = None,
              temperature: float = 0.3, http_cancel=None) -> dict:
    ep = resolve_endpoint(settings)
    body = {
        "model": ep["model"],
        "messages": messages,
        "temperature": temperature,
        "stream": False,
        "max_tokens": max_output_tokens(settings),
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    session = _session()
    if http_cancel:
        http_cancel.bind(session)
        if http_cancel.cancelled():
            raise AIClientError("已停止")
    try:
        resp = session.post(
            ep["url"], headers=ep["headers"], json=body, timeout=ONCE_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise _http_error(exc, http_cancel) from exc
    if resp.status_code >= 400:
        raise AIClientError(_err_text(resp), resp.status_code)
    resp.encoding = "utf-8"
    try:
        data = resp.json()
    except ValueError as exc:
        # 网关 200 却回了 HTML 错误页 / 半截文本：以前裸抛 JSONDecodeError，用户看到的是
        # "Expecting value: line 1 column 1" 这种原始报错。归成一条可读的 AIClientError。
        snippet = _decode_sse_line((resp.text or "").strip())[:200]
        raise AIClientError(
            f"接口返回的不是 JSON（HTTP {resp.status_code}）：{snippet or '空响应'}",
            resp.status_code) from exc
    if not isinstance(data, dict):
        raise AIClientError(f"接口返回格式异常（HTTP {resp.status_code}）", resp.status_code)
    choice = (data.get("choices") or [{}])[0]
    if not isinstance(choice, dict):
        choice = {}
    msg = choice.get("message") or {}
    return {
        "content": msg.get("content") or "",
        "tool_calls": msg.get("tool_calls") or [],
        "finish_reason": choice.get("finish_reason") or "stop",
        "usage": data.get("usage") or {},
    }

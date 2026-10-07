# -*- coding: utf-8 -*-
"""图片附件：读取、压缩、编码成 OpenAI 兼容的 data URL。

多模态消息体里图片走 ``image_url`` 内容块，值是 ``data:image/png;base64,…``。
这里负责把磁盘上/剪贴板里的图片变成那个字符串，并把体积压到合理范围。

限制的取值理由：
- 长边 1568：视觉模型内部会把图切块编码，超过这个尺寸后 token 成本线性涨、
  识别收益趋近于零，多数厂商文档也把 1568 作为推荐上限。
- 单图 4MB（编码前）：base64 会膨胀约 1/3，4MB 原图 → 约 5.3MB 请求体，
  在网关/反代常见的 10MB 默认限制内留了余量。
- 单轮 4 张：再多用户也说不清是哪张，且请求体线性膨胀。

Pillow 是可选依赖：没装时只能原样编码（不压缩），超限则明确报错而不是
静默发一张超大图把请求撑爆。
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

MAX_EDGE = 1568
MAX_BYTES = 4 * 1024 * 1024
MAX_PER_TURN = 4
JPEG_QUALITY = 85

# Pillow 缩放后仍然超限时的兜底质量档，逐档往下试
_QUALITY_LADDER = (85, 75, 65, 55)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class ImageError(Exception):
    """图片无法用于多模态请求（格式不支持 / 太大 / 读不了）。"""


def sniff_mime(data: bytes) -> str | None:
    """按魔数判断图片类型。不依赖 imghdr（3.13 已移除）也不信扩展名。"""
    if not data:
        return None
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"BM"):
        return "image/bmp"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _pillow():
    try:
        from PIL import Image  # noqa: F401
        return Image
    except Exception:  # noqa: BLE001
        return None


def has_pillow() -> bool:
    return _pillow() is not None


def _transpose(img):
    """按 EXIF 方向摆正。手机截图/相机照片常带旋转标记，
    不处理的话模型看到的是躺着的图。"""
    try:
        from PIL import ImageOps
        return ImageOps.exif_transpose(img)
    except Exception:  # noqa: BLE001
        return img


def _shrink(data: bytes, mime: str, *, max_edge: int = MAX_EDGE,
            max_bytes: int = MAX_BYTES) -> tuple:
    """超尺寸/超体积时重编码。返回 (data, mime)。

    Pillow 不可用时原样返回，由调用方按 max_bytes 判定是否放行。
    """
    Image = _pillow()
    if Image is None:
        return data, mime
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ImageError(f"图片无法解析：{exc}") from exc

    img = _transpose(img)
    changed = False
    w, h = img.size
    if max(w, h) > max_edge:
        scale = max_edge / float(max(w, h))
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                         Image.LANCZOS)
        changed = True

    # 有透明通道的一律存 PNG（JPEG 会把透明变黑块）；其余存 JPEG 省体积
    has_alpha = img.mode in ("RGBA", "LA", "P") and "transparency" in img.info \
        or img.mode in ("RGBA", "LA")
    if has_alpha:
        out_mime = "image/png"
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        out = buf.getvalue()
        if len(out) <= max_bytes or not changed:
            return (out, out_mime) if len(out) < len(data) or changed else (data, mime)
        return out, out_mime

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    out_mime = "image/jpeg"
    best = None
    for quality in _QUALITY_LADDER:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        out = buf.getvalue()
        if best is None or len(out) < len(best):
            best = out
        if len(out) <= max_bytes:
            best = out
            break
    if best is not None and (changed or len(best) < len(data)):
        return best, out_mime
    return data, mime


def encode_bytes(data: bytes, *, mime: str | None = None,
                 max_edge: int = MAX_EDGE, max_bytes: int = MAX_BYTES) -> str:
    """bytes → ``data:image/…;base64,…``。"""
    if not data:
        raise ImageError("图片是空的")
    mime = mime or sniff_mime(data)
    if not mime:
        raise ImageError("不是支持的图片格式（支持 PNG / JPEG / GIF / WebP / BMP）")
    if len(data) > max_bytes or max_edge:
        data, mime = _shrink(data, mime, max_edge=max_edge, max_bytes=max_bytes)
    if len(data) > max_bytes:
        raise ImageError(
            f"图片压缩后仍超过 {max_bytes // (1024 * 1024)}MB，"
            "请先裁剪或降低分辨率再发")
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def encode_file(path, **kw) -> str:
    """磁盘图片 → data URL。"""
    p = Path(path)
    try:
        data = p.read_bytes()
    except OSError as exc:
        raise ImageError(f"读不了这张图（{exc.strerror or exc}）") from exc
    return encode_bytes(data, **kw)


def make_block(url: str, *, detail: str | None = None) -> dict:
    """构造 OpenAI 兼容的 image_url 内容块。"""
    inner = {"url": url}
    if detail:
        inner["detail"] = detail
    return {"type": "image_url", "image_url": inner}


def build_user_content(text: str, images) -> object:
    """把「一句话 + 若干图片」拼成消息 content。

    没有图片时返回纯字符串——绝大多数请求走这条路径，保持与旧版完全一致的
    请求体，不给纯文本模型引入任何多余结构。
    """
    urls = [u for u in (images or []) if u]
    text = text or ""
    if not urls:
        return text
    blocks = []
    if text.strip():
        blocks.append({"type": "text", "text": text})
    for url in urls:
        blocks.append(make_block(url))
    return blocks


def strip_images(content):
    """把 content 里的图片块剥掉，只留文字。

    历史裁剪、摘要请求、非多模态模型兜底都走这里：base64 图片进摘要请求
    既烧 token 又毫无意义（摘要要的是语义，不是像素）。
    """
    if not isinstance(content, list):
        return content
    texts = []
    dropped = 0
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            texts.append(str(block.get("text") or ""))
        elif block.get("type") == "image_url":
            dropped += 1
    joined = "\n".join(t for t in texts if t.strip())
    if dropped:
        note = f"（此处原有 {dropped} 张图片，已省略）"
        joined = f"{joined}\n{note}".strip() if joined else note
    return joined


def strip_message(m: dict) -> dict:
    """把一条消息里的图片信息剥干净，只留文字（含 images 路径字段）。

    给摘要/压缩/历史导出用：这些场景要的是语义，图片既没用又占体积。
    """
    if not isinstance(m, dict):
        return m
    out = dict(m)
    paths = out.pop("images", None)
    content = strip_images(out.get("content"))
    if paths and isinstance(content, str):
        note = f"（此处原有 {len(paths)} 张图片，已省略）"
        content = f"{content}\n{note}".strip() if content.strip() else note
    out["content"] = content
    return out


def count_images(content) -> int:
    if not isinstance(content, list):
        return 0
    return sum(1 for b in content
               if isinstance(b, dict) and b.get("type") == "image_url")


def describe_limits() -> str:
    return (f"单图 ≤ {MAX_BYTES // (1024 * 1024)}MB、长边 ≤ {MAX_EDGE}px、"
            f"单轮 ≤ {MAX_PER_TURN} 张")

"""发送前的图片规格收敛，用于视觉识别（文档对齐 DeepSeek Vision 限制）。

官方限制（api-docs.deepseek.com/guides/vision）：
- 支持 JPEG / PNG / GIF / WebP，格式按文件内容判断；
- 单张 ≤32 MiB，请求体 ≤48 MiB，单边 ≤8192 px；
- 推理前会统一缩放：小于约 544×544 的图会被放大，更大的图会缩到约 1300×1300 的像素总量。

也就是说：超出 ~1300×1300 的像素服务端最终仍会丢弃，但传输与编码成本由客户端承担，
这正是大图请求容易超时、被限流或失败的原因。这里在本地预先收敛到接近该尺度。
"""
from __future__ import annotations

import io

from PIL import Image

MAX_VISION_BYTES = 4 * 1024 * 1024
MAX_VISION_EDGE = 1568

_IMAGE_MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


def prepare_for_vision(data: bytes, mime_type: str = "image/png") -> tuple[bytes, str]:
    """把图片收敛为视觉接口更容易接受的规格，返回 (bytes, mime)。

    解析失败时原样返回，由随后真正的 API 调用给出原因，不在这里吞掉错误。
    """
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        return data, mime_type

    width, height = image.size
    # The bytes are authoritative. Callers may use the default PNG fallback even
    # when an uploaded photo has already been normalized to JPEG; sending a
    # mismatched data URL MIME can be rejected by stricter OpenAI-compatible gateways.
    detected_mime = _IMAGE_MIME_BY_FORMAT.get((image.format or "").upper(), mime_type)
    oversized = len(data) > MAX_VISION_BYTES or max(width, height) > MAX_VISION_EDGE
    if not oversized:
        # 规格已经合适就原样发送：重编码会引入压缩伪影，对密集文字反而降低识别率。
        return data, detected_mime

    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    if max(width, height) > MAX_VISION_EDGE:
        image.thumbnail((MAX_VISION_EDGE, MAX_VISION_EDGE), Image.LANCZOS)

    candidate = b""
    for quality in (88, 80, 72, 64):
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        candidate = buffer.getvalue()
        if len(candidate) <= MAX_VISION_BYTES:
            return candidate, "image/jpeg"
    return candidate or data, "image/jpeg"

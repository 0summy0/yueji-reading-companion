from __future__ import annotations

import base64
import ipaddress
import json
import random
import re
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from .base import AIProvider, EmbeddingResult, ImageResult, OCRProvider, ProviderError, TextResult
from ..vision import prepare_for_vision

MAX_RESPONSE_BYTES = 256 * 1024
MAX_RESPONSE_CHARS = 20_000
# 视觉请求要先把整张图编码进请求体再完成多模态编码，耗时通常远高于纯文本。
DEFAULT_TIMEOUT_SECONDS = 30
VISION_TIMEOUT_SECONDS = 90
# 结构化/OCR 输出一口气写完才可能被解析；给得太小会让 JSON 被截断，表现就是“时好时坏”。
VISION_MAX_TOKENS = 1000
OCR_MAX_TOKENS = 4000
# 只有瞬时故障值得重试；参数与鉴权错误重试只会重复消耗配额。
RETRYABLE_CATEGORIES = {"timeout", "network", "rate_limited", "server"}
MAX_ATTEMPTS = 3


def _parse_retry_after(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        return max(0.0, min(float(raw), 8.0))
    except ValueError:
        return None


def validate_openai_base_url(base_url: str, allowed_hosts: tuple[str, ...]) -> str:
    try:
        parsed = urlparse(base_url.strip())
        # parsed.port 对畸形端口会抛 ValueError，必须转换为安全 400。
        port = parsed.port
    except ValueError as exc:
        raise ProviderError("bad_request", "Base URL 端口无效") from exc
    if parsed.scheme.lower() != "https":
        raise ProviderError("bad_request", "自定义端点必须使用 HTTPS")
    if parsed.username or parsed.password:
        raise ProviderError("bad_request", "Base URL 不允许包含用户信息")
    if parsed.query or parsed.fragment:
        raise ProviderError("bad_request", "Base URL 不允许包含查询或片段")
    if port not in (None, 443):
        raise ProviderError("bad_request", "Base URL 必须使用 443 端口")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise ProviderError("bad_request", "Base URL 缺少主机名")
    if not any(hostname == allowed or hostname.endswith("." + allowed) for allowed in allowed_hosts):
        raise ProviderError("bad_request", "该域名不在管理员允许的 API 主机清单中")
    try:
        ipaddress.ip_address(hostname)
        raise ProviderError("bad_request", "Base URL 必须使用受允许的服务域名，不能直接填写 IP")
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ProviderError("network", "API 域名 DNS 解析失败") from exc
    if not infos:
        raise ProviderError("network", "API 域名 DNS 解析失败")
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise ProviderError("network", "API 域名解析结果无效")
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ProviderError("bad_request", "API 域名解析到私有、回环或保留地址，已拒绝")
    path = parsed.path or "/"
    if ".." in path or not path.startswith("/"):
        raise ProviderError("bad_request", "Base URL 路径无效")
    return parsed._replace(path=path.rstrip("/") or "/").geturl().rstrip("/")


class OpenAICompatibleProvider(AIProvider, OCRProvider):
    """OpenAI-compatible Chat Completions HTTP 适配器。禁止重定向，仅在服务端持有密钥。"""

    def __init__(
        self,
        base_url: str,
        model_id: str,
        api_key: str,
        allowed_hosts: tuple[str, ...],
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = MAX_ATTEMPTS,
        sleep: Any | None = None,
    ):
        self.base_url = validate_openai_base_url(base_url, allowed_hosts)
        self.model_id = model_id
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self._sleep = sleep or time.sleep
        self.client = httpx.Client(timeout=httpx.Timeout(timeout_seconds), follow_redirects=False, transport=transport)

    def close(self) -> None:
        self.client.close()

    def _endpoint(self, name: str) -> str:
        path = urlparse(self.base_url).path or ""
        if path.rstrip("/").endswith(f"/{name}"):
            return self.base_url
        return f"{self.base_url}/{name}"

    def _map_http_error(self, status: int, message: str, retry_after: float | None = None) -> ProviderError:
        lower = message.lower()

        def fail(category: str, text: str) -> ProviderError:
            return ProviderError(category, text, retry_after)

        if status == 401:
            return fail("auth", "API Key 无效、已过期或格式不正确（401）")
        if status == 403:
            return fail("auth", "API Key 没有访问该模型或接口的权限（403）")
        # DeepSeek 余额耗尽返回 402；以前会被当成普通请求被拒，用户误以为是 Key 失效。
        if status == 402 or any(term in lower for term in ["insufficient balance", "insufficient_quota", "out of balance", "account balance"]):
            return fail("payment_required", "账户余额不足或套餐配额已耗尽（402）")
        if status == 429:
            return fail("rate_limited", "模型服务限流或配额不足（429）")
        if status in {408, 504}:
            return fail("timeout", "模型服务请求超时")
        if status >= 500:
            return fail("server", "模型服务端错误（5xx）")
        # 只有明确“不接受图片/视觉”的能力错误才判 unsupported；参数、尺寸、配额必须归类真实原因。
        if any(term in lower for term in [
            "does not support image", "not support vision", "multimodal is not supported",
            "image_url is not supported", "invalid image_url", "image input is not supported",
        ]):
            return fail("unsupported", "当前模型接口明确不支持图片输入")
        if any(term in lower for term in [
            "image dimensions", "image size", "image too large", "payload too large",
            "max image size", "request too large", "too many images", "request entity too large",
        ]):
            return fail("image_too_large", "图片尺寸或体积超过服务商限制")
        if any(term in lower for term in [
            "unsupported image format", "invalid image format", "unsupported image",
            "failed to download image", "cannot read image", "invalid image",
        ]):
            return fail("image_unreadable", "图片格式不被接受或无法解析")
        if "response_format" in lower or "json mode" in lower or "json_object" in lower:
            return fail("json_mode_unsupported", "当前服务商不接受 response_format/json_object 参数")
        if status == 404 or "model not found" in lower or "does not exist" in lower:
            return fail("model_not_found", "模型或端点不存在（404）")
        return fail("bad_request", f"模型请求被拒绝（HTTP {status}）")

    @staticmethod
    def _read_limited(response: httpx.Response) -> bytes:
        length = response.headers.get("content-length")
        if length:
            try:
                if int(length) > MAX_RESPONSE_BYTES:
                    raise ProviderError("bad_response", "模型服务响应超过大小限制")
            except ValueError:
                raise ProviderError("bad_response", "模型服务响应长度头无效")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise ProviderError("bad_response", "模型服务响应超过大小限制")
            chunks.append(chunk)
        return b"".join(chunks)

    def _attempt(self, endpoint: str, payload: dict[str, Any], timeout: float | None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        kwargs: dict[str, Any] = {"headers": headers, "json": payload}
        if timeout is not None:
            kwargs["timeout"] = timeout
        try:
            with self.client.stream("POST", self._endpoint(endpoint), **kwargs) as response:
                if response.is_redirect:
                    raise ProviderError("redirect", "模型服务端返回重定向，已拒绝")
                retry_after = _parse_retry_after(response.headers.get("retry-after"))
                raw = self._read_limited(response)
                status = response.status_code
        except httpx.TimeoutException as exc:
            raise ProviderError("timeout", "模型服务请求超时") from exc
        except httpx.TransportError as exc:
            raise ProviderError("network", "模型服务网络连接失败") from exc

        message = ""
        if status >= 400:
            try:
                error_body = json.loads(raw.decode("utf-8", errors="replace"))
                if isinstance(error_body, dict):
                    error = error_body.get("error")
                    if isinstance(error, dict):
                        message = str(error.get("message") or "")
                    elif error:
                        message = str(error)
            except (ValueError, UnicodeDecodeError):
                message = ""
            raise self._map_http_error(status, message, retry_after)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProviderError("bad_response", "模型服务返回了非 JSON 响应") from exc
        if not isinstance(body, dict):
            raise ProviderError("bad_response", "模型服务响应格式无效")
        return body

    def _post(self, endpoint: str, payload: dict[str, Any], timeout: float | None = None) -> dict[str, Any]:
        """只对瞬时故障重试：网络、超时、限流与 5xx。鉴权与参数类错误立刻失败，避免重复消耗配额。"""
        last: ProviderError | None = None
        for attempt in range(self.max_attempts):
            try:
                return self._attempt(endpoint, payload, timeout)
            except ProviderError as error:
                last = error
                if error.category not in RETRYABLE_CATEGORIES or attempt >= self.max_attempts - 1:
                    raise
                delay = error.retry_after if error.retry_after is not None else 0.8 * (2 ** attempt) + random.uniform(0, 0.25)
                self._sleep(delay)
        raise last if last else ProviderError("network", "模型服务请求失败")

    def _message_content(self, body: dict[str, Any]) -> str:
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError("bad_response", "模型服务没有返回 choices")
        first = choices[0]
        if not isinstance(first, dict) or not isinstance(first.get("message"), dict):
            raise ProviderError("bad_response", "模型服务响应缺少 message")
        message = first["message"]
        content = message.get("content")
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            text = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict)).strip()
        else:
            text = ""
        # 被 max_tokens 截断时 JSON 一定残缺，必须明确报“截断”，而不是让用户看到解析兜底后的伪失败。
        if first.get("finish_reason") == "length" or message.get("finish_reason") == "length":
            raise ProviderError("response_truncated", "模型输出被 max_tokens 截断，结构化结果不完整")
        if not text:
            reasoning = message.get("reasoning_content")
            if isinstance(reasoning, str) and reasoning.strip():
                raise ProviderError("reasoning_only", "模型只产出了推理过程，没有可解析的答案（推理模型需更大的 max_tokens）")
            raise ProviderError("bad_response", "模型服务返回了空内容")
        if len(text) > MAX_RESPONSE_CHARS:
            raise ProviderError("bad_response", "模型服务返回内容超过长度限制")
        return text

    def _chat(self, messages: list[dict[str, Any]], max_tokens: int, json_mode: bool = False, timeout: float | None = None) -> str:
        payload: dict[str, Any] = {"model": self.model_id, "messages": messages, "max_tokens": max_tokens}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return self._message_content(self._post("chat/completions", payload, timeout))

    def generate_text(self, prompt: str) -> TextResult:
        text = self._chat([
            {"role": "system", "content": "你是阅迹的只读工具。只完成当前极简任务，不讨论无关内容。"},
            {"role": "user", "content": prompt},
        ], max_tokens=40)
        return TextResult(text=text, model_id=self.model_id)

    def analyze_image(self, image_bytes: bytes, prompt: str, mime_type: str = "image/png") -> ImageResult:
        prepared, prepared_mime = prepare_for_vision(image_bytes, mime_type)
        encoded = base64.b64encode(prepared).decode("ascii")
        content = [
            {"type": "text", "text": prompt},
            # detail=high 保留原图：中文书页与六位码这类小字一旦被降采样就会读错或读不出来。
            {"type": "image_url", "image_url": {"url": f"data:{prepared_mime};base64,{encoded}", "detail": "high"}},
        ]
        text = self._chat([
            {"role": "system", "content": "你负责读取图片。只返回请求要求的结构化结果，不要猜测。"},
            {"role": "user", "content": content},
        ], max_tokens=VISION_MAX_TOKENS, timeout=VISION_TIMEOUT_SECONDS)
        return ImageResult(fields=parse_model_fields(text), model_id=self.model_id)

    def ocr_probe_page(self, image_bytes: bytes) -> ImageResult:
        prompt = (
            "这是一张合成中文书页。顶部随机标识和底部页脚不是正文。请只识别中间两行正文，并分别填写 lines。"
            '只返回 JSON：{"lines":["正文第一行","正文第二行"],"marker":"顶部随机标识"}。'
        )
        return self.analyze_image(image_bytes, prompt, "image/png")

    def ocr_page(self, image_bytes: bytes, language: str = "zh-CN") -> ImageResult:
        prepared, prepared_mime = prepare_for_vision(image_bytes, "image/png")
        encoded = base64.b64encode(prepared).decode("ascii")
        content = [
            {"type": "text", "text": "请识别这张中文书页中的所有清晰正文行，按从上到下的原顺序输出；页眉、页脚、噪声不要写入。只返回 JSON：{\"lines\":[\"...\",\"...\"]}"},
            {"type": "image_url", "image_url": {"url": f"data:{prepared_mime};base64,{encoded}", "detail": "high"}},
        ]
        text = self._chat([
            {"role": "system", "content": "你是书页 OCR 工具。只输出可核对文字，不编造、不总结。"},
            {"role": "user", "content": content},
        ], max_tokens=OCR_MAX_TOKENS, timeout=VISION_TIMEOUT_SECONDS)
        return ImageResult(fields=parse_model_fields(text), model_id=self.model_id)

    def extract_structured(self, prompt: str, schema_name: str) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": f"你是阅读记忆整理器。只输出符合 {schema_name} 的 JSON，不输出其他文字。"},
            {"role": "user", "content": prompt},
        ]
        try:
            text = self._chat(messages, max_tokens=1000, json_mode=True)
        except ProviderError as error:
            if error.category != "json_mode_unsupported":
                raise
            # 兼容不支持 JSON mode 的服务商：只重试一次省略参数，仍由后端 JSON Schema 校验。
            text = self._chat(messages, max_tokens=1000, json_mode=False)
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProviderError("bad_response", "结构化输出不是合法 JSON") from exc
        if not isinstance(value, dict):
            raise ProviderError("bad_response", "结构化输出必须是 JSON 对象")
        return value

    def embed_text(self, texts: list[str]) -> EmbeddingResult:
        payload = {"model": self.model_id, "input": texts[:32]}
        body = self._post("embeddings", payload)
        data = body.get("data")
        if not isinstance(data, list):
            raise ProviderError("unsupported", "当前端点未返回 Embedding 数据")
        vectors: list[list[float]] = []
        for item in data:
            if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
                raise ProviderError("bad_response", "Embedding 响应格式无效")
            vectors.append([float(value) for value in item["embedding"]])
        dimensions = len(vectors[0]) if vectors else 0
        return EmbeddingResult(vectors=vectors, model_id=self.model_id, dimensions=dimensions)


def parse_model_fields(text: str) -> dict[str, Any]:
    """从真实模型输出中提取 JSON；失败时做保守正则兜底，不把自由文本当成事实。"""
    candidate = text.strip()
    # 模型经常用 ```json 代码块包裹答案；去掉围栏再解析，可避免“明明识别正确却被判失败”。
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        value = json.loads(candidate)
        return value if isinstance(value, dict) else {"raw": candidate}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, flags=re.S)
        if match:
            try:
                value = json.loads(match.group(0))
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                pass
    fields: dict[str, Any] = {"raw": candidate}
    code = re.search(r"(?:码|code)[:：\s]*([A-Z0-9]{6})", candidate, flags=re.I)
    color = re.search(r"(红色|绿色|蓝色)", candidate)
    marker = re.search(r"(页[A-Z0-9]{3,6})", candidate, flags=re.I)
    if code:
        fields["code"] = code.group(1).upper()
    if color:
        fields["color"] = color.group(1)
    if marker:
        fields["marker"] = marker.group(1).upper()
    return fields

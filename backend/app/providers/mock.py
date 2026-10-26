from __future__ import annotations

import hashlib
from typing import Any

from .base import AIProvider, EmbeddingResult, ImageResult, OCRProvider, ProviderError, TextResult


class MockProvider(AIProvider, OCRProvider):
    """离线场景演员。所有结果均为模拟，绝不发起网络请求。"""

    def __init__(self, scenario: str = "success", model_id: str = "mock-reader-v1"):
        self.scenario = scenario
        self.model_id = model_id
        # 仅测试夹具在内存中注入合成探针真值；不进入提示词、文件名或日志。
        self.mock_probe_truth: dict[str, Any] | None = None

    def close(self) -> None:
        return None

    def _raise_if_error(self) -> None:
        mapping = {
            "auth_error": ("auth", "模拟鉴权失败"),
            "rate_limited": ("rate_limited", "模拟限流或配额不足"),
            "timeout": ("timeout", "模拟请求超时"),
        }
        if self.scenario in mapping:
            category, message = mapping[self.scenario]
            raise ProviderError(category, message)

    def generate_text(self, prompt: str) -> TextResult:
        self._raise_if_error()
        return TextResult("MOCK_OK" if prompt else "", self.model_id)

    def analyze_image(self, image_bytes: bytes, prompt: str, mime_type: str = "image/png") -> ImageResult:
        self._raise_if_error()
        if not image_bytes.startswith(b"\x89PNG"):
            raise ProviderError("bad_request", "模拟图片格式错误")
        if self.scenario == "unsupported":
            raise ProviderError("unsupported", "模拟接口明确拒绝图片输入")
        if self.scenario == "hallucinated" or not self.mock_probe_truth:
            return ImageResult({"code": "000000", "color": "未知", "shape": "圆形"}, self.model_id)
        return ImageResult(
            {"code": self.mock_probe_truth["code"], "color": self.mock_probe_truth["color"], "shape": self.mock_probe_truth["shape"]},
            self.model_id,
        )

    def extract_structured(self, prompt: str, schema_name: str) -> dict[str, Any]:
        self._raise_if_error()
        return {"summary": "模拟结果，未提炼真实笔记", "cards": [], "candidate_links": [], "schema": schema_name}

    def embed_text(self, texts: list[str]) -> EmbeddingResult:
        self._raise_if_error()
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vectors.append([round(byte / 255 - 0.5, 6) for byte in digest[:16]])
        return EmbeddingResult(vectors, "mock-hash-embedding-v1", 16)

    def ocr_page(self, image_bytes: bytes, language: str = "zh-CN") -> ImageResult:
        self._raise_if_error()
        if not image_bytes.startswith(b"\x89PNG"):
            raise ProviderError("bad_request", "模拟图片格式错误")
        if self.scenario == "unsupported":
            raise ProviderError("unsupported", "模拟图片接口不可用")
        if self.scenario == "hallucinated" or not self.mock_probe_truth:
            return ImageResult({"lines": ["模拟答非所问"], "marker": "UNKNOWN"}, self.model_id)
        if self.scenario == "partial":
            return ImageResult({"lines": [self.mock_probe_truth["page_lines"][0]], "marker": self.mock_probe_truth["marker"]}, self.model_id)
        return ImageResult({"lines": self.mock_probe_truth["page_lines"], "marker": self.mock_probe_truth["marker"]}, self.model_id)

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class ProviderError(RuntimeError):
    def __init__(self, category: str, safe_message: str, retry_after: float | None = None):
        super().__init__(safe_message)
        self.category = category
        self.safe_message = safe_message
        # 服务端建议的重试等待秒数（取自 Retry-After），用于限流退避。
        self.retry_after = retry_after


@dataclass(frozen=True)
class TextResult:
    text: str
    model_id: str


@dataclass(frozen=True)
class ImageResult:
    fields: dict[str, Any]
    model_id: str


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model_id: str
    dimensions: int


class AIProvider(ABC):
    """聊天、视觉、结构化与向量能力彼此独立，不能按供应商推定。"""

    @abstractmethod
    def generate_text(self, prompt: str) -> TextResult:
        raise NotImplementedError

    @abstractmethod
    def analyze_image(self, image_bytes: bytes, prompt: str, mime_type: str = "image/png") -> ImageResult:
        raise NotImplementedError

    @abstractmethod
    def extract_structured(self, prompt: str, schema_name: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def embed_text(self, texts: list[str]) -> EmbeddingResult:
        raise NotImplementedError


class OCRProvider(ABC):
    """独立书页 OCR 接口，可路由到与聊天模型不同的服务。"""

    @abstractmethod
    def ocr_page(self, image_bytes: bytes, language: str = "zh-CN") -> ImageResult:
        raise NotImplementedError

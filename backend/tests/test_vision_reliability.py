"""图片识别可靠性：重试退避、配额与截断识别、输出解析、发送前图片规格收敛。"""
from __future__ import annotations

import io
import json

import httpx
import pytest
from PIL import Image

from app.providers.base import ProviderError
from app.providers.openai import OCR_MAX_TOKENS, VISION_MAX_TOKENS, VISION_TIMEOUT_SECONDS, OpenAICompatibleProvider, parse_model_fields
from app.vision import MAX_VISION_EDGE, prepare_for_vision

HOSTS = ("api.deepseek.com",)
BASE = "https://api.deepseek.com"


def ok_body(content: str, finish_reason: str = "stop", message_extra: dict | None = None) -> dict:
    message = {"role": "assistant", "content": content}
    if message_extra:
        message.update(message_extra)
    return {"choices": [{"message": message, "finish_reason": finish_reason}], "usage": {}}


def provider_with(script: list[dict], max_attempts: int = 3):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        step = script[min(calls["count"] - 1, len(script) - 1)]
        return httpx.Response(step.get("status", 200), json=step.get("body", {}), headers=step.get("headers", {}))

    provider = OpenAICompatibleProvider(
        BASE, "deepseek-flash", "sk-test", HOSTS,
        transport=httpx.MockTransport(handler), max_attempts=max_attempts, sleep=lambda _: None,
    )
    return provider, calls


def test_rate_limited_then_success_retries_once():
    provider, calls = provider_with([
        {"status": 429, "body": {"error": {"message": "rate limit"}}, "headers": {"retry-after": "1"}},
        {"status": 200, "body": ok_body('{"code":"AB12CD","color":"红色"}')},
    ])
    result = provider.analyze_image(b"fake", "读一下")
    assert result.fields["code"] == "AB12CD"
    assert calls["count"] == 2


def test_server_error_exhausts_retries_then_raises():
    provider, calls = provider_with([{"status": 500, "body": {"error": {"message": "server broke"}}}])
    with pytest.raises(ProviderError) as raised:
        provider.analyze_image(b"fake", "读一下")
    assert raised.value.category == "server"
    assert calls["count"] == 3


def test_bad_request_is_not_retried_to_avoid_burning_quota():
    provider, calls = provider_with([{"status": 400, "body": {"error": {"message": "invalid request"}}}])
    with pytest.raises(ProviderError) as raised:
        provider.analyze_image(b"fake", "读一下")
    assert raised.value.category == "bad_request"
    assert calls["count"] == 1


def test_402_balance_exhausted_is_reported_as_quota_not_key_problem():
    provider, _ = provider_with([{"status": 402, "body": {"error": {"message": "Insufficient balance"}}}])
    with pytest.raises(ProviderError) as raised:
        provider.generate_text("返回正常")
    assert raised.value.category == "payment_required"
    assert "余额" in raised.value.safe_message


def test_truncated_output_is_not_silently_parsed_as_failure():
    provider, _ = provider_with([{"status": 200, "body": ok_body('{"lines":["第一行","第', finish_reason="length")}])
    with pytest.raises(ProviderError) as raised:
        provider.ocr_page(b"fake")
    assert raised.value.category == "response_truncated"


def test_reasoning_only_output_has_clear_category():
    provider, _ = provider_with([
        {"status": 200, "body": ok_body("", finish_reason="stop", message_extra={"reasoning_content": "让我想想…"})},
    ])
    with pytest.raises(ProviderError) as raised:
        provider.generate_text("返回正常")
    assert raised.value.category == "reasoning_only"


def test_vision_request_uses_detail_high_and_generous_token_budget():
    seen = {}
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json=ok_body('{"lines":["甲","乙"]}'))

    provider = OpenAICompatibleProvider(
        BASE, "deepseek-flash", "sk-test", HOSTS, transport=httpx.MockTransport(handler), sleep=lambda _: None,
    )
    provider.ocr_page(b"fake")
    payload = captured[-1]
    image_part = payload["messages"][1]["content"][1]["image_url"]
    assert image_part["detail"] == "high"
    assert payload["max_tokens"] >= OCR_MAX_TOKENS > 1200
    assert seen == {}

    captured.clear()
    provider.analyze_image(b"fake", "读一下")
    payload = captured[-1]
    assert payload["messages"][1]["content"][1]["image_url"]["detail"] == "high"
    assert payload["max_tokens"] >= VISION_MAX_TOKENS > 220
    assert VISION_TIMEOUT_SECONDS > 30


def test_fenced_json_answer_is_parsed_instead_of_fallback():
    fields = parse_model_fields('```json\n{"code":"ZX9K2M","color":"蓝色"}\n```')
    assert fields["code"] == "ZX9K2M"
    assert fields["color"] == "蓝色"


def test_prepare_for_vision_downscales_huge_image():
    image = Image.new("RGB", (4000, 3000), (240, 238, 230))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    prepared, mime = prepare_for_vision(buffer.getvalue())
    assert mime == "image/jpeg"
    with Image.open(io.BytesIO(prepared)) as result:
        assert max(result.size) <= MAX_VISION_EDGE
        assert result.size[0] < 4000
    assert len(prepared) < len(buffer.getvalue())


def test_prepare_for_vision_uses_actual_jpeg_mime_when_fallback_is_png():
    image = Image.new("RGB", (800, 500), (240, 238, 230))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    prepared, mime = prepare_for_vision(buffer.getvalue(), "image/png")
    assert prepared.startswith(b"\xff\xd8\xff")
    assert mime == "image/jpeg"


def test_prepare_for_vision_keeps_unreadable_bytes_untouched():
    prepared, mime = prepare_for_vision(b"not-an-image")
    assert prepared == b"not-an-image"
    assert mime == "image/png"

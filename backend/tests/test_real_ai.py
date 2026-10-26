from __future__ import annotations

import base64
import io
import json
import socket
from typing import Any

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from PIL import Image

from app import ai
from app.main import app
from app.providers.base import ImageResult, ProviderError, TextResult
from app.providers.openai import OpenAICompatibleProvider, validate_openai_base_url

PUBLIC_IP = "93.184.216.34"


def public_dns(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_IP, port))])


@pytest.fixture
def secure_client(tmp_path, monkeypatch):
    public_dns(monkeypatch)
    monkeypatch.setenv("YUEJI_DATA_DIR", str(tmp_path / "secure"))
    monkeypatch.setenv("YUEJI_DATABASE", "secure.sqlite3")
    monkeypatch.setenv("YUEJI_SEED_SAMPLES", "false")
    monkeypatch.setenv("YUEJI_AUTH_REQUIRED", "false")
    monkeypatch.setenv("YUEJI_MASTER_KEY", Fernet.generate_key().decode("ascii"))
    with TestClient(app) as test_client:
        yield test_client


class FakeRealProvider:
    def __init__(self, truth: dict[str, Any] | None = None, fail: str | None = None):
        self.truth = truth or {}
        self.fail = fail

    def _maybe_fail(self, kind: str):
        if self.fail == kind:
            raise ProviderError(self.fail, f"模拟真实{kind}错误")

    def generate_text(self, prompt: str) -> TextResult:
        self._maybe_fail("auth")
        self._maybe_fail("rate_limited")
        self._maybe_fail("timeout")
        return TextResult("正常", "fake-real")

    def analyze_image(self, image_bytes: bytes, prompt: str, mime_type: str = "image/png") -> ImageResult:
        self._maybe_fail("auth")
        self._maybe_fail("rate_limited")
        self._maybe_fail("timeout")
        self._maybe_fail("unsupported")
        return ImageResult({"code": self.truth.get("code", ""), "color": self.truth.get("color", ""), "shape": "圆形"}, "fake-real")

    def ocr_page(self, image_bytes: bytes, language: str = "zh-CN") -> ImageResult:
        self._maybe_fail("auth")
        self._maybe_fail("rate_limited")
        self._maybe_fail("timeout")
        self._maybe_fail("unsupported")
        if self.fail == "partial":
            return ImageResult({"lines": self.truth.get("page_lines", [])[:1], "marker": self.truth.get("marker", "")}, "fake-real")
        return ImageResult({"lines": self.truth.get("page_lines", []), "marker": self.truth.get("marker", "")}, "fake-real")

    def extract_structured(self, prompt: str, schema_name: str):
        return {"summary": "fake", "cards": [], "candidate_links": []}

    def embed_text(self, texts: list[str]):
        raise ProviderError("unsupported", "fake endpoint 不支持向量")

    def close(self):
        return None


def patch_provider(monkeypatch, provider: FakeRealProvider):
    def factory(settings, row, truth=None):
        provider.truth = truth or provider.truth
        return provider

    monkeypatch.setattr(ai, "_provider_for_connection", factory)


def real_payload(api_key: str | None = "sk-real-secret-for-tests"):
    value = {
        "alias": "真实 OpenAI 测试",
        "provider_type": "openai_compatible",
        "model_id": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
    }
    if api_key is not None:
        value["api_key"] = api_key
    return value


def test_real_connection_encrypts_key_updates_without_echo(secure_client, tmp_path, monkeypatch):
    provider = FakeRealProvider()
    patch_provider(monkeypatch, provider)
    secret = "sk-real-secret-for-tests"
    response = secure_client.post("/api/ai/connections", json=real_payload(secret))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["credential_mode"] == "stored_encrypted"
    assert body["has_saved_key"] is True
    assert body["capabilities"]["text"]["status"] == "verified"
    assert secret not in response.text and "secret_ref" not in response.text
    connection_id = body["id"]

    update = secure_client.post("/api/ai/connections", json={**real_payload(None), "connection_id": connection_id, "model_id": "gpt-4o-mini-2"})
    assert update.status_code == 201, update.text
    assert update.json()["has_saved_key"] is True
    assert secret not in update.text

    from app.db import connect
    with connect(secure_client.app.state.settings) as conn:
        stored = conn.execute("SELECT secret_ref FROM ai_connections WHERE id = ?", (connection_id,)).fetchone()[0]
    assert stored.startswith("fernet:v1:")
    assert secret not in stored


def test_real_connection_requires_master_key_and_rejects_bad_endpoint(client, monkeypatch):
    public_dns(monkeypatch)
    secret = "must-not-be-echoed"
    response = client.post("/api/ai/connections", json=real_payload(secret))
    assert response.status_code == 503
    assert secret not in response.text

    bad = client.post("/api/ai/connections", json={**real_payload(secret), "base_url": "http://api.openai.com/v1"})
    assert bad.status_code == 400
    assert "HTTPS" in bad.json()["detail"]


def test_openai_ssrf_url_validation(monkeypatch):
    hosts = ("api.openai.com",)
    public_dns(monkeypatch)
    assert validate_openai_base_url("https://api.openai.com/v1", hosts) == "https://api.openai.com/v1"
    rejected = [
        "http://api.openai.com/v1",
        "https://api.openai.com:8443/v1",
        "https://user:pass@api.openai.com/v1",
        "https://api.openai.com/v1?x=1",
        "https://api.openai.com/v1#x",
        "https://example.com/v1",
        "https://localhost/v1",
        "https://127.0.0.1/v1",
    ]
    for url in rejected:
        with pytest.raises(ProviderError):
            validate_openai_base_url(url, hosts)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))])
    with pytest.raises(ProviderError, match="私有"):
        validate_openai_base_url("https://api.openai.com/v1", hosts)


def mock_provider(monkeypatch, handler, base_url="https://api.deepseek.com", model_id="deepseek-flash"):
    public_dns(monkeypatch)
    requests: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(wrapped)
    provider = OpenAICompatibleProvider(base_url, model_id, "sk-test", ("api.deepseek.com", "api.openai.com"), transport=transport)
    return provider, requests


def json_response(content: str, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, content=content.encode("utf-8"), headers={"Content-Type": "application/json", **(headers or {})})


def chat_content_response(content: dict[str, Any], status: int = 200) -> httpx.Response:
    body = {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}
    return json_response(json.dumps(body, ensure_ascii=False), status=status)


def test_deepseek_chat_and_image_request_format(monkeypatch):
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content.decode("utf-8")))
        return chat_content_response({"code": "ABC123", "color": "红色"})

    provider, requests = mock_provider(monkeypatch, handler)
    image = Image.new("RGB", (64, 64), "#ffffff")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    result = provider.analyze_image(buffer.getvalue(), "读取图片")
    assert result.fields["code"] == "ABC123"
    assert requests[0].url == "https://api.deepseek.com/chat/completions"
    assert requests[0].headers["Authorization"] == "Bearer sk-test"
    payload = payloads[0]
    assert payload["model"] == "deepseek-flash"
    assert "temperature" not in payload
    content = payload["messages"][-1]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert base64.b64decode(content[1]["image_url"]["url"].split(",", 1)[1]).startswith(b"\x89PNG")
    provider.close()


def test_real_error_and_partial_statuses_are_not_conflated(secure_client, monkeypatch):
    provider = FakeRealProvider(fail="auth")
    patch_provider(monkeypatch, provider)
    response = secure_client.post("/api/ai/connections", json=real_payload())
    assert response.status_code == 201
    capabilities = response.json()["capabilities"]
    assert capabilities["text"]["status"] == "unverified_error"
    assert capabilities["vision_input"]["status"] == "unverified_error"
    assert capabilities["failure_category"] == "auth"

    partial = FakeRealProvider(fail="partial")
    patch_provider(monkeypatch, partial)
    response = secure_client.post("/api/ai/connections", json=real_payload())
    capabilities = response.json()["capabilities"]
    assert capabilities["vision_input"]["status"] == "verified"
    assert capabilities["page_ocr"]["status"] == "vision_partial"


def test_real_probe_truth_never_enters_prompt(secure_client, monkeypatch):
    seen: list[str] = []

    class SpyProvider(FakeRealProvider):
        def analyze_image(self, image_bytes: bytes, prompt: str, mime_type: str = "image/png") -> ImageResult:
            seen.append(prompt)
            assert self.truth["code"] not in prompt
            assert self.truth["page_lines"][0] not in prompt
            return super().analyze_image(image_bytes, prompt, mime_type)

    patch_provider(monkeypatch, SpyProvider())
    response = secure_client.post("/api/ai/connections", json=real_payload())
    assert response.status_code == 201
    assert len(seen) == 1


def test_adapter_error_categories_are_not_misclassified(monkeypatch):
    cases = [
        (400, {"error": {"message": "The model does not support response_format"}}, "json_mode_unsupported"),
        (400, {"error": {"message": "image dimensions exceed maximum size"}}, "image_too_large"),
        (404, {"error": {"message": "vision-model does not exist"}}, "model_not_found"),
        (400, {"error": {"message": "This model does not support image input"}}, "unsupported"),
    ]
    image = Image.new("RGB", (32, 32), "#fff")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    for status, body, category in cases:
        provider, _ = mock_provider(monkeypatch, lambda request, status=status, body=body: json_response(json.dumps(body), status=status))
        with pytest.raises(ProviderError) as error:
            provider.analyze_image(buffer.getvalue(), "读取图片")
        assert error.value.category == category
        provider.close()


def test_non_json_auth_and_rate_limit_keep_http_semantics(monkeypatch):
    for status, category in [(401, "auth"), (429, "rate_limited")]:
        provider, _ = mock_provider(monkeypatch, lambda request, status=status: httpx.Response(status, content=b"<html>Unauthorized</html>", headers={"Content-Type": "text/html"}))
        with pytest.raises(ProviderError) as error:
            provider.generate_text("只返回正常")
        assert error.value.category == category
        provider.close()


def test_json_mode_falls_back_once_without_response_format(monkeypatch):
    payloads: list[dict[str, Any]] = []
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        payload = json.loads(request.content.decode("utf-8"))
        payloads.append(payload)
        if calls["count"] == 1:
            return json_response('{"error":{"message":"The model does not support response_format"}}', status=400)
        return chat_content_response({"answer": "ok", "citations": [], "uncertainty": "low", "spoiler_risk": "low"})

    provider, _ = mock_provider(monkeypatch, handler)
    result = provider.extract_structured("按证据回答", "EvidenceAnswer")
    assert result["answer"] == "ok"
    assert calls["count"] == 2
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in payloads[1]
    provider.close()


def test_real_ocr_and_probe_have_different_budgets_and_contracts(monkeypatch):
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        payloads.append(payload)
        if payload["max_tokens"] > 2000:
            return chat_content_response({"lines": "灯亮着，归还便有了方向。\n我把沉默夹进书页。"})
        return chat_content_response({"lines": ["灯亮着，归还便有了方向。", "我把沉默夹进书页。"], "marker": "页TEST"})

    provider, _ = mock_provider(monkeypatch, handler)
    image = Image.new("RGB", (64, 64), "#fff")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    real = provider.ocr_page(buffer.getvalue())
    assert "灯亮着" in str(real.fields.get("lines"))
    probe = provider.ocr_probe_page(buffer.getvalue())
    assert probe.fields["marker"] == "页TEST"
    # OCR 与探针的预算分级：书页识别远大于单次视觉问答，避免 JSON 被截断。
    assert payloads[0]["max_tokens"] >= 1000
    assert 220 < payloads[1]["max_tokens"] < payloads[0]["max_tokens"]
    assert "顶部随机标识" in payloads[1]["messages"][-1]["content"][0]["text"]
    assert "页脚不是正文" in payloads[1]["messages"][-1]["content"][0]["text"]
    provider.close()


def test_deepseek_v41_display_aliases_normalize_only_on_official_host():
    assert ai.normalize_model_id("https://api.deepseek.com", "DeepSeek V4.1 Flash") == "deepseek-flash"
    assert ai.normalize_model_id("https://api.deepseek.com", "deepseek-v4-flash-vision-exp") == "deepseek-flash"
    assert ai.normalize_model_id("https://gateway.example.com", "DeepSeek V4.1 Flash") == "DeepSeek V4.1 Flash"


def test_probe_accepts_safe_format_variations_but_not_wrong_content():
    expected = ["灯亮着，归还便有了方向。", "我把沉默夹进书页。"]
    assert ai._probe_lines_match(["灯亮着, 归还便有了方向。", "我把沉默夹进书页。", "（识别完成）"], expected)
    assert ai._probe_lines_match("灯亮着，归还便有了方向。\n我把沉默夹进书页。", expected)
    assert not ai._probe_lines_match(["灯亮着，归还便有了方向。", "这是另一行。"], expected)
    assert ai._probe_color("green") == "绿色"


def test_streaming_response_size_limits(monkeypatch):
    from app.providers.openai import MAX_RESPONSE_BYTES

    provider, _ = mock_provider(monkeypatch, lambda request: httpx.Response(200, content=b"", headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)}))
    with pytest.raises(ProviderError, match="大小限制"):
        provider.generate_text("只返回正常")
    provider.close()

    provider, _ = mock_provider(monkeypatch, lambda request: httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1), headers={"Content-Type": "application/json"}))
    with pytest.raises(ProviderError, match="大小限制"):
        provider.generate_text("只返回正常")
    provider.close()


def test_malformed_url_port_is_safe_400(monkeypatch):
    public_dns(monkeypatch)
    with pytest.raises(ProviderError, match="端口"):
        validate_openai_base_url("https://api.deepseek.com:bad/v1", ("api.deepseek.com",))


def test_global_real_provider_disable_blocks_existing_connections(monkeypatch):
    monkeypatch.setenv("YUEJI_ENABLE_REAL_PROVIDERS", "false")
    from app.config import get_settings
    settings = get_settings()
    row = {"provider_type": "openai_compatible", "model_id": "deepseek-flash", "base_url": "https://api.deepseek.com", "secret_ref": "fernet:v1:invalid"}
    with pytest.raises(Exception) as error:
        ai._provider_for_connection(settings, row)
    assert "禁用" in str(error.value)

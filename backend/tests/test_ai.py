from __future__ import annotations

import json

import pytest

from app.db import connect
from app.providers.mock import MockProvider


def payload(scenario="success", alias="离线演示", model="mock-reader-v1"):
    return {"alias": alias, "provider_type": "mock", "model_id": model, "base_url": "mock://local", "scenario": scenario}


@pytest.mark.parametrize(
    "scenario,text,vision,page,category",
    [
        ("success", "verified", "verified", "verified", None),
        ("unsupported", "verified", "unsupported", "unsupported", "unsupported"),
        ("hallucinated", "verified", "inconclusive", "inconclusive", "challenge_mismatch"),
        ("partial", "verified", "verified", "vision_partial", "page_ocr_mismatch"),
        ("auth_error", "unverified_error", "unverified_error", "unverified_error", "auth"),
        ("rate_limited", "unverified_error", "unverified_error", "unverified_error", "rate_limited"),
        ("timeout", "unverified_error", "unverified_error", "unverified_error", "timeout"),
    ],
)
def test_mock_capability_states(client, scenario, text, vision, page, category):
    response = client.post("/api/ai/connections", json=payload(scenario))
    assert response.status_code == 201, response.text
    body = response.json()
    capabilities = body["capabilities"]
    assert capabilities["text"]["status"] == text
    assert capabilities["vision_input"]["status"] == vision
    assert capabilities["page_ocr"]["status"] == page
    assert capabilities["failure_category"] == category
    assert capabilities["simulation_notice"] == "模拟检测，不代表真实API能力"
    assert "secret_ref" not in body and "api_key" not in body
    rechecked = client.post(f"/api/ai/connections/{body['id']}/verify")
    assert rechecked.status_code == 200


def test_mock_rejects_keys_and_real_connections_without_echo(client):
    secret = "do-not-store-or-echo-this-key"
    response = client.post("/api/ai/connections", json={**payload(), "api_key": secret})
    assert response.status_code == 400
    assert secret not in response.text
    real = client.post("/api/ai/connections", json={**payload(), "provider_type": "openai_compatible", "base_url": "https://example.invalid"})
    assert real.status_code == 400
    assert "管理员允许" in real.json()["detail"] or "Key" in real.json()["detail"]
    invalid_key = client.post("/api/ai/connections", json={**payload(), "api_key": 87654321})
    assert invalid_key.status_code == 422
    assert "87654321" not in invalid_key.text
    assert client.get("/api/ai/connections").json()["items"] == []


def test_config_change_stales_old_check_and_retests(client):
    created = client.post("/api/ai/connections", json=payload()).json()
    old = client.post(
        "/api/ai/connections",
        json={**payload(model="mock-reader-v2"), "connection_id": created["id"]},
    )
    assert old.status_code == 201
    with connect(client.app.state.settings) as conn:
        checks = conn.execute(
            "SELECT text_status, config_fingerprint FROM ai_capability_checks WHERE connection_id = ? ORDER BY checked_at", (created["id"],)
        ).fetchall()
        assert [row["text_status"] for row in checks] == ["stale", "verified"]
        assert checks[0]["config_fingerprint"] != checks[1]["config_fingerprint"]


def test_probe_prompt_does_not_leak_truth(client, monkeypatch):
    original = MockProvider.analyze_image
    seen = []

    def spy(self, image_bytes, prompt, mime_type="image/png"):
        seen.append(prompt)
        assert self.mock_probe_truth["code"] not in prompt
        assert self.mock_probe_truth["page_lines"][0] not in prompt
        assert image_bytes.startswith(b"\x89PNG")
        return original(self, image_bytes, prompt, mime_type)

    monkeypatch.setattr(MockProvider, "analyze_image", spy)
    response = client.post("/api/ai/connections", json=payload())
    assert response.status_code == 201
    assert len(seen) == 1


def test_task_routes_enforce_separate_capabilities(client):
    partial = client.post("/api/ai/connections", json=payload("partial", "部分通过")).json()
    denied = client.put("/api/ai/task-routes", json={"routes": {"analyze_image": partial["id"]}})
    assert denied.status_code == 400
    success = client.post("/api/ai/connections", json=payload("success", "完整模拟")).json()
    routes = {name: success["id"] for name in ["generate_text", "analyze_image", "extract_structured", "embed_text", "ocr_page"]}
    accepted = client.put("/api/ai/task-routes", json={"routes": routes})
    assert accepted.status_code == 200
    assert accepted.json()["routes"] == routes


def test_mock_provider_has_all_independent_interfaces():
    provider = MockProvider()
    assert provider.generate_text("x").text == "MOCK_OK"
    assert len(provider.embed_text(["中文"]).vectors[0]) == 16
    assert provider.extract_structured("x", "NoteExtractionResult")["cards"] == []
    assert hasattr(provider, "ocr_page")


def test_task_routes_support_complete_replacement_and_clear(client):
    connection = client.post("/api/ai/connections", json=payload()).json()
    accepted = client.put("/api/ai/task-routes", json={"routes": {"generate_text": connection["id"]}})
    assert accepted.status_code == 200
    assert client.get("/api/ai/task-routes").json()["routes"] == {"generate_text": connection["id"]}
    cleared = client.put("/api/ai/task-routes", json={"routes": {}})
    assert cleared.status_code == 200
    assert cleared.json()["routes"] == {}
    assert client.get("/api/ai/task-routes").json()["routes"] == {}


def test_photo_path_exposes_actual_mock_capabilities_but_stays_manual(client):
    connection = client.post("/api/ai/connections", json=payload()).json()
    routed = client.put("/api/ai/task-routes", json={"routes": {"analyze_image": connection["id"]}})
    assert routed.status_code == 200
    status = client.get("/api/photo-path").json()
    assert status["capabilities"]["vision_input"]["status"] == "verified"
    assert status["capabilities"]["page_ocr"]["status"] == "verified"
    assert status["automatic_location_available"] is True
    assert status["display_path"] == "ai_vision"

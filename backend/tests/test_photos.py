from __future__ import annotations

import io
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import ai
from app.main import app
from app.providers.base import ImageResult
from conftest import import_txt


@pytest.fixture
def photo_book(client):
    book = import_txt(client, "# 第一章 起点\n阿尔法段落。\n\n贝塔段落。\n\n伽马段落。", filename="photo.txt", title="照片匹配书")
    connection = client.post("/api/ai/connections", json={"alias": "视觉", "provider_type": "mock", "model_id": "mock-reader-v1", "base_url": "mock://local", "scenario": "success"}).json()
    routed = client.put("/api/ai/task-routes", json={"routes": {"analyze_image": connection["id"]}})
    assert routed.status_code == 200
    items = client.get(f"/api/books/{book['id']}/passages").json()["items"]
    return client, book, items, connection


def jpeg_bytes() -> bytes:
    image = Image.new("RGB", (900, 500), "#f8f3e8")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


class FakePhotoProvider:
    def __init__(self, lines: list[str]):
        self.lines = lines

    def ocr_page(self, image_bytes: bytes, language: str = "zh-CN") -> ImageResult:
        return ImageResult({"lines": self.lines, "marker": "页TEST"}, "fake-photo")

    def close(self):
        return None


def test_photo_top3_never_advances_before_confirm(photo_book, monkeypatch):
    client, book, items, _ = photo_book
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: FakePhotoProvider([items[2]["text"]]))
    before = client.get(f"/api/books/{book['id']}").json()
    assert before["read_ranges"] == []

    response = client.post(
        f"/api/books/{book['id']}/location-attempts",
        files={"file": ("page.jpg", jpeg_bytes(), "image/jpeg")},
    )
    assert response.status_code == 201, response.text
    attempt = response.json()["attempt"]
    assert attempt["state"] == "candidates"
    assert attempt["ocr_text"] == "伽马段落。"
    assert [candidate["passage_id"] for candidate in attempt["candidates"]][0] == items[2]["id"]
    assert len(attempt["candidates"]) == 3

    middle = client.get(f"/api/books/{book['id']}").json()
    assert middle["read_ranges"] == []
    assert middle["progress"]["current_anchor"] is None

    invalid = client.post(f"/api/location-attempts/{attempt['id']}/confirm", json={
        "chosen_anchor": "pa_not_in_candidates", "started_at": "2026-10-25T03:00:00+08:00",
        "ended_at": "2026-10-25T03:20:00+08:00", "timezone": "Asia/Shanghai",
    })
    assert invalid.status_code == 400

    confirmed = client.post(f"/api/location-attempts/{attempt['id']}/confirm", json={
        "chosen_anchor": items[2]["id"], "started_at": "2026-10-25T03:00:00+08:00",
        "ended_at": "2026-10-25T03:20:00+08:00", "timezone": "Asia/Shanghai",
        "session_type": "skip", "anchor_read_confirmed": True, "reading_context": "在窗边试拍定位",
    })
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["session"]["reading_context"] == "在窗边试拍定位"
    after = client.get(f"/api/books/{book['id']}").json()
    assert [(r["start_position"], r["end_position"]) for r in after["read_ranges"]] == [(2, 2)]
    assert after["progress"]["current_anchor"] == items[2]["id"]


def test_photo_low_confidence_and_no_route_are_manual_safe(photo_book, monkeypatch):
    client, book, items, connection = photo_book
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: FakePhotoProvider(["完全无关的一句话"]))
    response = client.post(f"/api/books/{book['id']}/location-attempts", files={"file": ("page.jpg", jpeg_bytes(), "image/jpeg")})
    assert response.status_code == 201
    assert response.json()["attempt"]["state"] == "failed"
    assert client.get(f"/api/books/{book['id']}").json()["read_ranges"] == []

    assert client.put("/api/ai/task-routes", json={"routes": {}}).status_code == 200
    no_route = client.post(f"/api/books/{book['id']}/location-attempts", files={"file": ("page.jpg", jpeg_bytes(), "image/jpeg")})
    assert no_route.status_code == 400
    assert "手动定位" in no_route.json()["detail"]


def test_photo_rejects_unsafe_image(photo_book):
    client, book, _, _ = photo_book
    response = client.post(f"/api/books/{book['id']}/location-attempts", files={"file": ("bad.exe", b"not an image", "application/octet-stream")})
    assert response.status_code == 400


def test_photo_confirm_is_atomic_and_retry_idempotent(photo_book, monkeypatch):
    client, book, items, _ = photo_book
    client._transport.raise_server_exceptions = False
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: FakePhotoProvider([items[2]["text"]]))
    uploaded = client.post(f"/api/books/{book['id']}/location-attempts", files={"file": ("page.jpg", jpeg_bytes(), "image/jpeg")})
    attempt_id = uploaded.json()["attempt"]["id"]
    payload = {
        "chosen_anchor": items[2]["id"], "started_at": "2026-10-25T03:00:00+08:00",
        "ended_at": "2026-10-25T03:20:00+08:00", "timezone": "Asia/Shanghai",
        "session_type": "skip", "anchor_read_confirmed": True,
    }

    from app import reading

    def fail_core(*args, **kwargs):
        raise RuntimeError("模拟确认后落库失败")

    with monkeypatch.context() as patch:
        patch.setattr(reading, "create_session_core", fail_core)
        failed = client.post(f"/api/location-attempts/{attempt_id}/confirm", json=payload)
    assert failed.status_code == 500
    detail = client.get(f"/api/books/{book['id']}").json()
    assert detail["read_ranges"] == []
    assert detail["progress"]["current_anchor"] is None

    first = client.post(f"/api/location-attempts/{attempt_id}/confirm", json=payload)
    assert first.status_code == 200
    retry = client.post(f"/api/location-attempts/{attempt_id}/confirm", json=payload)
    assert retry.status_code == 200
    assert retry.json()["session"]["id"] == first.json()["session"]["id"]
    assert len(client.get(f"/api/books/{book['id']}/sessions").json()["items"]) == 1


def test_photo_accepts_cloud_signed_url_and_path(photo_book, monkeypatch):
    """前端直传云存储后，用签名 URL + 云端路径完成识别；服务端不再写本地照片文件。"""
    from app import photos as photos_module

    client, book, items, _ = photo_book
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: FakePhotoProvider([items[2]["text"]]))
    monkeypatch.setattr(photos_module, "fetch_signed_photo", lambda url: jpeg_bytes())
    response = client.post(
        f"/api/books/{book['id']}/location-attempts",
        data={"photo_url": "https://cos.example-signed-url.test/page.jpg?sign=xx", "cloud_path": "users/uid123/photos/ph-cloud-1.jpg"},
    )
    assert response.status_code == 201, response.text
    attempt = response.json()["attempt"]
    assert attempt["state"] == "candidates"
    assert attempt["cloud_path"] == "users/uid123/photos/ph-cloud-1.jpg"

    from app.db import connect
    settings = client.app.state.settings
    with connect(settings) as conn:
        row = conn.execute("SELECT local_path, cloud_path, retention_policy FROM photos WHERE id = ?", (attempt["photo_id"],)).fetchone()
    assert row["cloud_path"] == "users/uid123/photos/ph-cloud-1.jpg"
    assert row["local_path"] is None
    assert row["retention_policy"] == "cloud_private"

    bad = client.post(
        f"/api/books/{book['id']}/location-attempts",
        data={"photo_url": "https://cos.example-signed-url.test/page.jpg?sign=xx", "cloud_path": "../etc/passwd"},
    )
    assert bad.status_code == 400

    missing = client.post(f"/api/books/{book['id']}/location-attempts", data={})
    assert missing.status_code == 400

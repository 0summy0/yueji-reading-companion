from __future__ import annotations

import json
from typing import Any

import pytest

from app import ai
from conftest import import_txt


class FakeAskProvider:
    def __init__(self, citation: str | None, seen: list[str]):
        self.citation = citation
        self.seen = seen

    def extract_structured(self, prompt: str, schema_name: str) -> dict[str, Any]:
        self.seen.append(prompt)
        citations = [self.citation] if self.citation else []
        return {
            "answer": "根据你的原话，这段沉默更像一种自我保护。",
            "citations": citations,
            "uncertainty": "medium",
            "follow_up_question": None,
            "spoiler_risk": "low",
        }

    def close(self):
        return None


@pytest.fixture
def ask_setup(client):
    book = import_txt(client, "# 第一章 已知\n阿尔法段落。\n\n贝塔段落。\n\n# 第二章 未读\n未来章节秘密。", filename="ask.txt", title="证据问答书")
    items = client.get(f"/api/books/{book['id']}/passages").json()["items"]
    session = client.post(f"/api/books/{book['id']}/sessions", json={
        "started_at": "2026-10-25T03:00:00+08:00", "ended_at": "2026-10-25T03:10:00+08:00",
        "timezone": "Asia/Shanghai", "start_anchor": items[0]["id"], "current_anchor": items[1]["id"],
        "session_type": "sequential", "sequential_confirmed": True, "anchor_read_confirmed": True,
    })
    assert session.status_code == 201
    note = client.post("/api/notes", json={"book_id": book["id"], "passage_id": items[0]["id"], "text": "我认为沉默是人物保护自己的方式。"})
    assert note.status_code == 201
    connection = client.post("/api/ai/connections", json={"alias": "问答", "provider_type": "mock", "model_id": "mock-reader-v1", "base_url": "mock://local", "scenario": "success"}).json()
    assert client.put("/api/ai/task-routes", json={"routes": {"generate_text": connection["id"]}}).status_code == 200
    return client, book, items, note.json()


def test_ask_uses_only_read_evidence_and_real_citations(ask_setup, monkeypatch):
    client, book, items, note = ask_setup
    seen: list[str] = []
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: FakeAskProvider(f"nv:{note['current_version_id']}", seen))
    response = client.post("/api/ask", json={"question": "我怎样理解这里的沉默？", "book_id": book["id"], "mode": "book"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "沉默" in body["answer"]
    assert body["citations"] == [f"nv:{note['current_version_id']}"]
    assert body["evidence"][0]["kind"] == "note"
    prompt = seen[0]
    assert "我认为沉默是人物保护自己的方式。" in prompt
    assert "未来章节秘密" not in prompt
    assert items[2]["text"] not in prompt


def test_ask_rejects_model_citations_outside_evidence_pack(ask_setup, monkeypatch):
    client, book, _, _ = ask_setup
    monkeypatch.setattr(ai, "_provider_for_connection", lambda settings, row, truth=None: FakeAskProvider("pa:future-fake", []))
    response = client.post("/api/ask", json={"question": "未来发生了什么？", "book_id": book["id"], "mode": "book"})
    assert response.status_code == 502
    assert "不存在的证据" in response.json()["detail"]


def test_ask_without_evidence_does_not_guess(ask_setup, monkeypatch):
    client, _, _, _ = ask_setup
    empty_book = import_txt(client, "另一段。", filename="empty-evidence.txt", title="空证据书")
    response = client.post("/api/ask", json={"question": "这本书讲了什么？", "book_id": empty_book["id"], "mode": "book"})
    assert response.status_code == 200
    body = response.json()
    assert "没有找到可用证据" in body["answer"]
    assert body["citations"] == []


def test_ask_requires_verified_text_route(ask_setup, monkeypatch):
    client, book, _, _ = ask_setup
    assert client.put("/api/ai/task-routes", json={"routes": {}}).status_code == 200
    response = client.post("/api/ask", json={"question": "沉默意味着什么？", "book_id": book["id"], "mode": "book"})
    assert response.status_code == 400
    assert "文字检测" in response.json()["detail"]


def test_evidence_endpoint_returns_only_read_pack_without_ai(ask_setup):
    """免密钥云端问答的前置接口：只给已读证据包，不需要任何 AI 连接，不调用模型。"""
    client, book, items, note = ask_setup
    assert client.put("/api/ai/task-routes", json={"routes": {}}).status_code == 200
    response = client.post("/api/evidence", json={"question": "我怎样理解这里的沉默？", "book_id": book["id"], "mode": "book"})
    assert response.status_code == 200, response.text
    body = response.json()
    ids = {item["id"] for item in body["items"]}
    assert f"nv:{note['current_version_id']}" in ids
    assert f"pa:{items[0]['id']}" in ids and f"pa:{items[1]['id']}" in ids
    assert f"pa:{items[2]['id']}" not in ids  # 未读段落绝不进入证据包
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[f"nv:{note['current_version_id']}"]["speaker"] == "user"
    assert by_id[f"pa:{items[0]['id']}"]["speaker"] == "author"
    for item in body["items"]:
        assert len(item["text"]) <= 500

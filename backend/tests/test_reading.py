from __future__ import annotations

from datetime import datetime

from app.db import connect
from conftest import import_txt


def session_payload(items, end=2, start=0, kind="sequential", request_id="session-retry"):
    return {
        "started_at": "2026-10-25T10:00:00+08:00",
        "ended_at": "2026-10-25T03:00:00+00:00",
        "timezone": "Asia/Shanghai",
        "start_anchor": items[start]["id"],
        "current_anchor": items[end]["id"],
        "session_type": kind,
        "sequential_confirmed": kind == "sequential",
        "anchor_read_confirmed": True,
        "client_request_id": request_id,
    }


def setup_book(client):
    book = import_txt(client, "# 第一章 开始\n零段。\n\n一段。\n\n二段。\n\n三段。\n\n四段。\n\n五段。", filename="reading.txt")
    items = client.get(f"/api/books/{book['id']}/passages").json()["items"]
    return book, items


def test_utc_sessions_sequential_skip_and_reread_ranges(client):
    book, items = setup_book(client)
    response = client.post(f"/api/books/{book['id']}/sessions", json=session_payload(items))
    assert response.status_code == 201, response.text
    session = response.json()
    assert session["started_at"] == "2026-10-25T02:00:00+00:00"
    assert session["ended_at"] == "2026-10-25T03:00:00+00:00"
    assert datetime.fromisoformat(session["ended_at"]) - datetime.fromisoformat(session["started_at"]) == __import__("datetime").timedelta(hours=1)

    detail = client.get(f"/api/books/{book['id']}").json()
    assert [(r["start_position"], r["end_position"]) for r in detail["read_ranges"]] == [(0, 2)]

    skip = session_payload(items, end=5, start=2, kind="skip", request_id="skip-1")
    assert client.post(f"/api/books/{book['id']}/sessions", json=skip).status_code == 201
    detail = client.get(f"/api/books/{book['id']}").json()
    assert [(r["start_position"], r["end_position"]) for r in detail["read_ranges"]] == [(0, 2), (5, 5)]

    reread = session_payload(items, end=1, start=1, kind="reread", request_id="reread-1")
    assert client.post(f"/api/books/{book['id']}/sessions", json=reread).status_code == 201
    detail = client.get(f"/api/books/{book['id']}").json()
    assert [(r["start_position"], r["end_position"]) for r in detail["read_ranges"]] == [(0, 2), (5, 5)]
    assert len(client.get(f"/api/books/{book['id']}/sessions").json()["items"]) == 3


def test_sequential_requires_explicit_confirmation_and_start(client):
    book, items = setup_book(client)
    payload = session_payload(items)
    payload["sequential_confirmed"] = False
    response = client.post(f"/api/books/{book['id']}/sessions", json=payload)
    assert response.status_code == 201
    detail = client.get(f"/api/books/{book['id']}").json()
    assert [(r["start_position"], r["end_position"]) for r in detail["read_ranges"]] == [(2, 2)]

    payload["client_request_id"] = "missing-start"
    payload["sequential_confirmed"] = True
    payload["start_anchor"] = None
    assert client.post(f"/api/books/{book['id']}/sessions", json=payload).status_code == 422


def test_session_idempotency_is_scoped_and_validated(client):
    book, items = setup_book(client)
    payload = session_payload(items)
    first = client.post(f"/api/books/{book['id']}/sessions", json=payload)
    retry = client.post(f"/api/books/{book['id']}/sessions", json=payload)
    assert first.status_code == retry.status_code == 201
    assert first.json()["id"] == retry.json()["id"]
    changed = {**payload, "current_anchor": items[4]["id"]}
    conflict = client.post(f"/api/books/{book['id']}/sessions", json=changed)
    assert conflict.status_code == 409
    other = import_txt(client, "另一段。", filename="other.txt", title="另一本书")
    other_items = client.get(f"/api/books/{other['id']}/passages").json()["items"]
    other_payload = session_payload(other_items, end=0, start=0)
    assert client.post(f"/api/books/{other['id']}/sessions", json=other_payload).status_code == 409


def test_note_versions_evidence_stale_cards_and_idempotency(client):
    book, items = setup_book(client)
    payload = {"book_id": book["id"], "passage_id": items[1]["id"], "text": "我最初的疑问。", "client_request_id": "note-retry"}
    created = client.post("/api/notes", json=payload)
    assert created.status_code == 201, created.text
    note = created.json()
    assert note["source"] == "user" and note["author"] == "user"
    assert client.post("/api/notes", json=payload).json()["id"] == note["id"]
    assert client.post("/api/notes", json={**payload, "text": "不同内容"}).status_code == 409

    with connect(client.app.state.settings) as conn:
        conn.execute(
            """INSERT INTO knowledge_cards(id, user_id, type, speaker, epistemic_type, text, status, source_note_version, created_at, updated_at)
               VALUES ('card_test', 'u_local', 'reader_question', 'user', 'question', '候选问题', 'confirmed', ?, '2026-01-01', '2026-01-01')""",
            (note["current_version_id"],),
        )
    updated = client.patch(f"/api/notes/{note['id']}", json={"text": "我后来修订了原话。", "passage_id": items[1]["id"]})
    assert updated.status_code == 200, updated.text
    result = updated.json()
    assert result["version"] == 2 and result["stale_cards_marked"] == 1
    assert [v["text"] for v in result["versions"]] == ["我后来修订了原话。", "我最初的疑问。"]
    with connect(client.app.state.settings) as conn:
        assert conn.execute("SELECT status FROM knowledge_cards WHERE id = 'card_test'").fetchone()[0] == "stale"
        assert conn.execute("SELECT state FROM ai_jobs WHERE job_type = 'EXTRACT_NOTE'").fetchone()[0] == "queued"


def test_photo_entry_never_changes_progress(client):
    book, items = setup_book(client)
    before = client.get(f"/api/books/{book['id']}").json()
    status = client.get("/api/photo-path").json()
    after = client.get(f"/api/books/{book['id']}").json()
    assert status["automatic_location_available"] is False
    assert status["display_path"] == "manual"
    assert before["read_ranges"] == after["read_ranges"] == []


def test_end_before_start_returns_safe_422(client):
    book, items = setup_book(client)
    payload = session_payload(items, request_id="invalid-time")
    payload["ended_at"] = "2026-10-25T01:00:00+00:00"
    response = client.post(f"/api/books/{book['id']}/sessions", json=payload)
    assert response.status_code == 422
    assert "结束时间不能早于开始时间" in response.text
    assert "input" not in response.json()


def test_reading_context_optional_idempotent_and_returned(client):
    book, items = setup_book(client)
    payload = {**session_payload(items, request_id="with-context"), "reading_context": "在宿舍窗边，外面下着雨，桌上有一杯温茶。"}
    response = client.post(f"/api/books/{book['id']}/sessions", json=payload)
    assert response.status_code == 201
    assert response.json()["reading_context"] == "在宿舍窗边，外面下着雨，桌上有一杯温茶。"
    retry = client.post(f"/api/books/{book['id']}/sessions", json=payload)
    assert retry.json()["id"] == response.json()["id"]
    changed = {**payload, "reading_context": "换成了安静的图书馆"}
    assert client.post(f"/api/books/{book['id']}/sessions", json=changed).status_code == 409

    plain = session_payload(items, request_id="without-context")
    plain_response = client.post(f"/api/books/{book['id']}/sessions", json=plain)
    assert plain_response.status_code == 201
    assert plain_response.json()["reading_context"] is None

    overflow = {**payload, "reading_context": "长" * 1001}
    assert client.post(f"/api/books/{book['id']}/sessions", json=overflow).status_code == 422

    session_events = client.get("/api/timeline").json()["items"]
    assert any(item["kind"] == "session" and item["data"].get("reading_context") for item in session_events)


def test_002_migration_upgrades_existing_database(tmp_path, monkeypatch):
    from pathlib import Path

    from app.db import connect, migrate
    from app.config import get_settings

    data_dir = tmp_path / "upgrade-data"
    data_dir.mkdir()
    monkeypatch.setenv("YUEJI_DATA_DIR", str(data_dir))
    monkeypatch.setenv("YUEJI_DATABASE", "upgrade.sqlite3")
    settings = get_settings()
    migration_dir = Path(__file__).resolve().parents[1] / "migrations"
    with connect(settings) as conn:
        conn.executescript((migration_dir / "001_initial.sql").read_text(encoding="utf-8"))
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("INSERT INTO schema_migrations(version, name) VALUES (1, '001_initial.sql')")
        conn.commit()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(reading_sessions)")}
        assert "reading_context" not in columns
        migrate(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(reading_sessions)")}
        assert "reading_context" in columns
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = 2").fetchone()[0] == 1

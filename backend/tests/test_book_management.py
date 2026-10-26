from __future__ import annotations

import io

from PIL import Image

from app.db import connect
from conftest import import_txt


def session_payload(items):
    return {
        "started_at": "2026-10-25T10:00:00+08:00",
        "ended_at": "2026-10-25T03:00:00+00:00",
        "timezone": "Asia/Shanghai",
        "start_anchor": items[0]["id"],
        "current_anchor": items[1]["id"],
        "session_type": "sequential",
        "sequential_confirmed": True,
        "anchor_read_confirmed": True,
        "client_request_id": "book-management-session",
    }


def jpeg_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (240, 160), "#d9c9a3").save(output, format="JPEG")
    return output.getvalue()


def test_book_title_update_is_shelf_only_and_searchable(client):
    book = import_txt(client, title="导入时的书名")
    original_edition = book["edition_id"]
    original_hash = book["source_hash"]

    updated = client.patch(f"/api/books/{book['id']}/title", json={"title": "我想用的书名"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == "我想用的书名"
    assert updated.json()["edition_id"] == original_edition
    assert updated.json()["source_hash"] == original_hash
    assert client.get(f"/api/books/{book['id']}").json()["title"] == "我想用的书名"
    assert client.get("/api/books", params={"search": "我想用的书名"}).json()["items"][0]["id"] == book["id"]

    assert client.patch(f"/api/books/{book['id']}/title", json={"title": "   "}).status_code == 422
    assert client.patch(f"/api/books/{book['id']}/title", json={"title": "书" * 201}).status_code == 422


def test_delete_book_cascades_reading_notes_photo_and_local_file(client):
    book = import_txt(client, title="待删除的书")
    passages = client.get(f"/api/books/{book['id']}/passages").json()["items"]
    session = client.post(f"/api/books/{book['id']}/sessions", json=session_payload(passages))
    assert session.status_code == 201, session.text
    created_note = client.post(
        "/api/notes",
        json={
            "book_id": book["id"],
            "passage_id": passages[0]["id"],
            "session_id": session.json()["id"],
            "text": "删除前的原话",
            "client_request_id": "book-management-note",
        },
    )
    assert created_note.status_code == 201, created_note.text

    settings = client.app.state.settings
    local_path = settings.photo_dir / "u_local" / "to-delete.jpg"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(b"test-photo")
    with connect(settings) as conn:
        now = "2026-10-25T03:00:00+00:00"
        conn.execute(
            """INSERT INTO photos(id, user_id, session_id, local_path, cloud_path, captured_at, retention_policy, created_at, book_id, edition_id)
               VALUES ('photo-delete', 'u_local', ?, ?, NULL, ?, 'private_local', ?, ?, ?)""",
            (session.json()["id"], str(local_path), now, now, book["id"], book["edition_id"]),
        )
        conn.execute(
            """INSERT INTO location_attempts(id, user_id, photo_id, ocr_text, candidate_json, confidence, chosen_anchor, state, created_at, book_id)
               VALUES ('attempt-delete', 'u_local', 'photo-delete', '原文', '[]', NULL, NULL, 'failed', ?, ?)""",
            (now, book["id"]),
        )

    context_photo = client.post(
        f"/api/reading-sessions/{session.json()['id']}/context-photos",
        files={"file": ("reading-environment.jpg", jpeg_bytes(), "image/jpeg")},
    )
    assert context_photo.status_code == 201, context_photo.text
    session_after_photo = client.get(f"/api/books/{book['id']}/sessions").json()["items"][0]
    assert len(session_after_photo["context_photos"]) == 1
    assert client.get(session_after_photo["context_photos"][0]["url"]).status_code == 200

    deleted = client.delete(f"/api/books/{book['id']}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"deleted": True, "book_id": book["id"]}
    assert client.get(f"/api/books/{book['id']}").status_code == 404
    assert client.get(f"/api/books/{book['id']}/sessions").status_code == 404
    assert not local_path.exists()
    with connect(settings) as conn:
        for table in ("bookshelves", "editions", "passages", "reading_sessions", "read_ranges", "notes", "note_versions", "photos", "location_attempts", "reading_context_photos"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


def test_context_photo_requires_valid_image_and_does_not_enter_ocr_route(client):
    book = import_txt(client, title="环境记录书")
    passages = client.get(f"/api/books/{book['id']}/passages").json()["items"]
    session = client.post(f"/api/books/{book['id']}/sessions", json=session_payload(passages))
    assert session.status_code == 201
    session_id = session.json()["id"]
    bad = client.post(
        f"/api/reading-sessions/{session_id}/context-photos",
        files={"file": ("not-image.jpg", b"not an image", "image/jpeg")},
    )
    assert bad.status_code == 400
    good = client.post(
        f"/api/reading-sessions/{session_id}/context-photos",
        files={"file": ("environment.webp", jpeg_bytes(), "image/webp")},
    )
    assert good.status_code == 201
    assert client.get(f"/api/books/{book['id']}/sessions").json()["items"][0]["context_photos"]


def test_context_photo_can_live_in_cloud_storage_only(client, monkeypatch):
    """登录云端后情境照片走云存储：只存 cloud_path，不落本地文件，本地文件接口返回 404。"""
    from app import photos as photos_module

    book = import_txt(client, title="云端情境书")
    passages = client.get(f"/api/books/{book['id']}/passages").json()["items"]
    session = client.post(f"/api/books/{book['id']}/sessions", json=session_payload(passages))
    session_id = session.json()["id"]
    monkeypatch.setattr(photos_module, "fetch_signed_photo", lambda url: jpeg_bytes())
    created = client.post(
        f"/api/reading-sessions/{session_id}/context-photos",
        data={"photo_url": "https://cos.example.test/ctx.jpg?sign=1", "cloud_path": "users/uid9/photos/ctx-1.jpg"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["cloud_path"] == "users/uid9/photos/ctx-1.jpg"
    assert created.json()["url"] is None
    assert client.get(f"/api/reading-sessions/{session_id}/context-photos/{created.json()['id']}/file").status_code == 404
    assert client.get(f"/api/books/{book['id']}/sessions").json()["items"][0]["context_photos"][0]["cloud_path"] == "users/uid9/photos/ctx-1.jpg"

    bad = client.post(
        f"/api/reading-sessions/{session_id}/context-photos",
        data={"photo_url": "https://cos.example.test/ctx.jpg?sign=1", "cloud_path": "../escape.jpg"},
    )
    assert bad.status_code == 400
    missing = client.post(f"/api/reading-sessions/{session_id}/context-photos", data={})
    assert missing.status_code == 400


def test_delete_book_with_cloud_only_context_photo_succeeds(client, monkeypatch):
    """回归：情境照片只存云端（local_path 为空）时，删除整本书不应因本地清理抛 500。"""
    from app import photos as photos_module

    book = import_txt(client, title="云端情境待删书")
    passages = client.get(f"/api/books/{book['id']}/passages").json()["items"]
    session = client.post(f"/api/books/{book['id']}/sessions", json=session_payload(passages))
    session_id = session.json()["id"]
    monkeypatch.setattr(photos_module, "fetch_signed_photo", lambda url: jpeg_bytes())
    created = client.post(
        f"/api/reading-sessions/{session_id}/context-photos",
        data={"photo_url": "https://cos.example.test/ctx.jpg?sign=1", "cloud_path": "users/uid9/photos/ctx-2.jpg"},
    )
    assert created.status_code == 201
    deleted = client.delete(f"/api/books/{book['id']}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] is True
    with connect(client.app.state.settings) as conn:
        assert conn.execute("SELECT COUNT(*) FROM reading_context_photos").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM reading_sessions").fetchone()[0] == 0


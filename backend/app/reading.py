from __future__ import annotations

import hashlib
from datetime import timezone
from pathlib import Path
import re
import sqlite3
from typing import Any

from fastapi import HTTPException

from .config import Settings
from .library import LOCAL_USER, get_book, new_id, utcnow
from .schemas import NoteCreate, NoteUpdate, SessionCreate


def _passage(conn: sqlite3.Connection, passage_id: str, edition_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM passages WHERE id = ? AND edition_id = ?", (passage_id, edition_id)).fetchone()
    if not row:
        raise HTTPException(400, "段落锚点不属于当前电子版本")
    return row


def _add_read_range(
    conn: sqlite3.Connection,
    edition_id: str,
    start: sqlite3.Row,
    end: sqlite3.Row,
    method: str,
    session_id: str,
) -> None:
    if end["position"] < start["position"]:
        raise HTTPException(400, "已读范围的结束位置不能早于开始位置")
    start_position, end_position = start["position"], end["position"]
    nearby = conn.execute(
        """SELECT * FROM read_ranges
           WHERE edition_id = ? AND start_position <= ? AND end_position >= ?""",
        (edition_id, end_position + 1, start_position - 1),
    ).fetchall()
    if nearby:
        start_position = min([start_position, *(row["start_position"] for row in nearby)])
        end_position = max([end_position, *(row["end_position"] for row in nearby)])
        conn.executemany("DELETE FROM read_ranges WHERE id = ?", [(row["id"],) for row in nearby])
    anchors = conn.execute(
        "SELECT (SELECT id FROM passages WHERE edition_id = ? AND position = ?) AS start_id, (SELECT id FROM passages WHERE edition_id = ? AND position = ?) AS end_id",
        (edition_id, start_position, edition_id, end_position),
    ).fetchone()
    if not anchors["start_id"] or not anchors["end_id"]:
        raise HTTPException(400, "已读范围锚点无效")
    conn.execute(
        """INSERT INTO read_ranges(id, user_id, edition_id, start_anchor, end_anchor, start_position, end_position, confirmation_method, source_session_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (new_id("rr"), LOCAL_USER, edition_id, anchors["start_id"], anchors["end_id"], start_position, end_position, method, session_id, utcnow()),
    )


def create_session_core(
    conn: sqlite3.Connection,
    book_id: str,
    payload: SessionCreate,
    source_location_attempt_id: str | None = None,
) -> dict[str, Any]:
    book = get_book(conn, book_id)
    request_hash = hashlib.sha256(f"session:{book_id}:{payload.model_dump_json()}".encode("utf-8")).hexdigest()
    if payload.client_request_id:
        existing = conn.execute(
            "SELECT id, edition_id, request_hash FROM reading_sessions WHERE client_request_id = ?", (payload.client_request_id,)
        ).fetchone()
        if existing:
            if existing["edition_id"] != book["edition_id"] or existing["request_hash"] != request_hash:
                raise HTTPException(409, "相同 client_request_id 已用于其他书籍或不同会话内容")
            return get_session(conn, existing["id"])
    end = _passage(conn, payload.current_anchor, book["edition_id"])
    start = _passage(conn, payload.start_anchor, book["edition_id"]) if payload.start_anchor else None
    session_id = new_id("rs")
    now = utcnow()
    started_utc = payload.started_at.astimezone(timezone.utc).isoformat()
    ended_utc = payload.ended_at.astimezone(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO reading_sessions(id, user_id, edition_id, started_at, ended_at, timezone, start_anchor, current_anchor,
                                        session_type, sequential_confirmed, anchor_read_confirmed, reading_context, client_request_id, request_hash,
                                        source_location_attempt_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, LOCAL_USER, book["edition_id"], started_utc, ended_utc, payload.timezone,
         payload.start_anchor, payload.current_anchor, payload.session_type, int(payload.sequential_confirmed),
         int(payload.anchor_read_confirmed), (payload.reading_context or "").strip() or None, payload.client_request_id,
         request_hash, source_location_attempt_id, now),
    )
    if payload.sequential_confirmed and payload.session_type == "sequential":
        _add_read_range(conn, book["edition_id"], start, end, "manual_sequential", session_id)
    elif payload.anchor_read_confirmed:
        _add_read_range(conn, book["edition_id"], end, end, "manual_point", session_id)
    conn.execute(
        "UPDATE bookshelves SET current_anchor = ?, updated_at = ? WHERE id = ?",
        (payload.current_anchor, now, book_id),
    )
    return get_session(conn, session_id)


def create_session(conn: sqlite3.Connection, book_id: str, payload: SessionCreate) -> dict[str, Any]:
    with conn:
        return create_session_core(conn, book_id, payload)


def list_context_photos(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, session_id, captured_at, created_at, local_path, cloud_path FROM reading_context_photos WHERE session_id = ? ORDER BY created_at",
        (session_id,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "session_id": row["session_id"],
            "captured_at": row["captured_at"],
            "created_at": row["created_at"],
            "cloud_path": row["cloud_path"],
            "url": f"/api/reading-sessions/{session_id}/context-photos/{row['id']}/file" if row["local_path"] else None,
        }
        for row in rows
    ]


def attach_context_photo(
    conn: sqlite3.Connection,
    settings: Settings,
    session_id: str,
    data: bytes,
    cloud_path: str | None = None,
) -> dict[str, Any]:
    session = conn.execute(
        """SELECT s.id, b.id AS book_id
           FROM reading_sessions s JOIN bookshelves b ON b.edition_id = s.edition_id
          WHERE s.id = ? AND s.user_id = ?""",
        (session_id, LOCAL_USER),
    ).fetchone()
    if not session:
        raise HTTPException(404, "阅读会话不存在")
    photo_id = new_id("ctx")
    now = utcnow()
    local_path: str | None = None
    if cloud_path:
        if not re.fullmatch(r"users/[A-Za-z0-9._/-]+\.[A-Za-z0-9]+", cloud_path) or ".." in cloud_path:
            raise HTTPException(400, "云端照片路径不合法")
    else:
        path = settings.photo_dir / LOCAL_USER / "context" / f"{photo_id}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        local_path = str(path)
    try:
        with conn:
            conn.execute(
                """INSERT INTO reading_context_photos(id, user_id, session_id, book_id, local_path, cloud_path, captured_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (photo_id, LOCAL_USER, session_id, session["book_id"], local_path, cloud_path, now, now),
            )
    except Exception:
        if local_path:
            Path(local_path).unlink(missing_ok=True)
        raise
    return list_context_photos(conn, session_id)[-1]


def context_photo_file(conn: sqlite3.Connection, session_id: str, photo_id: str) -> Path:
    row = conn.execute(
        "SELECT local_path FROM reading_context_photos WHERE id = ? AND session_id = ? AND user_id = ?",
        (photo_id, session_id, LOCAL_USER),
    ).fetchone()
    if not row:
        raise HTTPException(404, "阅读情境照片不存在")
    if not row["local_path"]:
        raise HTTPException(404, "照片保存在云端，请使用云端签名链接查看")
    path = Path(row["local_path"])
    if not path.is_file():
        raise HTTPException(404, "阅读情境照片文件不存在")
    return path


def get_session(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    row = conn.execute(
        """SELECT s.*, p.chapter_title, p.position, substr(p.text, 1, 160) AS excerpt
           FROM reading_sessions s JOIN passages p ON p.id = s.current_anchor WHERE s.id = ?""",
        (session_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "阅读会话不存在")
    item = dict(row)
    item["source"] = "user"
    item["context_photos"] = list_context_photos(conn, session_id)
    return item


def _note_dict(conn: sqlite3.Connection, note_id: str, include_history: bool = True) -> dict[str, Any]:
    note = conn.execute(
        """SELECT n.*, COALESCE(b.title_override, w.title) AS book_title, b.id AS book_id
           FROM notes n JOIN editions e ON e.id = n.edition_id
           JOIN works w ON w.id = e.work_id JOIN bookshelves b ON b.edition_id = e.id
          WHERE n.id = ?""",
        (note_id,),
    ).fetchone()
    if not note:
        raise HTTPException(404, "笔记不存在")
    versions = conn.execute("SELECT * FROM note_versions WHERE note_id = ? ORDER BY version DESC", (note_id,)).fetchall()
    latest = versions[0]
    evidence = conn.execute(
        """SELECT p.id AS passage_id, p.chapter_title, p.position, p.start_char, p.end_char, substr(p.text, 1, 180) AS excerpt
           FROM evidence_links el JOIN passages p ON p.id = el.passage_id
          WHERE el.note_version_id = ? LIMIT 1""",
        (latest["id"],),
    ).fetchone()
    result = dict(note)
    result.update({"text": latest["text"], "version": latest["version"], "current_version_id": latest["id"],
                   "source": "user", "evidence": dict(evidence) if evidence else None})
    if include_history:
        result["versions"] = [dict(row) for row in versions]
    return result


def create_note(conn: sqlite3.Connection, payload: NoteCreate) -> dict[str, Any]:
    book = get_book(conn, payload.book_id)
    request_hash = hashlib.sha256(f"note:{payload.model_dump_json()}".encode("utf-8")).hexdigest()
    if payload.client_request_id:
        existing = conn.execute("SELECT id, edition_id, request_hash FROM notes WHERE client_request_id = ?", (payload.client_request_id,)).fetchone()
        if existing:
            if existing["edition_id"] != book["edition_id"] or existing["request_hash"] != request_hash:
                raise HTTPException(409, "相同 client_request_id 已用于其他书籍或不同笔记内容")
            return _note_dict(conn, existing["id"])
    if payload.session_id:
        session = conn.execute("SELECT edition_id FROM reading_sessions WHERE id = ?", (payload.session_id,)).fetchone()
        if not session or session["edition_id"] != book["edition_id"]:
            raise HTTPException(400, "笔记关联的阅读会话不属于本书")
    if payload.passage_id:
        _passage(conn, payload.passage_id, book["edition_id"])
    note_id = new_id("nt")
    version_id = new_id("nv")
    now = utcnow()
    with conn:
        conn.execute(
            "INSERT INTO notes(id, user_id, edition_id, session_id, author, client_request_id, request_hash, created_at, updated_at) VALUES (?, ?, ?, ?, 'user', ?, ?, ?, ?)",
            (note_id, LOCAL_USER, book["edition_id"], payload.session_id, payload.client_request_id, request_hash, now, now),
        )
        conn.execute("INSERT INTO note_versions(id, note_id, version, text, created_at) VALUES (?, ?, 1, ?, ?)", (version_id, note_id, payload.text, now))
        if payload.passage_id:
            conn.execute(
                "INSERT INTO evidence_links(id, user_id, note_version_id, passage_id, relation, created_at) VALUES (?, ?, ?, ?, 'anchor', ?)",
                (new_id("ev"), LOCAL_USER, version_id, payload.passage_id, now),
            )
    return _note_dict(conn, note_id)


def update_note(conn: sqlite3.Connection, note_id: str, payload: NoteUpdate) -> dict[str, Any]:
    old = _note_dict(conn, note_id, include_history=False)
    passage_id = payload.passage_id or (old["evidence"] or {}).get("passage_id")
    if passage_id:
        _passage(conn, passage_id, old["edition_id"])
    new_version = old["version"] + 1
    version_id = new_id("nv")
    now = utcnow()
    with conn:
        conn.execute("INSERT INTO note_versions(id, note_id, version, text, created_at) VALUES (?, ?, ?, ?, ?)", (version_id, note_id, new_version, payload.text, now))
        conn.execute("UPDATE notes SET updated_at = ? WHERE id = ?", (now, note_id))
        if passage_id:
            conn.execute(
                "INSERT INTO evidence_links(id, user_id, note_version_id, passage_id, relation, created_at) VALUES (?, ?, ?, ?, 'anchor', ?)",
                (new_id("ev"), LOCAL_USER, version_id, passage_id, now),
            )
        cursor = conn.execute(
            """UPDATE knowledge_cards SET status = 'stale', updated_at = ?
               WHERE source_note_version IN (SELECT id FROM note_versions WHERE note_id = ?) AND status != 'retracted'""",
            (now, note_id),
        )
        input_hash = hashlib.sha256(version_id.encode("utf-8")).hexdigest()
        conn.execute(
            """INSERT OR IGNORE INTO ai_jobs(id, user_id, job_type, input_hash, state, attempts, last_error, created_at, updated_at)
               VALUES (?, ?, 'EXTRACT_NOTE', ?, 'queued', 0, '阶段3待处理；原话已持久保存', ?, ?)""",
            (new_id("job"), LOCAL_USER, input_hash, now, now),
        )
    result = _note_dict(conn, note_id)
    result["stale_cards_marked"] = cursor.rowcount
    result["derivation_state"] = "pending_stage3"
    return result


def list_notes(conn: sqlite3.Connection, book_id: str) -> list[dict[str, Any]]:
    book = get_book(conn, book_id)
    ids = conn.execute("SELECT id FROM notes WHERE edition_id = ? ORDER BY updated_at DESC", (book["edition_id"],)).fetchall()
    return [_note_dict(conn, row["id"]) for row in ids]


def list_sessions(conn: sqlite3.Connection, book_id: str) -> list[dict[str, Any]]:
    book = get_book(conn, book_id)
    rows = conn.execute("SELECT id FROM reading_sessions WHERE edition_id = ? ORDER BY ended_at DESC", (book["edition_id"],))
    return [get_session(conn, row["id"]) for row in rows]


def timeline(conn: sqlite3.Connection, book_id: str | None = None) -> list[dict[str, Any]]:
    book_ids = [book_id] if book_id else [row["id"] for row in conn.execute("SELECT id FROM bookshelves WHERE user_id = ?", (LOCAL_USER,))]
    events: list[dict[str, Any]] = []
    for current_book in book_ids:
        for session in list_sessions(conn, current_book):
            events.append({"kind": "session", "occurred_at": session["ended_at"], "book_id": current_book,
                           "book_title": get_book(conn, current_book)["title"], "source": "user", "data": session})
        for note in list_notes(conn, current_book):
            events.append({"kind": "note", "occurred_at": note["updated_at"], "book_id": current_book,
                           "book_title": note["book_title"], "source": "user", "data": note})
    return sorted(events, key=lambda item: item["occurred_at"], reverse=True)

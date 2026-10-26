from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from .importer import ParsedBook, parse_book

LOCAL_USER = "u_local"
PARSER_VERSION = "safe-spine-v1"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


DEFAULT_STYLES = [
    {"color": "#59634b", "accent": "#d9c9a3", "material": "cloth", "title_layout": "vertical", "height": 226, "width": 62},
    {"color": "#7a493d", "accent": "#ead9b8", "material": "leather", "title_layout": "vertical", "height": 242, "width": 54},
    {"color": "#315c5b", "accent": "#e6d6ae", "material": "linen", "title_layout": "vertical", "height": 208, "width": 72},
    {"color": "#b09a72", "accent": "#493d31", "material": "paper", "title_layout": "horizontal", "height": 218, "width": 82},
    {"color": "#4b5663", "accent": "#d7c5a0", "material": "cloth", "title_layout": "vertical", "height": 252, "width": 58},
]


def style_for(source_hash: str, title: str) -> dict[str, Any]:
    base = dict(DEFAULT_STYLES[int(source_hash[:2], 16) % len(DEFAULT_STYLES)])
    base["width"] = max(44, min(96, base["width"] + len(title) % 9 - 4))
    return base


def _book_query() -> str:
    return """
        SELECT b.id, b.edition_id, b.spine_style_json, b.sort_order, b.status,
               b.current_anchor, b.created_at, b.updated_at,
               COALESCE(b.title_override, w.title) AS title, w.author, w.language, e.format, e.source_hash,
               e.source_name, e.parsed_at, e.parser_version, e.content_sha256,
               p.chapter_title AS current_chapter, p.position AS current_position,
               substr(p.text, 1, 90) AS current_excerpt,
               (SELECT COUNT(*) FROM passages ap WHERE ap.edition_id = b.edition_id) AS passage_count,
               (SELECT COALESCE(SUM(r.end_position - r.start_position + 1), 0)
                  FROM read_ranges r WHERE r.edition_id = b.edition_id) AS confirmed_passages,
               (SELECT MAX(s.ended_at) FROM reading_sessions s WHERE s.edition_id = b.edition_id) AS last_read_at
          FROM bookshelves b
          JOIN editions e ON e.id = b.edition_id
          JOIN works w ON w.id = e.work_id
          LEFT JOIN passages p ON p.id = b.current_anchor
         WHERE b.user_id = 'u_local'
    """


def serialize_book(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["spine_style"] = json.loads(item.pop("spine_style_json"))
    item["progress"] = {
        "current_anchor": item.get("current_anchor"),
        "current_chapter": item.get("current_chapter"),
        "current_position": item.get("current_position"),
        "current_excerpt": item.get("current_excerpt"),
        "confirmed_passages": item.get("confirmed_passages", 0),
        "passage_count": item.get("passage_count", 0),
        "last_read_at": item.get("last_read_at"),
    }
    return item


def get_book(conn: sqlite3.Connection, book_id: str) -> dict[str, Any]:
    row = conn.execute(_book_query() + " AND b.id = ?", (book_id,)).fetchone()
    if not row:
        raise HTTPException(404, "书架上没有这本书")
    return serialize_book(row)


def list_books(conn: sqlite3.Connection, search: str = "", sort: str = "imported") -> list[dict[str, Any]]:
    order = {
        "imported": "b.sort_order ASC, b.created_at ASC",
        "title": "COALESCE(b.title_override, w.title) COLLATE NOCASE ASC",
        "-title": "COALESCE(b.title_override, w.title) COLLATE NOCASE DESC",
        "author": "w.author COLLATE NOCASE ASC, COALESCE(b.title_override, w.title) ASC",
        "recent": "last_read_at IS NULL, last_read_at DESC, b.updated_at DESC",
    }.get(sort)
    if not order:
        raise HTTPException(400, "不支持的排序方式")
    sql = _book_query()
    params: list[Any] = []
    if search.strip():
        sql += " AND (COALESCE(b.title_override, w.title) LIKE ? OR w.author LIKE ?)"
        needle = f"%{search.strip()}%"
        params.extend([needle, needle])
    sql += f" ORDER BY {order}"
    return [serialize_book(row) for row in conn.execute(sql, params)]


def import_book(
    conn: sqlite3.Connection,
    data: bytes,
    filename: str,
    title_override: str | None = None,
    author_override: str | None = None,
    format_override: str | None = None,
    style_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed: ParsedBook = parse_book(data, filename)
    source_hash = hashlib.sha256(data).hexdigest()
    existing = conn.execute(
        "SELECT b.id FROM editions e JOIN bookshelves b ON b.edition_id = e.id WHERE e.user_id = ? AND e.source_hash = ?",
        (LOCAL_USER, source_hash),
    ).fetchone()
    if existing:
        result = get_book(conn, existing[0])
        result["duplicate"] = True
        return result

    now = utcnow()
    title = (title_override or parsed.title).strip()[:200] or "未命名图书"
    author = (author_override or parsed.author).strip()[:120] or "未知作者"
    edition_id = f"ed_{source_hash[:32]}"
    content_sha256 = hashlib.sha256("\n".join(p.text for p in parsed.passages).encode("utf-8")).hexdigest()
    with conn:
        work = conn.execute(
            "SELECT id FROM works WHERE user_id = ? AND title = ? AND author = ?",
            (LOCAL_USER, title, author),
        ).fetchone()
        work_id = work[0] if work else new_id("wk")
        if not work:
            conn.execute(
                "INSERT INTO works(id, user_id, title, author, language, created_at) VALUES (?, ?, ?, ?, 'zh-CN', ?)",
                (work_id, LOCAL_USER, title, author, now),
            )
        conn.execute(
            """INSERT INTO editions(id, user_id, work_id, format, source_hash, source_name, parsed_at, parser_version, content_sha256)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (edition_id, LOCAL_USER, work_id, format_override or parsed.format, source_hash, Path(filename).name, now, PARSER_VERSION, content_sha256),
        )
        cursor = 0
        chapter_order = 0
        passage_order = 0
        previous_chapter: str | None = None
        for position, passage in enumerate(parsed.passages):
            if passage.chapter_title != previous_chapter:
                chapter_order += 1
                passage_order = 0
                previous_chapter = passage.chapter_title
            passage_order += 1
            start = cursor
            end = start + len(passage.text)
            cursor = end + 2
            passage_id = "pa_" + hashlib.sha256(f"{edition_id}:{position}:{start}:{passage.text}".encode("utf-8")).hexdigest()[:28]
            text_hash = hashlib.sha256(passage.text.encode("utf-8")).hexdigest()
            conn.execute(
                """INSERT INTO passages(id, edition_id, chapter_order, chapter_title, passage_order, position, start_char, end_char, text, hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (passage_id, edition_id, chapter_order, passage.chapter_title, passage_order, position, start, end, passage.text, text_hash),
            )
        sort_order = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM bookshelves WHERE user_id = ?", (LOCAL_USER,)).fetchone()[0]
        book_id = new_id("bs")
        style = style_override or style_for(source_hash, title)
        conn.execute(
            """INSERT INTO bookshelves(id, user_id, edition_id, spine_style_json, sort_order, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'reading', ?, ?)""",
            (book_id, LOCAL_USER, edition_id, json.dumps(style, ensure_ascii=False), sort_order, now, now),
        )
    result = get_book(conn, book_id)
    result["duplicate"] = False
    return result


def list_passages(conn: sqlite3.Connection, book_id: str) -> list[dict[str, Any]]:
    book = get_book(conn, book_id)
    rows = conn.execute(
        """SELECT id, chapter_order, chapter_title, passage_order, position, start_char, end_char, hash, text
           FROM passages WHERE edition_id = ? ORDER BY position""",
        (book["edition_id"],),
    )
    return [dict(row) for row in rows]


def book_detail(conn: sqlite3.Connection, book_id: str) -> dict[str, Any]:
    book = get_book(conn, book_id)
    chapters = conn.execute(
        """SELECT chapter_order, chapter_title, COUNT(*) AS passage_count, MIN(position) AS first_position
           FROM passages WHERE edition_id = ? GROUP BY chapter_order, chapter_title ORDER BY chapter_order""",
        (book["edition_id"],),
    )
    ranges = conn.execute(
        """SELECT id, start_anchor, end_anchor, start_position, end_position, confirmation_method, created_at
           FROM read_ranges WHERE edition_id = ? ORDER BY start_position""",
        (book["edition_id"],),
    )
    book["chapters"] = [dict(row) for row in chapters]
    book["read_ranges"] = [dict(row) for row in ranges]
    return book


def update_book_title(conn: sqlite3.Connection, book_id: str, title: str) -> dict[str, Any]:
    """Update only the shelf display title; imported work metadata and content stay unchanged."""
    book = get_book(conn, book_id)
    normalized = title.strip()
    if not normalized or len(normalized) > 200:
        raise HTTPException(400, "书名不能为空且不能超过 200 个字符")
    now = utcnow()
    with conn:
        conn.execute(
            "UPDATE bookshelves SET title_override = ?, updated_at = ? WHERE id = ?",
            (normalized, now, book_id),
        )
    return get_book(conn, book_id)


def delete_book(conn: sqlite3.Connection, settings: Any, book_id: str) -> dict[str, Any]:
    """Delete a shelf book and its dependent reading records in one transaction."""
    book = get_book(conn, book_id)
    edition_id = book["edition_id"]
    work_id = conn.execute("SELECT work_id FROM editions WHERE id = ?", (edition_id,)).fetchone()[0]
    local_paths = [
        row[0]
        for row in conn.execute(
            "SELECT local_path FROM photos WHERE book_id = ? AND local_path IS NOT NULL", (book_id,)
        ).fetchall()
    ]
    local_paths.extend(
        row[0]
        for row in conn.execute(
            "SELECT local_path FROM reading_context_photos WHERE book_id = ? AND local_path IS NOT NULL", (book_id,)
        ).fetchall()
    )
    with conn:
        # These tables contain RESTRICT references to passages/sessions, so remove
        # them explicitly before the edition cascade runs.
        conn.execute(
            "DELETE FROM evidence_links WHERE passage_id IN (SELECT id FROM passages WHERE edition_id = ?)",
            (edition_id,),
        )
        conn.execute(
            "DELETE FROM evidence_links WHERE note_version_id IN (SELECT nv.id FROM note_versions nv JOIN notes n ON n.id = nv.note_id WHERE n.edition_id = ?)",
            (edition_id,),
        )
        conn.execute("DELETE FROM read_ranges WHERE edition_id = ?", (edition_id,))
        conn.execute("DELETE FROM reading_sessions WHERE edition_id = ?", (edition_id,))
        conn.execute("DELETE FROM photos WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM reading_context_photos WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM notes WHERE edition_id = ?", (edition_id,))
        conn.execute(
            "DELETE FROM socratic_reports WHERE session_id IN (SELECT id FROM socratic_sessions WHERE book_id = ?)",
            (book_id,),
        )
        conn.execute(
            "DELETE FROM socratic_turns WHERE session_id IN (SELECT id FROM socratic_sessions WHERE book_id = ?)",
            (book_id,),
        )
        conn.execute("DELETE FROM socratic_sessions WHERE book_id = ?", (book_id,))
        conn.execute("DELETE FROM bookshelves WHERE id = ?", (book_id,))
        conn.execute("DELETE FROM editions WHERE id = ?", (edition_id,))
        conn.execute(
            "DELETE FROM works WHERE id = ? AND NOT EXISTS (SELECT 1 FROM editions WHERE work_id = ?)",
            (work_id, work_id),
        )
    photo_root = settings.photo_dir.resolve()
    for raw_path in local_paths:
        if not raw_path:
            continue
        try:
            candidate = Path(raw_path).resolve()
            candidate.relative_to(photo_root)
            candidate.unlink(missing_ok=True)
        except OSError:
            # Database deletion is authoritative; an orphaned local file is safe
            # to clean up later and must not turn a successful delete into a 500.
            continue
        except ValueError:
            # Never unlink a path outside the configured photo root, even if a
            # legacy database row contains an unexpected value.
            continue
    return {"deleted": True, "book_id": book_id}


def seed_samples(conn: sqlite3.Connection, sample_dir: Path) -> None:
    samples = [
        ("窗外有座小山.txt", "窗外有座小山", "林拾青", {"color": "#59634b", "accent": "#e4d3aa", "material": "cloth", "title_layout": "vertical", "height": 232, "width": 60}),
        ("夜航修理铺.txt", "夜航修理铺", "周见微", {"color": "#365b60", "accent": "#dfc78f", "material": "leather", "title_layout": "vertical", "height": 248, "width": 52}),
        ("苔痕笔记.txt", "苔痕笔记", "沈知闲", {"color": "#a58b64", "accent": "#413a2f", "material": "paper", "title_layout": "horizontal", "height": 210, "width": 76}),
    ]
    for filename, title, author, style in samples:
        path = sample_dir / filename
        if path.exists():
            import_book(conn, path.read_bytes(), filename, title, author, "sample", style)

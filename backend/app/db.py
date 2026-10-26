from __future__ import annotations

from collections.abc import Generator
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any

from fastapi import HTTPException, Request

from .config import Settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def connect_path(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def connect(settings: Settings) -> sqlite3.Connection:
    return connect_path(settings.database_path)


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(path.name[:3])
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        conn.executescript(sql)
        conn.execute("INSERT INTO schema_migrations(version, name) VALUES (?, ?)", (version, path.name))
        conn.commit()


# sqlite3.Connection 的 with 只管理事务、不关闭连接；进程内缓存避免每个请求都重复扫描迁移目录。
_migrated_paths: set[str] = set()
_migrate_lock = threading.Lock()


def initialize_path(database_path: Path) -> None:
    key = str(database_path)
    if key in _migrated_paths:
        return
    with _migrate_lock:
        if key in _migrated_paths:
            return
        with closing(connect_path(database_path)) as conn:
            migrate(conn)
        _migrated_paths.add(key)


def initialize(settings: Settings) -> None:
    initialize_path(settings.database_path)


def user_database_path(settings: Settings, user_id: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", user_id):
        raise HTTPException(400, "用户标识无效")
    return settings.user_databases_dir / f"{user_id}.sqlite3"


def get_db(request: Request) -> Generator[sqlite3.Connection, Any, None]:
    settings: Settings = request.app.state.settings
    if settings.auth_required:
        from . import auth

        user = auth.current_user(request)
        if not user:
            raise HTTPException(401, "请先登录")
        database_path = user_database_path(settings, user["id"])
        initialize_path(database_path)
    else:
        database_path = settings.database_path
        initialize_path(database_path)
    conn = connect_path(database_path)
    try:
        yield conn
    finally:
        conn.close()

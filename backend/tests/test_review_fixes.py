from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth, db, library
from app.auth import create_invite, rate_limiter, register_user
from app.auth_cli import migrate_local_database
from app.config import get_settings


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()
from app.main import app


def test_from_local_migration_uses_sqlite_backup_api(tmp_path, monkeypatch):
    import app.auth_cli as auth_cli

    monkeypatch.setattr(auth_cli, "new_id", lambda prefix: "usr_fixed")
    data_dir = tmp_path / "migrate"
    monkeypatch.setenv("YUEJI_DATA_DIR", str(data_dir))
    monkeypatch.setenv("YUEJI_SEED_SAMPLES", "false")
    monkeypatch.setenv("YUEJI_AUTH_REQUIRED", "false")
    settings = get_settings()
    db.initialize_path(settings.database_path)
    with db.connect(settings) as conn:
        library.import_book(conn, "窗外有座小山。\n\n我把沉默夹进书页。".encode("utf-8"), "旧书.txt", "旧书", "旧作者")

    result = migrate_local_database(settings, "旧主", "OwnerPassword-2026")
    target = result["database_path"]
    assert target.exists() and target.name.endswith(".sqlite3")
    with db.connect_path(target) as conn:
        books = conn.execute("SELECT w.title, w.author FROM works w").fetchall()
    assert [(row["title"], row["author"]) for row in books] == [("旧书", "旧作者")]

    with pytest.raises(SystemExit, match="拒绝覆盖"):
        migrate_local_database(settings, "旧主二", "OwnerPassword-2026")


def test_failed_registration_does_not_consume_invite_and_concurrency_is_atomic(tmp_path, monkeypatch):
    monkeypatch.setenv("YUEJI_DATA_DIR", str(tmp_path / "invites"))
    monkeypatch.setenv("YUEJI_SEED_SAMPLES", "false")
    settings = get_settings()
    code = create_invite(settings, "单次邀请", uses=1)
    with pytest.raises(HTTPException):
        register_user(settings, code, "坏密码用户", "short")
    with auth.auth_connect(settings) as conn:
        assert conn.execute("SELECT uses FROM auth_invites").fetchone()[0] == 0

    account = register_user(settings, code, "合法用户", "ValidPassword-2026")
    assert account["username"] == "合法用户"
    with auth.auth_connect(settings) as conn:
        assert conn.execute("SELECT uses FROM auth_invites").fetchone()[0] == 1
    with pytest.raises(HTTPException):
        register_user(settings, code, "超员用户", "ValidPassword-2026")

    race_code = create_invite(settings, "并发单次", uses=1)
    outcomes = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(register_user, settings, race_code, f"并发{i}", "ValidPassword-2026") for i in range(2)]
        for future in futures:
            try:
                outcomes.append(("ok", future.result()["username"]))
            except HTTPException as error:
                outcomes.append(("error", error.status_code))
    assert sorted(item[0] for item in outcomes) == ["error", "ok"]
    with auth.auth_connect(settings) as conn:
        assert conn.execute("SELECT uses FROM auth_invites WHERE label = '并发单次'").fetchone()[0] == 1


@pytest.fixture
def review_client(tmp_path, monkeypatch):
    monkeypatch.setenv("YUEJI_DATA_DIR", str(tmp_path / "review"))
    monkeypatch.setenv("YUEJI_SEED_SAMPLES", "false")
    monkeypatch.setenv("YUEJI_AUTH_REQUIRED", "true")
    monkeypatch.setenv("YUEJI_TEST_INVITE_CODE", "REVIEW-INVITE")
    with TestClient(app) as client:
        yield client


def test_forged_xff_cannot_bypass_rate_limit(review_client):
    rate_limiter._hits.clear()
    statuses = []
    for index in range(9):
        response = review_client.post("/api/auth/register", json={
            "invite_code": "REVIEW-INVITE", "username": f"限流{index}", "password": "ValidPassword-2026",
        })
        statuses.append(response.status_code)
    assert statuses[:8] == [201] * 8
    assert statuses[8] == 429
    forged = review_client.post("/api/auth/register", json={
        "invite_code": "REVIEW-INVITE", "username": "伪造IP", "password": "ValidPassword-2026",
    }, headers={"X-Forwarded-For": "203.0.113.99"})
    assert forged.status_code == 429


def test_malformed_cookies_are_invalid_not_500(review_client):
    assert auth._safe_token_hash("中文会话") is None
    assert review_client.get("/api/auth/me", cookies={"yueji_session": "x" * 300}).status_code == 401
    assert review_client.post("/api/auth/logout", cookies={"yueji_session": "x" * 300}).status_code == 200


def test_origin_scheme_and_global_csrf_protect_all_unsafe_api(review_client):
    good = review_client.post("/api/auth/register", json={
        "invite_code": "REVIEW-INVITE", "username": "同源用户", "password": "ValidPassword-2026",
    }, headers={"Origin": "http://testserver"})
    assert good.status_code == 201
    review_client.post("/api/auth/logout")

    bad_scheme = review_client.post("/api/auth/register", json={
        "invite_code": "REVIEW-INVITE", "username": "跨协议", "password": "ValidPassword-2026",
    }, headers={"Origin": "https://testserver"})
    assert bad_scheme.status_code == 403

    login = review_client.post("/api/auth/login", json={"username": "同源用户", "password": "ValidPassword-2026"})
    assert login.status_code == 200
    book = review_client.post("/api/books/import", files={"file": ("csrf.txt", "阿尔法。\n\n贝塔。", "text/plain")}, data={"title": "CSRF"})
    assert book.status_code == 201
    note = review_client.post("/api/notes", json={"book_id": book.json()["book"]["id"], "text": "同源笔记"})
    assert note.status_code == 201
    cross = review_client.post("/api/notes", json={"book_id": book.json()["book"]["id"], "text": "跨站笔记"}, headers={"Origin": "https://testserver"})
    assert cross.status_code == 403


def test_configured_public_origin_accepted_behind_reverse_proxy(tmp_path, monkeypatch):
    """托管反代下 Host 头是内部地址：白名单内的公开 Origin 必须通过，未列出的来源仍被拒绝。"""
    monkeypatch.setenv("YUEJI_DATA_DIR", str(tmp_path / "public-origin"))
    monkeypatch.setenv("YUEJI_SEED_SAMPLES", "false")
    monkeypatch.setenv("YUEJI_AUTH_REQUIRED", "false")
    monkeypatch.setenv("YUEJI_ENV", "trial")
    monkeypatch.setenv("YUEJI_PUBLIC_ORIGINS", "https://example.com")
    with TestClient(app) as client:
        client.post("/api/auth/logout")
        good = client.post("/api/books/import", files={"file": ("origin.txt", "阿尔法。\n\n贝塔。", "text/plain")}, data={"title": "反代导入"}, headers={
            "Origin": "https://example.com",
            "Host": "3000-internal.e2b.sandbox.example",
        })
        assert good.status_code == 201, good.text
        bad = client.post("/api/books/import", files={"file": ("origin2.txt", "伽马。", "text/plain")}, data={"title": "跨站导入"}, headers={
            "Origin": "https://evil.example",
            "Host": "3000-internal.e2b.sandbox.example",
        })
        assert bad.status_code == 403


def test_bootstrap_invite_is_created_without_secret_material(tmp_path, monkeypatch):
    monkeypatch.setenv("YUEJI_DATA_DIR", str(tmp_path / "bootstrap"))
    monkeypatch.setenv("YUEJI_SEED_SAMPLES", "false")
    monkeypatch.setenv("YUEJI_BOOTSTRAP_INVITE_CODE", "YJ-BOOTSTRAP-TEST")
    settings = get_settings()
    auth.ensure_bootstrap_invite(settings)
    account = register_user(settings, "YJ-BOOTSTRAP-TEST", "初始同学", "ValidPassword-2026")
    assert account["username"] == "初始同学"


def test_production_startup_requires_auth_secure_cookie_and_master_key(monkeypatch, tmp_path):
    monkeypatch.setenv("YUEJI_DATA_DIR", str(tmp_path / "prod"))
    monkeypatch.setenv("YUEJI_ENV", "production")
    monkeypatch.setenv("YUEJI_AUTH_REQUIRED", "false")
    monkeypatch.setenv("YUEJI_SECURE_COOKIES", "false")
    monkeypatch.delenv("YUEJI_MASTER_KEY", raising=False)
    with pytest.raises(RuntimeError, match="认证"):
        with TestClient(app):
            pass

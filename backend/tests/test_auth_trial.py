from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.auth import auth_connect, create_invite, rate_limiter
from app.main import app


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


@pytest.fixture
def trial_client(tmp_path, monkeypatch):
    monkeypatch.setenv("YUEJI_DATA_DIR", str(tmp_path / "trial"))
    monkeypatch.setenv("YUEJI_SEED_SAMPLES", "false")
    monkeypatch.setenv("YUEJI_AUTH_REQUIRED", "true")
    monkeypatch.setenv("YUEJI_TEST_INVITE_CODE", "E2E-INVITE-2026")
    monkeypatch.setenv("YUEJI_MASTER_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=")
    with TestClient(app) as test_client:
        yield test_client


def register(client: TestClient, username: str, password: str = "TrialPassword-2026"):
    return client.post("/api/auth/register", json={"invite_code": "E2E-INVITE-2026", "username": username, "password": password})


def import_txt(client: TestClient, filename="隔离.txt", title="隔离书"):
    response = client.post("/api/books/import", files={"file": (filename, "阿尔法。\n\n贝塔。", "text/plain")}, data={"title": title, "author": "隔离作者"})
    assert response.status_code == 201, response.text
    return response.json()["book"]


def test_register_login_logout_and_password_hash(trial_client):
    assert trial_client.get("/api/books").status_code == 401
    response = register(trial_client, "同学甲")
    assert response.status_code == 201, response.text
    cookie = response.headers.get("set-cookie", "")
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "password" not in cookie.lower()

    me = trial_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "同学甲"
    assert trial_client.get("/api/books").status_code == 200

    with auth_connect(trial_client.app.state.settings) as conn:
        stored = conn.execute("SELECT password_hash FROM auth_users WHERE username = '同学甲'").fetchone()[0]
        users = conn.execute("SELECT username FROM auth_users ORDER BY created_at").fetchall()
    assert stored.startswith("scrypt$")
    assert "TrialPassword-2026" not in stored
    assert [row[0] for row in users] == ["同学甲"]

    assert trial_client.post("/api/auth/logout").status_code == 200
    assert trial_client.get("/api/books").status_code == 401
    assert trial_client.post("/api/auth/login", json={"username": "同学甲", "password": "wrong-password"}).status_code == 401
    login = trial_client.post("/api/auth/login", json={"username": "同学甲", "password": "TrialPassword-2026"})
    assert login.status_code == 200
    assert trial_client.get("/api/auth/me").json()["user"]["username"] == "同学甲"


def test_invite_validation_and_origin_protection(trial_client):
    bad = trial_client.post("/api/auth/register", json={"invite_code": "WRONG", "username": "无邀请", "password": "TrialPassword-2026"})
    assert bad.status_code == 403

    csrf = trial_client.post(
        "/api/auth/register",
        json={"invite_code": "E2E-INVITE-2026", "username": "跨站用户", "password": "TrialPassword-2026"},
        headers={"Origin": "https://evil.example"},
    )
    assert csrf.status_code == 403


def test_two_users_are_fully_isolated_by_database(trial_client):
    first = register(trial_client, "用户一")
    assert first.status_code == 201
    first_book = import_txt(trial_client)
    first_note = trial_client.post("/api/notes", json={"book_id": first_book["id"], "text": "只有用户一能看到的原话。"})
    assert first_note.status_code == 201
    assert trial_client.post("/api/auth/logout").status_code == 200

    second = register(trial_client, "用户二")
    assert second.status_code == 201
    second_book = import_txt(trial_client, filename="隔离2.txt", title="隔离书二")
    assert second_book["id"] != first_book["id"]
    assert second_book["edition_id"] != first_book["edition_id"] or second_book["id"] != first_book["id"]

    assert trial_client.get(f"/api/books/{first_book['id']}").status_code == 404
    assert trial_client.get(f"/api/notes/{first_note.json()['id']}").status_code == 404
    assert trial_client.get("/api/timeline").json()["items"] == []
    books = trial_client.get("/api/books").json()["items"]
    assert [book["title"] for book in books] == ["隔离书二"]


def test_invite_cli_creates_single_use_code(trial_client, tmp_path):
    settings = trial_client.app.state.settings
    code = create_invite(settings, "测试邀请", uses=1)
    one = trial_client.post("/api/auth/register", json={"invite_code": code, "username": "邀请一", "password": "TrialPassword-2026"})
    assert one.status_code == 201
    two = trial_client.post("/api/auth/register", json={"invite_code": code, "username": "邀请二", "password": "TrialPassword-2026"})
    assert two.status_code == 403


def test_readable_invite_code_accepts_case_variants(trial_client):
    """手机输入法会把首字母自动大写：YJ-XXXX-XXXX 被输成 yj-xxxx-xxxx 也应可用。

    只对「人工可读」的邀请码成立；随机邀请码是 YJ- + base64url，本身大小写混合，不做宽容。
    """
    lowered = trial_client.post(
        "/api/auth/register",
        json={"invite_code": "e2e-invite-2026", "username": "邀请小写", "password": "TrialPassword-2026"},
    )
    assert lowered.status_code == 201, lowered.text
    assert trial_client.post("/api/auth/logout").status_code == 200

    capitalized = trial_client.post(
        "/api/auth/register",
        json={"invite_code": "E2e-Invite-2026", "username": "邀请首字母大写", "password": "TrialPassword-2026"},
    )
    assert capitalized.status_code == 201, capitalized.text

    still_wrong = trial_client.post(
        "/api/auth/register",
        json={"invite_code": "E2E-INVITE-2026X", "username": "错码用户", "password": "TrialPassword-2026"},
    )
    assert still_wrong.status_code == 403

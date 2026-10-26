from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
from typing import Any
from urllib.parse import urlparse

from contextlib import contextmanager
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse

from . import db
from .config import PROJECT_ROOT, Settings
from .library import new_id, utcnow

SESSION_COOKIE = "yueji_session"
USERNAME_RE = re.compile(r"^[\w\u4e00-\u9fa5-]{2,30}$")
COMMON_PASSWORDS = {"password", "password123", "1234567890", "qwerty123456", "1111111111"}

AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS auth_users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    disabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_invites (
    code_hash TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    max_uses INTEGER NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id, expires_at);
"""


class RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = datetime.now(timezone.utc).timestamp()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                raise HTTPException(429, "操作过于频繁，请稍后再试")
            hits.append(now)


rate_limiter = RateLimiter()


def auth_connect(settings: Settings) -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect_path(settings.auth_database_path)
    conn.executescript(AUTH_SCHEMA)
    return conn


@contextmanager
def _auth_db(settings: Settings):
    """sqlite3 的 with 只管事务不管关闭；这里统一提交/回滚并确保连接被关闭。"""
    conn = auth_connect(settings)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def validate_runtime_settings(settings: Settings) -> None:
    if settings.is_production:
        if not settings.auth_required:
            raise RuntimeError("生产环境必须启用认证（YUEJI_AUTH_REQUIRED=true）")
        if not settings.secure_cookies:
            raise RuntimeError("生产环境必须启用 Secure Cookie（YUEJI_SECURE_COOKIES=true）")
        if not settings.master_key:
            raise RuntimeError("生产环境必须通过 YUEJI_MASTER_KEY 注入凭据主密钥")


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)
    return "scrypt$16384$8$1$" + salt.hex() + "$" + digest.hex()


def _verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=64)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def create_invite(settings: Settings, label: str, uses: int = 20, created_by: str | None = None) -> str:
    raw = "YJ-" + secrets.token_urlsafe(18)
    with _auth_db(settings) as conn:
        conn.execute(
            "INSERT INTO auth_invites(code_hash, label, max_uses, uses, created_by, created_at) VALUES (?, ?, ?, 0, ?, ?)",
            (_hash_code(raw), label[:80], max(1, uses), created_by, utcnow()),
        )
    return raw


def ensure_bootstrap_invite(settings: Settings) -> None:
    """托管试用启动时可注入一个初始邀请码；只写邀请表，不写入任何主密钥或用户 Key。"""
    if not settings.bootstrap_invite_code:
        return
    with _auth_db(settings) as conn:
        conn.execute(
            """INSERT INTO auth_invites(code_hash, label, max_uses, uses, created_by, created_at)
               VALUES (?, '初始邀请', 100, 0, 'bootstrap', ?)
               ON CONFLICT(code_hash) DO NOTHING""",
            (_hash_code(settings.bootstrap_invite_code), utcnow()),
        )


def validate_user_input(username: str, password: str) -> str:
    username = username.strip()
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(400, "用户名需为 2-30 位中文、字母、数字、下划线或短横线")
    if len(password) < 10 or len(password) > 128 or password.lower() in COMMON_PASSWORDS:
        raise HTTPException(400, "密码需 10-128 位，且不能使用常见密码")
    return username


def prepare_user_database(settings: Settings, user_id: str) -> None:
    path = db.user_database_path(settings, user_id)
    db.initialize_path(path)
    if settings.seed_samples:
        from . import library

        with db.connect_path(path) as conn:
            library.seed_samples(conn, PROJECT_ROOT / "samples")


def _insert_user(conn: sqlite3.Connection, user_id: str, username: str, password: str, display_name: str | None) -> dict[str, Any]:
    try:
        conn.execute(
            "INSERT INTO auth_users(id, username, display_name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, display_name or username, _hash_password(password), utcnow()),
        )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "用户名已存在") from exc
    return {"id": user_id, "username": username, "display_name": display_name or username}


def create_user(settings: Settings, username: str, password: str, display_name: str | None = None, prepare: bool = True) -> dict[str, Any]:
    username = validate_user_input(username, password)
    user_id = new_id("usr")
    if prepare:
        prepare_user_database(settings, user_id)
    with _auth_db(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        account = _insert_user(conn, user_id, username, password, display_name)
        conn.commit()
    return account


def register_user(settings: Settings, invite_code: str, username: str, password: str) -> dict[str, Any]:
    # 先完成所有输入校验，避免无效请求消耗邀请次数。
    username = validate_user_input(username, password)
    user_id = new_id("usr")
    # 先准备独立空库；若后续并发注册竞争失败，该库没有 auth_users 记录，不会被任何账号访问。
    prepare_user_database(settings, user_id)
    # 测试邀请码同样容忍大小写：可读邀请码（如 YJ-XXXX-XXXX）被手机输入法改成首字母大写后仍应可用。
    test_invite = bool(settings.test_invite_code and settings.test_invite_code.upper() == invite_code.upper())
    with _auth_db(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not test_invite:
            # 手机输入法会把首字母自动大写（yj-xxx → Yj-xxx），同时尝试大写变体；邀请码本身足够长，不影响安全强度。
            candidates = dict.fromkeys([invite_code, invite_code.upper(), invite_code.lower()])
            invite = conn.execute(
                "SELECT * FROM auth_invites WHERE code_hash IN ({})".format(",".join("?" * len(candidates))),
                tuple(_hash_code(item) for item in candidates),
            ).fetchone()
            if not invite:
                raise HTTPException(403, "邀请码无效或已用完")
            updated = conn.execute(
                "UPDATE auth_invites SET uses = uses + 1 WHERE code_hash = ? AND uses < max_uses",
                (invite["code_hash"],),
            )
            if updated.rowcount != 1:
                raise HTTPException(403, "邀请码无效或已用完")
        account = _insert_user(conn, user_id, username, password, None)
        conn.commit()
    return account


def _safe_token_hash(token: str | None) -> str | None:
    if not token or len(token) > 256:
        return None
    try:
        token.encode("ascii")
    except UnicodeEncodeError:
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def validate_origin(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if not origin:
        return
    try:
        parsed = urlparse(origin)
        # 托管平台经反代访问时 Host 头是内部地址，浏览器 Origin 是公开域名；
        # 显式配置的公开来源（白名单）视为同源，等价于 CORS 允许列表。
        if origin.strip().rstrip("/") in request.app.state.settings.public_origins:
            return
        if parsed.scheme.lower() != request.url.scheme.lower():
            raise HTTPException(403, "跨站请求被拒绝")
        origin_host = parsed.hostname or ""
        origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        # Vite 本地代理显式传递原始 Host；生产不信任该自定义头，只按同源反代/直连接口校验。
        host_header = request.headers.get("x-yueji-origin-host") if not request.app.state.settings.is_production else None
        host_header = host_header or request.headers.get("host", "")
        host, _, port_text = host_header.partition(":")
        host_port = int(port_text) if port_text else (443 if request.url.scheme == "https" else 80)
        origin_host_lower = origin_host.lower()
        host_lower = host.lower()
        local_aliases = {"localhost", "127.0.0.1"}
        same_local_alias = (
            not request.app.state.settings.is_production
            and origin_port == host_port
            and origin_host_lower in local_aliases
            and host_lower in local_aliases
        )
        if (origin_host_lower != host_lower or origin_port != host_port) and not same_local_alias:
            raise HTTPException(403, "跨站请求被拒绝")
    except (ValueError, HTTPException) as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(403, "跨站请求被拒绝") from exc


def client_key(request: Request, scope: str) -> str:
    # 不无条件信任客户端可伪造的 X-Forwarded-For；同一反代后的同学按 client/IP 分桶。
    ip = request.client.host if request.client else "local"
    return f"{scope}:{ip}"


def create_session(settings: Settings, user_id: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    session_id = new_id("sess")
    expires = datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)
    with _auth_db(settings) as conn:
        conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (utcnow(), user_id))
        conn.execute(
            "INSERT INTO auth_sessions(id, user_id, token_hash, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, token_hash, utcnow(), expires.isoformat()),
        )
        conn.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (utcnow(),))
    return token, session_id


def set_session_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def current_user(request: Request) -> sqlite3.Row | None:
    settings: Settings = request.app.state.settings
    token_hash = _safe_token_hash(request.cookies.get(SESSION_COOKIE))
    if not token_hash:
        return None
    with _auth_db(settings) as conn:
        row = conn.execute(
            """SELECT u.*, s.id AS session_id, s.expires_at FROM auth_sessions s
               JOIN auth_users u ON u.id = s.user_id
              WHERE s.token_hash = ? AND s.revoked_at IS NULL AND u.disabled = 0""",
            (token_hash,),
        ).fetchone()
        if not row or row["expires_at"] < utcnow():
            return None
        return row


def logout(request: Request, response: Response) -> None:
    settings: Settings = request.app.state.settings
    token_hash = _safe_token_hash(request.cookies.get(SESSION_COOKIE))
    if token_hash:
        with _auth_db(settings) as conn:
            conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ?", (utcnow(), token_hash))
    clear_session_cookie(response)


def auth_me(request: Request) -> dict[str, Any]:
    user = current_user(request)
    if not user:
        raise HTTPException(401, "请先登录")
    return {"id": user["id"], "username": user["username"], "display_name": user["display_name"]}


def auth_register(request: Request, payload: dict[str, str]) -> JSONResponse:
    settings: Settings = request.app.state.settings
    validate_origin(request)
    rate_limiter.check(client_key(request, "register"), 8, 600)
    user = register_user(settings, payload["invite_code"], payload["username"], payload["password"])
    token, _ = create_session(settings, user["id"])
    response = JSONResponse({"user": user}, status_code=201)
    set_session_cookie(response, settings, token)
    return response


def auth_login(request: Request, payload: dict[str, str]) -> JSONResponse:
    settings: Settings = request.app.state.settings
    validate_origin(request)
    rate_limiter.check(client_key(request, "login"), 10, 600)
    with _auth_db(settings) as conn:
        user = conn.execute("SELECT * FROM auth_users WHERE username = ? AND disabled = 0", (payload["username"].strip(),)).fetchone()
    if not user or not _verify_password(payload["password"], user["password_hash"]):
        raise HTTPException(401, "用户名或密码不正确")
    token, _ = create_session(settings, user["id"])
    response = JSONResponse({"user": {"id": user["id"], "username": user["username"], "display_name": user["display_name"]}})
    set_session_cookie(response, settings, token)
    return response

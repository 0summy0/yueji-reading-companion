from __future__ import annotations

from contextlib import asynccontextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ai, asking, auth, library, photos, reading, socratic
from .config import PROJECT_ROOT, Settings, get_settings
from .db import connect, get_db, initialize
from .importer import BookImportError, MAX_UPLOAD_BYTES
from .schemas import AIConnectionCreate, AskRequest, AuthLogin, AuthRegister, BookTitleUpdate, LocationConfirm, NoteCreate, NoteUpdate, SessionCreate, SpineStyle, SocraticAnswer, SocraticGenerate, SocraticStart, TaskRoutesUpdate

LOCAL_ADMIN = {"id": "u_local", "username": "local", "display_name": "本地读者"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    auth.validate_runtime_settings(settings)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    app.state.settings = settings
    initialize(settings)
    # 初始化认证库；真实登录用户各自使用 data/users/<id>.sqlite3。
    auth.auth_connect(settings).close()
    auth.ensure_bootstrap_invite(settings)
    if settings.seed_samples and not settings.auth_required:
        with connect(settings) as conn:
            library.seed_samples(conn, PROJECT_ROOT / "samples")
    yield


app = FastAPI(
    title="阅迹 API",
    version="0.2.0",
    description="真实 BYOK、证据式问答、照片确认与邀请制试用版。",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
        try:
            auth.validate_origin(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


@app.exception_handler(BookImportError)
async def import_error_handler(_: Request, exc: BookImportError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        safe = {key: value for key, value in error.items() if key not in {"input", "ctx"}}
        errors.append(safe)
    return JSONResponse(status_code=422, content={"detail": errors})


@app.get("/api/health")
def health(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    return {
        "status": "ok", "phase": "real-trial", "environment": settings.environment,
        "ai_mode": settings.ai_mode, "auth_required": settings.auth_required,
        "real_providers_enabled": settings.real_providers_enabled,
        "master_key_configured": bool(settings.master_key or (settings.allow_local_key_file and not settings.is_production)),
        "photo_location": "verified-route-or-manual",
        "notice": "真实连接需用户自带 Key；照片候选必须确认；未配置 AI 时手账仍可用。",
    }


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    if not settings.auth_required:
        return {"user": LOCAL_ADMIN, "auth_required": False}
    return {"user": auth.auth_me(request), "auth_required": True}


@app.post("/api/auth/register", status_code=201)
def auth_register(request: Request, payload: AuthRegister):
    return auth.auth_register(request, payload.model_dump())


@app.post("/api/auth/login")
def auth_login(request: Request, payload: AuthLogin):
    return auth.auth_login(request, payload.model_dump())


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    response = JSONResponse({"logged_out": True})
    auth.logout(request, response)
    return response


@app.get("/api/books")
def books(search: str = "", sort: str = "imported", conn: sqlite3.Connection = Depends(get_db)):
    return {"items": library.list_books(conn, search, sort)}


@app.post("/api/books/import", status_code=201)
async def import_book(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    author: str | None = Form(default=None),
    conn: sqlite3.Connection = Depends(get_db),
):
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    content_type = (file.content_type or "").split(";", 1)[0].lower()
    allowed = {
        ".txt": {"text/plain", "application/octet-stream", ""},
        ".epub": {"application/epub+zip", "application/octet-stream", ""},
    }
    if suffix not in allowed or content_type not in allowed[suffix]:
        raise HTTPException(400, "文件扩展名或 MIME 类型不符合 EPUB/TXT 导入要求")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "文件超过 20 MiB 限制")
    result = library.import_book(conn, data, filename, title, author)
    return {"book": result, "duplicate": result["duplicate"], "message": "同一文件已存在，未重复导入" if result["duplicate"] else "导入完成"}


@app.get("/api/books/{book_id}")
def book_detail(book_id: str, conn: sqlite3.Connection = Depends(get_db)):
    return library.book_detail(conn, book_id)


@app.get("/api/books/{book_id}/passages")
def passages(book_id: str, conn: sqlite3.Connection = Depends(get_db)):
    return {"items": library.list_passages(conn, book_id)}


@app.patch("/api/books/{book_id}/spine")
def update_spine(book_id: str, style: SpineStyle, conn: sqlite3.Connection = Depends(get_db)):
    library.get_book(conn, book_id)
    with conn:
        conn.execute(
            "UPDATE bookshelves SET spine_style_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(style.model_dump(), ensure_ascii=False), library.utcnow(), book_id),
        )
    return library.get_book(conn, book_id)


@app.patch("/api/books/{book_id}/title")
def update_book_title(book_id: str, payload: BookTitleUpdate, conn: sqlite3.Connection = Depends(get_db)):
    return library.update_book_title(conn, book_id, payload.title)


@app.delete("/api/books/{book_id}")
def delete_book(book_id: str, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    return library.delete_book(conn, request.app.state.settings, book_id)


@app.get("/api/books/{book_id}/sessions")
def sessions(book_id: str, conn: sqlite3.Connection = Depends(get_db)):
    return {"items": reading.list_sessions(conn, book_id)}


@app.post("/api/books/{book_id}/sessions", status_code=201)
def create_session(book_id: str, payload: SessionCreate, conn: sqlite3.Connection = Depends(get_db)):
    return reading.create_session(conn, book_id, payload)


@app.post("/api/reading-sessions/{session_id}/context-photos", status_code=201)
async def attach_context_photo(
    session_id: str,
    request: Request,
    file: UploadFile | None = File(default=None),
    photo_url: str | None = Form(default=None),
    cloud_path: str | None = Form(default=None),
    conn: sqlite3.Connection = Depends(get_db),
):
    user = auth.current_user(request)
    auth.rate_limiter.check(f"context-photo:{user['id'] if user else 'local'}", 20, 60)
    if file is not None:
        data = await file.read(photos.MAX_PHOTO_BYTES + 1)
    elif photo_url:
        data = photos.fetch_signed_photo(photo_url)
    else:
        raise HTTPException(400, "请选择一张阅读环境照片，或提供云存储签名链接")
    sanitized, _, _, _ = photos.sanitize_photo(data)
    return reading.attach_context_photo(conn, request.app.state.settings, session_id, sanitized, cloud_path=cloud_path)


@app.get("/api/reading-sessions/{session_id}/context-photos/{photo_id}/file")
def context_photo_file(session_id: str, photo_id: str, conn: sqlite3.Connection = Depends(get_db)):
    return FileResponse(reading.context_photo_file(conn, session_id, photo_id), media_type="image/jpeg")


@app.get("/api/books/{book_id}/notes")
def notes(book_id: str, conn: sqlite3.Connection = Depends(get_db)):
    return {"items": reading.list_notes(conn, book_id)}


@app.post("/api/notes", status_code=201)
def create_note(payload: NoteCreate, conn: sqlite3.Connection = Depends(get_db)):
    return reading.create_note(conn, payload)


@app.get("/api/notes/{note_id}")
def note_detail(note_id: str, conn: sqlite3.Connection = Depends(get_db)):
    return reading._note_dict(conn, note_id)


@app.patch("/api/notes/{note_id}")
def update_note(note_id: str, payload: NoteUpdate, conn: sqlite3.Connection = Depends(get_db)):
    return reading.update_note(conn, note_id, payload)


@app.get("/api/timeline")
def global_timeline(book_id: str | None = None, conn: sqlite3.Connection = Depends(get_db)):
    return {"items": reading.timeline(conn, book_id)}


@app.get("/api/photo-path")
def photo_path(conn: sqlite3.Connection = Depends(get_db)):
    return ai.photo_path_status(conn)


@app.post("/api/books/{book_id}/location-attempts", status_code=201)
def create_location_attempt(
    book_id: str,
    request: Request,
    file: UploadFile | None = File(default=None),
    photo_url: str | None = Form(default=None),
    cloud_path: str | None = Form(default=None),
    conn: sqlite3.Connection = Depends(get_db),
):
    settings: Settings = request.app.state.settings
    user = auth.current_user(request)
    auth.rate_limiter.check(f"photo:{user['id'] if user else 'local'}", 20, 60)
    if file is not None:
        data = file.file.read(photos.MAX_PHOTO_BYTES + 1)
    elif photo_url:
        data = photos.fetch_signed_photo(photo_url)
    else:
        raise HTTPException(400, "请上传照片文件或提供云存储签名链接")
    return photos.create_location_attempt(conn, settings, book_id, data, cloud_path=cloud_path)


@app.post("/api/location-attempts/{attempt_id}/confirm")
def confirm_location_attempt(attempt_id: str, payload: LocationConfirm, conn: sqlite3.Connection = Depends(get_db)):
    return photos.confirm_location_attempt(conn, attempt_id, payload)


@app.post("/api/ask")
def ask(request: Request, payload: AskRequest, conn: sqlite3.Connection = Depends(get_db)):
    settings: Settings = request.app.state.settings
    user = auth.current_user(request)
    auth.rate_limiter.check(f"ask:{user['id'] if user else 'local'}", 20, 60)
    return asking.ask(conn, settings, payload)


@app.post("/api/evidence")
def evidence(request: Request, payload: AskRequest, conn: sqlite3.Connection = Depends(get_db)):
    """只返回当前用户已读证据包，供前端免密钥云端问答自行组织提示词；不做模型调用。"""
    user = auth.current_user(request)
    auth.rate_limiter.check(f"evidence:{user['id'] if user else 'local'}", 30, 60)
    items = asking.evidence_package(conn, payload)
    compact = [
        {
            "id": item["id"], "kind": item["kind"], "speaker": item["speaker"],
            "book_id": item["book_id"], "book_title": item["book_title"],
            "chapter_title": item["chapter_title"], "position": item["position"],
            "excerpt": item["excerpt"], "text": item["text"][:500],
        }
        for item in items
    ]
    return {"items": compact}


@app.post("/api/socratic/start", status_code=201)
def socratic_start(request: Request, payload: SocraticStart, conn: sqlite3.Connection = Depends(get_db)):
    settings: Settings = request.app.state.settings
    user = auth.current_user(request)
    auth.rate_limiter.check(f"socratic:{user['id'] if user else 'local'}", 12, 60)
    return socratic.start(conn, settings, payload)


@app.get("/api/socratic")
def socratic_list(conn: sqlite3.Connection = Depends(get_db)):
    return {"items": socratic.list_sessions(conn)}


@app.get("/api/socratic/{session_id}")
def socratic_detail(session_id: str, conn: sqlite3.Connection = Depends(get_db)):
    return socratic.session_detail(conn, session_id)


@app.post("/api/socratic/{session_id}/answer")
def socratic_answer(session_id: str, request: Request, payload: SocraticAnswer, conn: sqlite3.Connection = Depends(get_db)):
    user = auth.current_user(request)
    auth.rate_limiter.check(f"socratic:{user['id'] if user else 'local'}", 12, 60)
    return socratic.answer(conn, session_id, payload)


@app.post("/api/socratic/{session_id}/generate")
def socratic_generate(session_id: str, request: Request, payload: SocraticGenerate, conn: sqlite3.Connection = Depends(get_db)):
    settings: Settings = request.app.state.settings
    user = auth.current_user(request)
    auth.rate_limiter.check(f"socratic:{user['id'] if user else 'local'}", 12, 60)
    return socratic.generate(conn, settings, session_id, payload)


@app.post("/api/socratic/{session_id}/finish")
def socratic_finish(session_id: str, request: Request, payload: SocraticGenerate, conn: sqlite3.Connection = Depends(get_db)):
    settings: Settings = request.app.state.settings
    user = auth.current_user(request)
    auth.rate_limiter.check(f"socratic:{user['id'] if user else 'local'}", 12, 60)
    return socratic.finish(conn, settings, session_id, payload)


@app.post("/api/ai/connections", status_code=201)
def create_ai_connection(request: Request, payload: AIConnectionCreate, conn: sqlite3.Connection = Depends(get_db)):
    return ai.create_connection(conn, payload, settings=request.app.state.settings)


@app.get("/api/ai/connections")
def ai_connections(conn: sqlite3.Connection = Depends(get_db)):
    return {"items": ai.list_connections(conn)}


@app.post("/api/ai/connections/{connection_id}/verify")
def verify_ai_connection(request: Request, connection_id: str, conn: sqlite3.Connection = Depends(get_db)):
    return ai.verify_connection(conn, connection_id, settings=request.app.state.settings)


@app.get("/api/ai/connections/{connection_id}/capabilities")
def ai_capabilities(connection_id: str, conn: sqlite3.Connection = Depends(get_db)):
    return ai.get_capabilities(conn, connection_id)


@app.get("/api/ai/task-routes")
def task_routes(conn: sqlite3.Connection = Depends(get_db)):
    return {"routes": ai.get_routes(conn)}


@app.put("/api/ai/task-routes")
def update_task_routes(payload: TaskRoutesUpdate, conn: sqlite3.Connection = Depends(get_db)):
    return {"routes": ai.update_routes(conn, payload)}


@app.post("/api/ai/connections/{connection_id}/revoke")
def revoke_ai_connection(connection_id: str, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT id FROM ai_connections WHERE id = ? AND user_id = 'u_local'", (connection_id,)).fetchone()
    if not row:
        raise HTTPException(404, "AI 连接不存在")
    with conn:
        conn.execute("DELETE FROM ai_connections WHERE id = ?", (connection_id,))
    return {"revoked": True, "message": "连接与加密凭据引用已删除；原始笔记不受影响"}


frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")

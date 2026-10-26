from __future__ import annotations

from difflib import SequenceMatcher
import io
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from fastapi import HTTPException
import httpx
from PIL import Image

from . import ai, library, reading
from .config import Settings
from .library import LOCAL_USER, new_id, utcnow
from .providers.base import ProviderError
from .schemas import LocationConfirm, SessionCreate

MAX_PHOTO_BYTES = 12 * 1024 * 1024
MAX_PHOTO_PIXELS = 20_000_000
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
Image.MAX_IMAGE_PIXELS = MAX_PHOTO_PIXELS


def _normalized(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text).lower()


def sanitize_photo(data: bytes) -> tuple[bytes, int, int, str]:
    if not data:
        raise HTTPException(400, "照片为空")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "照片超过 12 MiB 限制")
    try:
        source = Image.open(io.BytesIO(data))
        source.verify()
        source = Image.open(io.BytesIO(data))
        image_format = (source.format or "").upper()
        if image_format not in ALLOWED_IMAGE_FORMATS:
            raise HTTPException(400, "仅支持 JPG、PNG 或 WebP 照片")
        width, height = source.size
        if width < 100 or height < 100 or width > 4096 or height > 4096:
            raise HTTPException(400, "照片尺寸需在 100—4096 像素之间")
        if width * height > MAX_PHOTO_PIXELS:
            raise HTTPException(413, "照片像素总数超限")
        if source.mode not in {"RGB", "L"}:
            source = source.convert("RGB")
        output = io.BytesIO()
        # 重编码会去除 EXIF、ICC 外元数据与原始文件内容；只保留服务识别所需像素。
        source.save(output, format="JPEG", quality=88, optimize=True)
        sanitized = output.getvalue()
        if len(sanitized) > MAX_PHOTO_BYTES:
            raise HTTPException(413, "照片重编码后仍超过 12 MiB")
        return sanitized, width, height, "jpeg"
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "照片无法安全解析，请补拍清晰书页") from exc


def _photo_route(conn: sqlite3.Connection) -> tuple[sqlite3.Row, dict[str, Any], str]:
    """严格执行用户选择的路径；analyze 与 OCR 两条路线不存在静默跨供应商回退。"""
    routes = ai.get_routes(conn)
    if routes.get("analyze_image"):
        task = "analyze_image"
        required = ("vision_input", "page_ocr")
    elif routes.get("ocr_page"):
        task = "ocr_page"
        required = ("page_ocr",)
    else:
        raise HTTPException(400, "尚未在任务路由中选择拍照识别或独立 OCR；请使用手动定位或保存待定位笔记")
    row = conn.execute(
        "SELECT * FROM ai_connections WHERE id = ? AND user_id = ? AND enabled = 1",
        (routes[task], LOCAL_USER),
    ).fetchone()
    if not row:
        raise HTTPException(400, "所选照片识别连接不存在或已停用，请重新检测或改用手动定位")
    capabilities = ai.get_capabilities(conn, routes[task], required=False)
    if not capabilities:
        raise HTTPException(400, "所选照片识别连接尚未产生能力状态，请重新检测")
    missing = [name for name in required if capabilities[name]["status"] != "verified"]
    if missing:
        raise HTTPException(400, "照片识别路由尚未通过所需能力检测；请使用手动定位")
    return row, capabilities, task


def _ocr_fields(provider: Any, image_bytes: bytes) -> dict[str, Any]:
    result = provider.ocr_page(image_bytes, "zh-CN")
    fields = result.fields
    lines = fields.get("lines")
    if not isinstance(lines, list) or not any(str(line).strip() for line in lines):
        raw = str(fields.get("raw") or "")
        lines = [line.strip() for line in re.split(r"[\n。！？]", raw) if line.strip()]
    fields["lines"] = [str(line).strip() for line in lines if str(line).strip()][:12]
    return fields


def _candidates(passages: list[dict[str, Any]], lines: list[str]) -> list[dict[str, Any]]:
    query_parts = [_normalized(line) for line in lines if len(_normalized(line)) >= 4]
    if not query_parts:
        return []
    scored: list[dict[str, Any]] = []
    seen: set[str] = set()
    for passage in passages:
        passage_key = _normalized(passage["text"])
        if len(passage_key) < 4 or passage["id"] in seen:
            continue
        best = max(SequenceMatcher(None, query, passage_key).ratio() for query in query_parts)
        for query in query_parts:
            if query and query in passage_key:
                best = max(best, min(0.98, 0.72 + len(query) / max(len(passage_key), 1)))
        if best < 0.30:
            continue
        confidence = "high" if best >= 0.82 else "medium" if best >= 0.55 else "low"
        scored.append({
            "passage_id": passage["id"], "chapter_title": passage["chapter_title"], "position": passage["position"],
            "start_char": passage["start_char"], "end_char": passage["end_char"],
            "excerpt": passage["text"][:220], "score": round(best, 4), "confidence": confidence,
        })
        seen.add(passage["id"])
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:3]


def fetch_signed_photo(url: str) -> bytes:
    """从用户云存储签名 URL 下载照片字节；仅接受 HTTPS，禁止跟随重定向，限制体积。"""
    if not url.startswith("https://"):
        raise HTTPException(400, "照片地址必须为 HTTPS 签名链接")
    try:
        with httpx.Client(timeout=25, follow_redirects=False) as client:
            response = client.get(url)
    except httpx.TransportError as exc:
        raise HTTPException(400, "照片下载失败，请重新上传后再试") from exc
    if response.status_code != 200:
        raise HTTPException(400, "照片签名链接已失效，请重新上传后再试")
    data = response.content
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "照片超过 12 MiB 限制")
    return data


def create_location_attempt(
    conn: sqlite3.Connection,
    settings: Settings,
    book_id: str,
    data: bytes,
    cloud_path: str | None = None,
) -> dict[str, Any]:
    book = library.get_book(conn, book_id)
    sanitized, width, height, image_kind = sanitize_photo(data)
    row, capabilities, task = _photo_route(conn)
    photo_id = new_id("ph")
    attempt_id = new_id("la")
    now = utcnow()
    local_path: str | None = None
    retention_policy = "private_local"
    if cloud_path:
        # 照片已由前端去 EXIF 并直传云存储；服务端只保留云端对象路径，不再写本地文件。
        if not re.fullmatch(r"users/[A-Za-z0-9._/-]+\.[A-Za-z0-9]+", cloud_path) or ".." in cloud_path:
            raise HTTPException(400, "云端照片路径不合法")
        retention_policy = "cloud_private"
    else:
        photo_path: Path = settings.photo_dir / LOCAL_USER / f"{photo_id}.jpg"
        photo_path.parent.mkdir(parents=True, exist_ok=True)
        photo_path.write_bytes(sanitized)
        local_path = str(photo_path)
    with conn:
        conn.execute(
            """INSERT INTO photos(id, user_id, session_id, local_path, cloud_path, captured_at, retention_policy, created_at, book_id, edition_id)
               VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)""",
            (photo_id, LOCAL_USER, local_path, cloud_path, now, retention_policy, now, book["id"], book["edition_id"]),
        )
        conn.execute(
            """INSERT INTO location_attempts(id, user_id, photo_id, ocr_text, candidate_json, confidence, chosen_anchor, state, created_at, book_id)
               VALUES (?, ?, ?, NULL, '[]', NULL, NULL, 'pending', ?, ?)""",
            (attempt_id, LOCAL_USER, photo_id, now, book["id"]),
        )
    try:
        provider = ai._provider_for_connection(settings, row)
        try:
            fields = _ocr_fields(provider, sanitized)
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
        ocr_text = "\n".join(fields.get("lines", []))[:1500] or str(fields.get("raw", ""))[:1500]
        candidates = _candidates(library.list_passages(conn, book_id), fields.get("lines", []))
        state = "candidates" if candidates else "failed"
        confidence = candidates[0]["confidence"] if candidates else None
        message = "请核对 Top 3 候选；确认前阅读进度不会改变。" if candidates else "没有可靠候选。请补拍、手动选择段落，或保存为待定位笔记。"
        with conn:
            conn.execute(
                "UPDATE location_attempts SET ocr_text = ?, candidate_json = ?, confidence = ?, state = ? WHERE id = ?",
                (ocr_text, json.dumps(candidates, ensure_ascii=False), confidence, state, attempt_id),
            )
        return {
            "attempt": {
                "id": attempt_id, "photo_id": photo_id, "state": state, "ocr_text": ocr_text,
                "candidates": candidates, "message": message, "task_route": task, "cloud_path": cloud_path,
                "provider": {"alias": capabilities.get("provider_alias"), "model_id": capabilities.get("model_id"), "task_route": task},
                "photo": {"width": width, "height": height, "format": image_kind},
            }
        }
    except ProviderError as error:
        with conn:
            conn.execute(
                "UPDATE location_attempts SET ocr_text = ?, candidate_json = '[]', confidence = NULL, state = 'failed' WHERE id = ?",
                (f"识别失败：{error.safe_message}"[:1000], attempt_id),
            )
        return {"attempt": {"id": attempt_id, "photo_id": photo_id, "state": "failed", "ocr_text": "", "candidates": [], "message": f"识别失败：{error.safe_message}。可使用手动定位。", "task_route": task, "cloud_path": cloud_path}}


def confirm_location_attempt(conn: sqlite3.Connection, attempt_id: str, payload: LocationConfirm) -> dict[str, Any]:
    attempt = conn.execute(
        "SELECT * FROM location_attempts WHERE id = ? AND user_id = ?",
        (attempt_id, LOCAL_USER),
    ).fetchone()
    if not attempt:
        raise HTTPException(404, "定位尝试不存在")

    existing = conn.execute(
        "SELECT id FROM reading_sessions WHERE source_location_attempt_id = ?", (attempt_id,)
    ).fetchone()
    if existing:
        return {"session": reading.get_session(conn, existing["id"]), "attempt_id": attempt_id, "message": "该定位已确认过；重复请求返回同一会话，未重复推进度"}

    if attempt["state"] != "candidates":
        raise HTTPException(400, "当前定位尝试没有可确认候选")
    candidates = json.loads(attempt["candidate_json"])
    if payload.chosen_anchor not in {item["passage_id"] for item in candidates}:
        raise HTTPException(400, "只能从返回的 Top 3 候选中确认位置")
    book = library.get_book(conn, attempt["book_id"])
    start_anchor = None
    if payload.sequential_confirmed:
        if payload.session_type != "sequential":
            raise HTTPException(400, "只有顺读会话可以确认连续范围")
        start_anchor = book["progress"].get("current_anchor") or payload.chosen_anchor
    session_payload = SessionCreate(
        started_at=payload.started_at, ended_at=payload.ended_at, timezone=payload.timezone,
        start_anchor=start_anchor, current_anchor=payload.chosen_anchor, session_type=payload.session_type,
        sequential_confirmed=payload.sequential_confirmed, anchor_read_confirmed=payload.anchor_read_confirmed,
        reading_context=payload.reading_context, client_request_id=payload.client_request_id,
    )
    with conn:
        claimed = conn.execute(
            "UPDATE location_attempts SET state = 'confirmed' WHERE id = ? AND state = 'candidates'", (attempt_id,)
        )
        if claimed.rowcount != 1:
            raise HTTPException(409, "该定位正在被确认，请重试获取同一会话")
        session = reading.create_session_core(conn, book["id"], session_payload, source_location_attempt_id=attempt_id)
        conn.execute("UPDATE location_attempts SET chosen_anchor = ? WHERE id = ?", (payload.chosen_anchor, attempt_id))
        conn.execute("UPDATE photos SET session_id = ? WHERE id = ?", (session["id"], attempt["photo_id"]))
    return {"session": session, "attempt_id": attempt_id, "message": "已保存阅读会话；候选确认前未推进度，确认后仅按你的顺读选择扩展范围"}

from __future__ import annotations

from contextlib import closing
import hashlib
import json
import re
import sqlite3
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException

from .config import Settings
from .library import LOCAL_USER, new_id, utcnow
from .probes import page_png, probe_truth, vision_png
from .providers.base import AIProvider, OCRProvider, ProviderError
from .providers.mock import MockProvider
from .providers.openai import OpenAICompatibleProvider, validate_openai_base_url
from .schemas import AIConnectionCreate, TaskRoutesUpdate
from . import secrets_store

PROBE_VERSION = "synthetic-vision-v2"
MOCK_PROBE_VERSION = "mock-synthetic-vision-v1"
ADAPTER_VERSION = "adapter-v2"
SIMULATION_NOTICE = "模拟检测，不代表真实API能力"
REAL_NOTICE = "真实 HTTP 检测；是否通过以各分项状态为准，且只代表当前连接、当前模型与当前适配器版本"


def normalize_model_id(base_url: str, model_id: str) -> str:
    """Map DeepSeek's display/legacy aliases only on the official endpoint."""
    hostname = (urlparse(base_url).hostname or "").lower().rstrip(".")
    aliases = {
        "deepseek-v4.1-flash",
        "deepseek-v4-1-flash",
        "deepseek-v4-flash",
        "deepseek-v4-flash-vision-exp",
    }
    candidate = re.sub(r"[\s_]+", "-", model_id.strip().lower())
    if hostname == "api.deepseek.com" and candidate in aliases:
        return "deepseek-flash"
    return model_id


def _probe_normalize(value: Any) -> str:
    return re.sub(r"[\s\u3000，。！？、；：:,.!?\"'`*_]+", "", str(value)).upper()


def _probe_lines_match(actual: Any, expected: list[str]) -> bool:
    if isinstance(actual, str):
        lines = actual.splitlines()
    elif isinstance(actual, list):
        lines = [str(item) for item in actual]
    else:
        lines = []
    normalized_actual = [_probe_normalize(line) for line in lines if _probe_normalize(line)]
    normalized_expected = [_probe_normalize(line) for line in expected]
    cursor = 0
    for line in normalized_actual:
        if cursor < len(normalized_expected) and line == normalized_expected[cursor]:
            cursor += 1
    return cursor == len(normalized_expected)


def _probe_color(value: Any) -> str:
    aliases = {"RED": "红色", "GREEN": "绿色", "BLUE": "蓝色"}
    normalized = _probe_normalize(value)
    return aliases.get(normalized, normalized)


def _secret_fingerprint(secret_ref: str | None) -> str:
    return hashlib.sha256((secret_ref or "none").encode("utf-8")).hexdigest()[:16]


def _fingerprint(payload: AIConnectionCreate, secret_ref: str | None = None) -> str:
    raw = "|".join([
        payload.provider_type,
        payload.model_id,
        payload.base_url,
        payload.scenario or "none",
        ADAPTER_VERSION,
        _secret_fingerprint(secret_ref),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _connection_dict(row: sqlite3.Row) -> dict[str, Any]:
    is_mock = row["provider_type"] == "mock"
    return {
        "id": row["id"], "alias": row["alias"], "provider_type": row["provider_type"],
        "model_id": row["model_id"], "base_url": row["base_url"], "adapter_version": row["adapter_version"],
        "config_fingerprint": row["config_fingerprint"], "scenario": row["mock_scenario"],
        "enabled": bool(row["enabled"]), "created_at": row["created_at"], "updated_at": row["updated_at"],
        "credential_mode": "not_collected_mock" if is_mock else "stored_encrypted",
        "has_saved_key": bool(row["secret_ref"]),
        "simulation_notice": SIMULATION_NOTICE if is_mock else REAL_NOTICE,
    }


def list_connections(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM ai_connections WHERE user_id = ? ORDER BY created_at DESC", (LOCAL_USER,)).fetchall()
    return [{**_connection_dict(row), "capabilities": get_capabilities(conn, row["id"], required=False)} for row in rows]


def create_connection(conn: sqlite3.Connection, payload: AIConnectionCreate, settings: Settings | None = None) -> dict[str, Any]:
    is_mock = payload.provider_type == "mock"
    if is_mock:
        if payload.api_key:
            raise HTTPException(400, "Mock 模式不接收任何 API Key；请勿粘贴真实凭据")
    else:
        if settings and not settings.real_providers_enabled:
            raise HTTPException(403, "真实 Provider 已被管理员禁用")
        if settings:
            try:
                validate_openai_base_url(payload.base_url, settings.allowed_api_hosts)
            except ProviderError as error:
                raise HTTPException(400, error.safe_message) from error
    now = utcnow()
    connection_id = payload.connection_id or new_id("conn")
    existing = conn.execute("SELECT * FROM ai_connections WHERE id = ? AND user_id = ?", (connection_id, LOCAL_USER)).fetchone()
    if payload.connection_id and not existing:
        raise HTTPException(404, "要更新的连接不存在")

    if is_mock:
        secret_ref = None
    else:
        if payload.api_key:
            if not settings:
                raise HTTPException(503, "缺少服务端配置，无法保存真实凭据")
            secret_ref = secrets_store.encrypt_secret(settings, payload.api_key)
        elif existing and existing["secret_ref"]:
            secret_ref = existing["secret_ref"]
        else:
            raise HTTPException(400, "首次保存真实连接必须提供 API Key；更新时可留空保留原 Key")
    fingerprint = _fingerprint(payload, secret_ref)
    with conn:
        if existing:
            conn.execute(
                """UPDATE ai_connections SET alias = ?, provider_type = ?, model_id = ?, base_url = ?, secret_ref = ?,
                   adapter_version = ?, config_fingerprint = ?, mock_scenario = ?, enabled = ?, updated_at = ? WHERE id = ?""",
                (payload.alias, payload.provider_type, payload.model_id, payload.base_url, secret_ref,
                 ADAPTER_VERSION, fingerprint, payload.scenario, int(payload.enabled), now, connection_id),
            )
            if existing["config_fingerprint"] != fingerprint:
                conn.execute(
                    """UPDATE ai_capability_checks SET text_status = 'stale', vision_status = 'stale', page_ocr_status = 'stale',
                       diagnostic_safe_json = ? WHERE connection_id = ?""",
                    (json.dumps({"reason": "配置或凭据指纹已变化，旧结果失效", "simulated": is_mock}, ensure_ascii=False), connection_id),
                )
        else:
            conn.execute(
                """INSERT INTO ai_connections(id, user_id, alias, provider_type, model_id, base_url, secret_ref, adapter_version,
                                              config_fingerprint, mock_scenario, enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (connection_id, LOCAL_USER, payload.alias, payload.provider_type, payload.model_id, payload.base_url,
                 secret_ref, ADAPTER_VERSION, fingerprint, payload.scenario, int(payload.enabled), now, now),
            )
    verification = verify_connection(conn, connection_id, settings=settings)
    row = conn.execute("SELECT * FROM ai_connections WHERE id = ?", (connection_id,)).fetchone()
    return {**_connection_dict(row), "capabilities": verification["capabilities"], "probe_job_id": verification["probe_job_id"]}


def _provider_for_connection(settings: Settings | None, row: sqlite3.Row, truth: dict[str, Any] | None = None) -> AIProvider | OCRProvider:
    if row["provider_type"] == "mock":
        provider = MockProvider(row["mock_scenario"] or "success", row["model_id"])
        provider.mock_probe_truth = truth
        return provider
    if not settings:
        raise HTTPException(503, "缺少服务端配置，无法执行真实模型检测")
    if not settings.real_providers_enabled:
        raise HTTPException(403, "真实 Provider 已被管理员禁用")
    api_key = secrets_store.decrypt_secret(settings, row["secret_ref"])
    model_id = normalize_model_id(row["base_url"], row["model_id"])
    return OpenAICompatibleProvider(row["base_url"], model_id, api_key, settings.allowed_api_hosts)


def _error_status(error: ProviderError) -> tuple[str, str]:
    if error.category == "unsupported":
        return "unsupported", "当前模型接口明确不接受图片输入"
    if error.category == "font_missing":
        return "unverified_error", "系统缺少中文字体，无法完成真实中文书页检测"
    messages = {
        "auth": error.safe_message or "鉴权失败或 Key 无权限，请检查 API Key",
        "model_not_found": "模型或端点不存在，请检查 model_id 与 Base URL",
        "image_too_large": "图片尺寸或请求体超过服务商限制",
        "image_unreadable": "图片格式不被服务商接受或无法解析",
        "payment_required": "账户余额不足或套餐配额已耗尽，请充值后再检测",
        "response_truncated": "模型输出被长度上限截断，结构化结果不完整",
        "reasoning_only": "模型只返回了推理过程，没有可解析答案",
        "rate_limited": "模型服务限流或配额不足，请稍后重试",
        "timeout": "模型服务请求超时",
        "network": "模型服务网络连接失败",
    }
    if error.category in messages:
        return "unverified_error", messages[error.category]
    return "unverified_error", error.safe_message


def verify_connection(conn: sqlite3.Connection, connection_id: str, settings: Settings | None = None) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM ai_connections WHERE id = ? AND user_id = ?", (connection_id, LOCAL_USER)).fetchone()
    if not row:
        raise HTTPException(404, "AI 连接不存在")
    job_type = "VERIFY_CONNECTION"
    input_hash = row["config_fingerprint"]
    job = conn.execute("SELECT * FROM ai_jobs WHERE job_type = ? AND input_hash = ?", (job_type, input_hash)).fetchone()
    if job and job["attempts"] >= 20:
        raise HTTPException(429, "该配置已达到检测上限，请修改配置、稍后再试或检查费用")
    job_id = job["id"] if job else new_id("job")
    with conn:
        if job:
            conn.execute("UPDATE ai_jobs SET state = 'running', attempts = attempts + 1, updated_at = ? WHERE id = ?", (utcnow(), job_id))
        else:
            conn.execute(
                "INSERT INTO ai_jobs(id, user_id, job_type, input_hash, state, attempts, created_at, updated_at) VALUES (?, ?, ?, ?, 'running', 1, ?, ?)",
                (job_id, LOCAL_USER, job_type, input_hash, utcnow(), utcnow()),
            )

    truth = probe_truth()
    simulated = row["provider_type"] == "mock"
    with closing(_provider_for_connection(settings, row, truth)) as provider:
        failure_category: str | None = None
        try:
            text_response = provider.generate_text("仅返回 MOCK_OK，用于模拟文本接口检测。" if simulated else "请只返回两个字：正常。")
            expected = "MOCK_OK" if simulated else "正常"
            text_status = "verified" if expected in text_response.text else "unverified_error"
            text_message = ("模拟文字返回符合校验" if simulated else "真实文字接口返回包含约定文本") if text_status == "verified" else "文字返回与约定校验不一致"
        except ProviderError as error:
            text_status, text_message = _error_status(error)
            failure_category = error.category

        vision_prompt = "图中有一个圆和六位码。请只返回 JSON：{\"code\":\"六位码\",\"color\":\"红色|绿色|蓝色\"}，不要猜测。"
        try:
            vision = provider.analyze_image(vision_png(truth), vision_prompt)
            exact = _probe_normalize(vision.fields.get("code", "")) == _probe_normalize(truth["code"])
            exact = exact and _probe_color(vision.fields.get("color", "")) == truth["color"]
            vision_status = "verified" if exact else "inconclusive"
            vision_message = ("模拟随机图形与六位码均匹配" if simulated else "真实随机图片挑战的六位码与颜色均匹配") if exact else "图片挑战答案不匹配，不能确认识图能力"
            if not exact:
                failure_category = failure_category or "challenge_mismatch"
        except ProviderError as error:
            vision_status, vision_message = _error_status(error)
            failure_category = failure_category or error.category

        try:
            if hasattr(provider, "ocr_probe_page"):
                page = provider.ocr_probe_page(page_png(truth))
            else:
                page = provider.ocr_page(page_png(truth), "zh-CN")
            returned_lines = page.fields.get("lines")
            exact_page = _probe_lines_match(returned_lines, truth["page_lines"])
            exact_page = exact_page and _probe_normalize(page.fields.get("marker", "")) == _probe_normalize(truth["marker"])
            if exact_page:
                page_status = "verified"
                page_message = "模拟中文两行与随机标识完整匹配" if simulated else "真实中文书页两行与随机标识完整匹配"
            elif vision_status == "verified":
                page_status, page_message = "vision_partial", "看图通过，但中文书页字段或顺序不完整"
            else:
                page_status, page_message = "inconclusive", "中文书页读取未通过，不能据此确认识字能力"
            if not exact_page:
                failure_category = failure_category or "page_ocr_mismatch"
        except ProviderError as error:
            page_status, page_message = _error_status(error)
            failure_category = failure_category or error.category

    checked_at = utcnow()
    diagnostics = {
        "simulated": simulated,
        "notice": SIMULATION_NOTICE if simulated else REAL_NOTICE,
        "probe_version": MOCK_PROBE_VERSION if simulated else PROBE_VERSION,
        "text": {"status": text_status, "message": text_message},
        "vision_input": {"status": vision_status, "message": vision_message},
        "page_ocr": {"status": page_status, "message": page_message},
        "privacy": "仅发送内存合成图片；探针真值不进入提示词、文件名或元数据，不保存探针图片" if not simulated else "仅使用内存合成图片；未读取用户照片",
    }
    with conn:
        conn.execute(
            """INSERT INTO ai_capability_checks(id, connection_id, probe_version, checked_at, text_status, vision_status,
                                                page_ocr_status, failure_category, diagnostic_safe_json, config_fingerprint)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_id("cap"), connection_id, MOCK_PROBE_VERSION if simulated else PROBE_VERSION, checked_at, text_status,
             vision_status, page_status, failure_category, json.dumps(diagnostics, ensure_ascii=False), row["config_fingerprint"]),
        )
        conn.execute("UPDATE ai_jobs SET state = 'succeeded', last_error = NULL, updated_at = ? WHERE id = ?", (checked_at, job_id))
    return {"probe_job_id": job_id, "capabilities": get_capabilities(conn, connection_id)}


def get_capabilities(conn: sqlite3.Connection, connection_id: str, required: bool = True) -> dict[str, Any] | None:
    connection = conn.execute("SELECT * FROM ai_connections WHERE id = ?", (connection_id,)).fetchone()
    if not connection:
        if required:
            raise HTTPException(404, "AI 连接不存在")
        return None
    row = conn.execute(
        "SELECT * FROM ai_capability_checks WHERE connection_id = ? ORDER BY checked_at DESC LIMIT 1", (connection_id,)
    ).fetchone()
    is_mock = connection["provider_type"] == "mock"
    if not row:
        if required:
            return {
                "text": {"status": "untested"}, "vision_input": {"status": "untested"}, "page_ocr": {"status": "untested"},
                "simulated": is_mock, "simulation_notice": SIMULATION_NOTICE if is_mock else REAL_NOTICE,
                "provider_alias": connection["alias"], "model_id": connection["model_id"],
            }
        return None
    diagnostics = json.loads(row["diagnostic_safe_json"])
    stale = row["config_fingerprint"] != connection["config_fingerprint"]
    def section(key: str, column: str) -> dict[str, Any]:
        detail = diagnostics.get(key, {})
        return {"status": "stale" if stale else row[column], "message": "配置已变化，请重新检测" if stale else detail.get("message", ""),
                "checked_at": row["checked_at"]}
    return {
        "text": section("text", "text_status"), "vision_input": section("vision_input", "vision_status"),
        "page_ocr": section("page_ocr", "page_ocr_status"), "checked_at": row["checked_at"],
        "probe_version": row["probe_version"], "config_fingerprint": row["config_fingerprint"],
        "failure_category": row["failure_category"], "simulated": is_mock,
        "simulation_notice": SIMULATION_NOTICE if is_mock else REAL_NOTICE,
        "privacy": diagnostics.get("privacy"), "provider_alias": connection["alias"], "model_id": connection["model_id"],
    }


def get_routes(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["task_type"]: row["connection_id"] for row in conn.execute("SELECT * FROM ai_task_routes WHERE user_id = ?", (LOCAL_USER,))}


def _route_connection(conn: sqlite3.Connection, connection_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT enabled FROM ai_connections WHERE id = ? AND user_id = ?", (connection_id, LOCAL_USER)).fetchone()
    if not row or not row["enabled"]:
        raise HTTPException(400, "任务路由选择了不存在或已停用的连接")
    return row


def update_routes(conn: sqlite3.Connection, payload: TaskRoutesUpdate) -> dict[str, str]:
    for task, connection_id in payload.routes.items():
        _route_connection(conn, connection_id)
        capabilities = get_capabilities(conn, connection_id)
        if task in {"generate_text", "extract_structured"} and capabilities["text"]["status"] != "verified":
            raise HTTPException(400, f"任务 {task} 需要文字检测已验证的连接")
        if task == "analyze_image" and not (
            capabilities["vision_input"]["status"] == "verified" and capabilities["page_ocr"]["status"] == "verified"
        ):
            raise HTTPException(400, "照片识别路由要求视觉与中文书页两项均验证；否则请保持手动定位")
        if task == "ocr_page" and capabilities["page_ocr"]["status"] != "verified":
            raise HTTPException(400, "独立 OCR 路由需要中文书页检测已验证")
    now = utcnow()
    with conn:
        # PUT 采用完整替换语义：空对象或“不配置”必须真正删除旧路由。
        conn.execute("DELETE FROM ai_task_routes WHERE user_id = ?", (LOCAL_USER,))
        for task, connection_id in payload.routes.items():
            conn.execute(
                """INSERT INTO ai_task_routes(user_id, task_type, connection_id, updated_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, task_type) DO UPDATE SET connection_id = excluded.connection_id, updated_at = excluded.updated_at""",
                (LOCAL_USER, task, connection_id, now),
            )
    return get_routes(conn)


def connection_for_task(conn: sqlite3.Connection, task_type: str) -> tuple[sqlite3.Row, dict[str, Any]] | tuple[None, None]:
    route = get_routes(conn).get(task_type)
    if not route:
        return None, None
    row = conn.execute("SELECT * FROM ai_connections WHERE id = ? AND user_id = ? AND enabled = 1", (route, LOCAL_USER)).fetchone()
    if not row:
        return None, None
    return row, get_capabilities(conn, route)


def photo_path_status(conn: sqlite3.Connection) -> dict[str, Any]:
    routes = get_routes(conn)
    selected_task: str | None = None
    if routes.get("analyze_image"):
        selected_task = "analyze_image"
    elif routes.get("ocr_page"):
        selected_task = "ocr_page"
    connection_id = routes.get(selected_task) if selected_task else None
    capabilities = get_capabilities(conn, connection_id, required=False) if connection_id else None
    automatic = False
    if capabilities and selected_task == "analyze_image":
        automatic = capabilities["vision_input"]["status"] == "verified" and capabilities["page_ocr"]["status"] == "verified"
    elif capabilities and selected_task == "ocr_page":
        automatic = capabilities["page_ocr"]["status"] == "verified"
    simulated = bool(capabilities and capabilities.get("simulated"))
    return {
        "stage": 2, "automatic_location_available": automatic,
        "display_path": ("ai_vision" if selected_task == "analyze_image" else "ai_ocr") if automatic else "manual",
        "selected_task": selected_task,
        "message": "照片会先去除 EXIF、限制尺寸，再发送给你选择的已验证连接；候选必须经你确认，未确认绝不推进度。" if automatic else "尚未选择并通过拍照识别/独立 OCR 能力检测；请使用手动定位或保存待定位笔记。",
        "routes": routes, "capabilities": capabilities,
        "simulation_notice": SIMULATION_NOTICE if simulated else None,
    }

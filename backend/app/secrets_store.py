from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from .config import Settings

LOCAL_KEY_FILE = ".master_key"


def _load_or_create_local_key(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        key = path.read_text(encoding="utf-8").strip()
        Fernet(key.encode("ascii"))
        return key
    key = Fernet.generate_key().decode("ascii")
    path.write_text(key + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def get_fernet(settings: Settings) -> Fernet | None:
    """真实凭据主密钥。生产必须从 YUEJI_MASTER_KEY 注入；本地显式允许时生成受限文件。"""
    if settings.master_key:
        try:
            return Fernet(settings.master_key.encode("ascii"))
        except Exception as exc:
            raise HTTPException(500, "YUEJI_MASTER_KEY 不是有效 Fernet 密钥，请修正后重启") from exc
    if settings.allow_local_key_file and not settings.is_production:
        key = _load_or_create_local_key(settings.data_dir / LOCAL_KEY_FILE)
        return Fernet(key.encode("ascii"))
    return None


def encrypt_secret(settings: Settings, plaintext: str) -> str:
    fernet = get_fernet(settings)
    if not fernet:
        raise HTTPException(503, "未配置 YUEJI_MASTER_KEY，拒绝保存真实 API Key；本地开发可显式开启 YUEJI_ALLOW_LOCAL_KEY_FILE")
    if not plaintext or len(plaintext) > 4096:
        raise HTTPException(400, "API Key 不能为空且不能超过 4096 字符")
    return "fernet:v1:" + fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(settings: Settings, secret_ref: str | None) -> str:
    if not secret_ref:
        raise HTTPException(500, "连接缺少已保存凭据")
    if not secret_ref.startswith("fernet:v1:"):
        raise HTTPException(500, "凭据引用格式不受支持")
    fernet = get_fernet(settings)
    if not fernet:
        raise HTTPException(503, "未配置凭据主密钥，无法使用该连接")
    try:
        return fernet.decrypt(secret_ref.removeprefix("fernet:v1:").encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise HTTPException(500, "凭据解密失败：主密钥不匹配或数据已损坏") from exc

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_local_env() -> None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_local_env()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() == "true"


DEFAULT_ALLOWED_API_HOSTS = (
    "api.openai.com",
    "api.deepseek.com",
    "api.moonshot.cn",
    "api.groq.com",
    "openrouter.ai",
    "api.together.xyz",
)


@dataclass(frozen=True)
class Settings:
    environment: str
    data_dir: Path
    database_path: Path
    auth_database_path: Path
    user_databases_dir: Path
    photo_dir: Path
    seed_samples: bool
    ai_mode: str
    real_providers_enabled: bool
    auth_required: bool
    secure_cookies: bool
    session_ttl_days: int
    master_key: str | None
    allow_local_key_file: bool
    allowed_api_hosts: tuple[str, ...]
    test_invite_code: str | None
    bootstrap_invite_code: str | None
    public_origins: tuple[str, ...]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def get_settings() -> Settings:
    data_value = Path(os.getenv("YUEJI_DATA_DIR", "./data"))
    data_dir = data_value if data_value.is_absolute() else PROJECT_ROOT / data_value
    data_dir = data_dir.resolve()
    database_name = os.getenv("YUEJI_DATABASE", "yueji.sqlite3")
    if Path(database_name).name != database_name or not database_name.endswith(".sqlite3"):
        raise ValueError("YUEJI_DATABASE 只能是 .sqlite3 文件名。")
    hosts = tuple(
        item.strip().lower()
        for item in os.getenv("YUEJI_ALLOWED_API_HOSTS", ",".join(DEFAULT_ALLOWED_API_HOSTS)).split(",")
        if item.strip()
    )
    test_invite = os.getenv("YUEJI_TEST_INVITE_CODE")
    environment = os.getenv("YUEJI_ENV", "local")
    if environment == "production":
        test_invite = None
    public_origins = tuple(
        item.strip().rstrip("/")
        for item in os.getenv("YUEJI_PUBLIC_ORIGINS", "").split(",")
        if item.strip()
    )
    return Settings(
        environment=environment,
        public_origins=public_origins,
        data_dir=data_dir,
        database_path=data_dir / database_name,
        auth_database_path=data_dir / "auth.sqlite3",
        user_databases_dir=data_dir / "users",
        photo_dir=data_dir / "photos",
        seed_samples=_bool("YUEJI_SEED_SAMPLES", True),
        ai_mode=os.getenv("YUEJI_AI_MODE", "real"),
        real_providers_enabled=_bool("YUEJI_ENABLE_REAL_PROVIDERS", True),
        auth_required=_bool("YUEJI_AUTH_REQUIRED", True),
        secure_cookies=_bool("YUEJI_SECURE_COOKIES", False),
        session_ttl_days=int(os.getenv("YUEJI_SESSION_TTL_DAYS", "7")),
        master_key=os.getenv("YUEJI_MASTER_KEY"),
        allow_local_key_file=_bool("YUEJI_ALLOW_LOCAL_KEY_FILE", False),
        allowed_api_hosts=hosts,
        test_invite_code=test_invite,
        bootstrap_invite_code=os.getenv("YUEJI_BOOTSTRAP_INVITE_CODE"),
    )

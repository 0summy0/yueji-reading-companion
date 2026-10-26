from __future__ import annotations

import argparse
import getpass
import os
import sqlite3

from .auth import _auth_db, _insert_user, create_invite, validate_user_input
from .config import get_settings
from .library import new_id, utcnow
from . import db


def migrate_local_database(settings, username: str, password: str, display_name: str | None = None) -> dict[str, object]:
    """把现有 data/yueji.sqlite3 迁移为新登录用户数据库；使用 SQLite backup API 保留 WAL 数据。"""
    username = validate_user_input(username, password)
    source_path = settings.database_path
    if not source_path.exists():
        raise SystemExit(f"本地数据库不存在：{source_path}")
    user_id = new_id("usr")
    target_path = db.user_database_path(settings, user_id)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        candidate = target_path.with_name(target_path.name + suffix)
        if candidate.exists() and candidate.stat().st_size > 0:
            raise SystemExit(f"目标用户数据库已存在，拒绝覆盖：{candidate}")
        candidate.unlink(missing_ok=True)

    source = sqlite3.connect(source_path)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    db.initialize_path(target_path)

    try:
        with _auth_db(settings) as conn:
            conn.execute("BEGIN IMMEDIATE")
            account = _insert_user(conn, user_id, username, password, display_name)
            conn.commit()
    except Exception:
        for suffix in ("", "-wal", "-shm"):
            target_path.with_name(target_path.name + suffix).unlink(missing_ok=True)
        raise
    return {"account": account, "database_path": target_path}


def main() -> None:
    parser = argparse.ArgumentParser(description="阅迹试用账号与邀请管理")
    parser.add_argument("--data-dir", help="覆盖 YUEJI_DATA_DIR")
    sub = parser.add_subparsers(dest="command", required=True)

    invite = sub.add_parser("invite", help="创建邀请码（只显示一次）")
    invite.add_argument("--label", default="同学试用")
    invite.add_argument("--uses", type=int, default=20)

    user = sub.add_parser("create-user", help="创建用户；可选迁移现有本地 u_local 数据库")
    user.add_argument("--username", required=True)
    user.add_argument("--password")
    user.add_argument("--display-name")
    user.add_argument("--from-local", action="store_true", help="用 SQLite backup API 迁移 data/yueji.sqlite3，保留 WAL 数据")

    args = parser.parse_args()
    if args.data_dir:
        os.environ["YUEJI_DATA_DIR"] = args.data_dir
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    if args.command == "invite":
        code = create_invite(settings, args.label, args.uses, created_by="cli")
        print("邀请码（只显示一次，请私下转发）：")
        print(code)
        return

    password = args.password or getpass.getpass("密码（至少10位）: ")
    if args.from_local:
        result = migrate_local_database(settings, args.username, password, args.display_name)
        account = result["account"]
        target = result["database_path"]
    else:
        from .auth import create_user

        account = create_user(settings, args.username, password, args.display_name)
        target = db.user_database_path(settings, account["id"])
    print(f"已创建用户：{account['username']} ({account['id']})")
    print(f"用户数据库：{target}")


if __name__ == "__main__":
    main()

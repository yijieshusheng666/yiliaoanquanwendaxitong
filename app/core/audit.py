"""操作审计日志：记录关键动作（登录/登出/问答/删除会话/权限变更）到 SQLite。"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from app.config import OUTPUT_DIR

_db_path: Path = OUTPUT_DIR / "audit.db"
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit_logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id TEXT,"
        "username TEXT,"
        "action TEXT NOT NULL,"
        "detail TEXT,"
        "created_at REAL NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)"
    )
    conn.commit()
    return conn


def record(action: str, detail: str = "",
           user_id: Optional[str] = None, username: str = "") -> None:
    """追加一条审计记录（action 为登录/登出/chat/delete_conversation 等）。"""
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO audit_logs(user_id, username, action, detail, created_at) "
                "VALUES (?,?,?,?,?)",
                (user_id, username, action, detail, time.time()),
            )
            conn.commit()
        finally:
            conn.close()


def list_logs(limit: int = 100) -> list:
    """按时间倒序返回最近 limit 条审计记录。"""
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT id, user_id, username, action, detail, created_at "
                "FROM audit_logs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
    return [
        {"id": r[0], "user_id": r[1], "username": r[2], "action": r[3],
         "detail": r[4], "created_at": r[5]}
        for r in rows
    ]
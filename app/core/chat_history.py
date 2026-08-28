"""会话历史持久化：SQLite（Python 标准库 sqlite3，零外部依赖）。

支持多会话管理：每个会话有独立 ID 与标题，
可新建 / 列表 / 删除 / 恢复最近 N 轮上下文。
存储于 outputs/chat_history.db。
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import List, Optional

from app.config import OUTPUT_DIR

_DB_PATH: Path = OUTPUT_DIR / "chat_history.db"
_LOCK = threading.Lock()
DEFAULT_TITLE = "新对话"
_TITLE_MAX = 12


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    # 多会话结构：conversations（会话）+ messages（消息）
    conn.execute(
        "CREATE TABLE IF NOT EXISTS conversations ("
        "id TEXT PRIMARY KEY,"
        "title TEXT NOT NULL,"
        "created_at REAL NOT NULL,"
        "updated_at REAL NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS messages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "conversation_id TEXT NOT NULL,"
        "role TEXT NOT NULL,"
        "content TEXT NOT NULL,"
        "created_at REAL NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_conv "
        "ON messages(conversation_id, id)"
    )
    # 兼容旧表（早期单会话版 chat_history），迁入新结构
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """旧版只有 chat_history 表时，迁移为 conversations + messages。"""
    has_old = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_history'"
    ).fetchone()
    has_new = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages'"
    ).fetchone()
    if has_new or not has_old:
        return
    conn.execute("ALTER TABLE chat_history RENAME TO messages")
    old_cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()]
    if "session_id" in old_cols and "conversation_id" not in old_cols:
        conn.execute("ALTER TABLE messages RENAME COLUMN session_id TO conversation_id")
    rows = conn.execute(
        "SELECT DISTINCT conversation_id FROM messages"
    ).fetchall()
    for (cid,) in rows:
        conn.execute(
            "INSERT OR IGNORE INTO conversations(id, title, created_at, updated_at) "
            "VALUES (?,?,?,?)",
            (cid, DEFAULT_TITLE, time.time(), time.time()),
        )


def _title_from(question: str) -> str:
    q = (question or "").replace("\n", " ").strip()
    return q if len(q) <= _TITLE_MAX else q[:_TITLE_MAX] + "…"


def create_conversation() -> str:
    """新建会话，返回会话 ID。"""
    cid = "s_" + uuid.uuid4().hex[:12]
    now = time.time()
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO conversations(id, title, created_at, updated_at) "
                "VALUES (?,?,?,?)",
                (cid, DEFAULT_TITLE, now, now),
            )
            conn.commit()
        finally:
            conn.close()
    return cid


def list_conversations() -> List[dict]:
    """会话列表（按最近更新倒序），含标题、时间、消息数。"""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT c.id, c.title, c.created_at, c.updated_at, "
                "       (SELECT COUNT(*) FROM messages m "
                "         WHERE m.conversation_id = c.id) AS msg_count "
                "FROM conversations c ORDER BY c.updated_at DESC"
            ).fetchall()
        finally:
            conn.close()
    return [
        {"id": r[0], "title": r[1], "created_at": r[2],
         "updated_at": r[3], "msg_count": r[4]}
        for r in rows
    ]


def get_messages(conversation_id: str,
                 turns: Optional[int] = None) -> List[dict]:
    """返回某会话消息；turns 为 None 时返回全部（用于界面恢复），
    指定 turns 时仅返回最近 N 轮（用于 Agent 上下文）。"""
    if not conversation_id:
        return []
    with _LOCK:
        conn = _connect()
        try:
            if turns is not None:
                rows = conn.execute(
                    "SELECT role, content FROM ("
                    "SELECT id, role, content FROM messages "
                    "WHERE conversation_id=? ORDER BY id DESC LIMIT ?"
                    ") ORDER BY id ASC",
                    (conversation_id, turns * 2),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT role, content FROM messages "
                    "WHERE conversation_id=? ORDER BY id ASC",
                    (conversation_id,),
                ).fetchall()
        finally:
            conn.close()
    return [{"role": role, "content": content} for role, content in rows]


def append(conversation_id: str, role: str, content: str) -> None:
    """追加一条消息；首条用户消息自动设为会话标题。"""
    if not conversation_id or not content:
        return
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO messages(conversation_id, role, content, created_at) "
                "VALUES (?,?,?,?)",
                (conversation_id, role, content, time.time()),
            )
            conn.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?",
                (time.time(), conversation_id),
            )
            # 首条用户消息自动设为会话标题
            if role == "user":
                cnt = conn.execute(
                    "SELECT COUNT(*) FROM messages "
                    "WHERE conversation_id=? AND role='user'",
                    (conversation_id,),
                ).fetchone()[0]
                if cnt == 1:
                    conn.execute(
                        "UPDATE conversations SET title=? WHERE id=? AND title=?",
                        (_title_from(content), conversation_id, DEFAULT_TITLE),
                    )
            conn.commit()
        finally:
            conn.close()


def delete_conversation(conversation_id: str) -> None:
    """删除会话及其全部消息。"""
    if not conversation_id:
        return
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
            conn.execute(
                "DELETE FROM conversations WHERE id=?", (conversation_id,))
            conn.commit()
        finally:
            conn.close()
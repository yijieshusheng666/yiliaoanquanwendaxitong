"""反馈闭环：点踩问题进入争议队列，管理员审核并可将纠错知识回流知识库。

存储 SQLite（outputs/review.db）：
- 同一问题的重复点踩去重合并（count 累加），避免队列被刷屏；
- 状态流转：pending -> resolved / ignored。

回流（reflow）由 admin_routes 处理：审核为 resolved 时若提供了目标药品与补充内容，
将追加为【人工审核补充】章节到对应文档，重建索引后进入检索。
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Dict, List

from app.config import OUTPUT_DIR

_db_path = OUTPUT_DIR / "review.db"
_lock = threading.Lock()

STATUS_PENDING = "pending"
STATUS_RESOLVED = "resolved"
STATUS_IGNORED = "ignored"

_COLS = ("id, question, answer, session_id, user_id, count, status, "
         "note, reviewed_by, created_at, reviewed_at")
_KEYS = ["id", "question", "answer", "session_id", "user_id", "count",
         "status", "note", "reviewed_by", "created_at", "reviewed_at"]


def _connect() -> sqlite3.Connection:
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS review_items ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "question TEXT NOT NULL,"
        "answer TEXT NOT NULL,"
        "session_id TEXT,"
        "user_id TEXT,"
        "count INTEGER NOT NULL DEFAULT 1,"
        "status TEXT NOT NULL DEFAULT 'pending',"
        "note TEXT,"
        "reviewed_by TEXT,"
        "created_at REAL NOT NULL,"
        "reviewed_at REAL)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_review_status ON review_items(status)")
    conn.commit()
    return conn


def _row(r) -> Dict:
    return dict(zip(_KEYS, r))


def enqueue(question: str, answer: str, session_id: str = "",
            user_id: str = "") -> int:
    """点踩时入队；同一问题已有 pending 记录则累加 count 并复用（去重）。"""
    question = (question or "").strip()[:500]
    answer = (answer or "").strip()[:2000]
    if not question:
        return -1
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id FROM review_items WHERE question=? AND status=? LIMIT 1",
                (question, STATUS_PENDING)).fetchone()
            if row:
                conn.execute(
                    "UPDATE review_items SET count = count + 1, created_at=? WHERE id=?",
                    (time.time(), row[0]))
                conn.commit()
                return row[0]
            cur = conn.execute(
                "INSERT INTO review_items"
                "(question, answer, session_id, user_id, created_at) "
                "VALUES (?,?,?,?,?)",
                (question, answer, session_id, user_id, time.time()))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()


def list_reviews(status: str = "") -> List[Dict]:
    with _lock:
        conn = _connect()
        try:
            if status in (STATUS_PENDING, STATUS_RESOLVED, STATUS_IGNORED):
                rows = conn.execute(
                    f"SELECT {_COLS} FROM review_items WHERE status=? ORDER BY id DESC",
                    (status,)).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {_COLS} FROM review_items ORDER BY id DESC").fetchall()
        finally:
            conn.close()
    return [_row(r) for r in rows]


def summary() -> Dict:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM review_items GROUP BY status").fetchall()
        finally:
            conn.close()
    d = {s: 0 for s in (STATUS_PENDING, STATUS_RESOLVED, STATUS_IGNORED)}
    for status, n in rows:
        if status in d:
            d[status] = n
    d["total"] = sum(d.values())
    return d


def resolve(review_id: int, status: str, note: str = "",
            reviewed_by: str = "") -> bool:
    """把审核项置为 resolved / ignored；返回是否命中记录。"""
    if status not in (STATUS_RESOLVED, STATUS_IGNORED):
        return False
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "UPDATE review_items SET status=?, note=?, reviewed_by=?, reviewed_at=? "
                "WHERE id=?",
                (status, note, reviewed_by, time.time(), review_id))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
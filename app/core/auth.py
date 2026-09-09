"""用户体系：注册 / 登录 / 会话令牌（SQLite 标准库实现，零外部依赖）。

安全设计
--------
- 密码不存明文：PBKDF2-HMAC-SHA256（随机盐 16B + 20 万次迭代），
  存储格式 ``pbkdf2$sha256$<iter>$<salt_hex>$<hash_hex>``；
- 令牌为 secrets.token_urlsafe(32)，数据库只存其 SHA-256 摘要，
  即使 DB 泄露也不能直接冒用；过期自动失效（默认 7 天）；
- 口令比对使用 hmac.compare_digest（常量时间，防时序侧信道）；
- 与既有会话库共用 chat_history.db：users / auth_tokens 两张新表
  幂等建表，不影响 conversations / messages。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from typing import Dict, Optional

from app.config import OUTPUT_DIR

DB_PATH = OUTPUT_DIR / "chat_history.db"
_LOCK = threading.Lock()
TOKEN_TTL_DAYS = 7
_PBKDF2_ITER = 200_000
_SALT_BYTES = 16


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "username TEXT NOT NULL UNIQUE,"
        "password_hash TEXT NOT NULL,"
        "created_at REAL NOT NULL,"
        "is_active INTEGER NOT NULL DEFAULT 1)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS auth_tokens ("
        "token_hash TEXT PRIMARY KEY,"
        "user_id INTEGER NOT NULL,"
        "expires_at REAL NOT NULL,"
        "created_at REAL NOT NULL)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tokens_user ON auth_tokens(user_id)"
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------
# 密码哈希
# ---------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 salt, _PBKDF2_ITER)
    return (f"pbkdf2$sha256${_PBKDF2_ITER}$"
            f"{salt.hex()}${digest.hex()}")


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, _, iter_s, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2" or iter_s != str(_PBKDF2_ITER):
            raise ValueError
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 salt, _PBKDF2_ITER)
    return hmac.compare_digest(actual, expected)


# ---------------------------------------------------------------
# 用户 CRUD
# ---------------------------------------------------------------
def register(username: str, password: str) -> Optional[Dict]:
    """注册新用户，成功返回用户 dict；用户名冲突/参数非法返回 None。"""
    username = (username or "").strip()
    if not (3 <= len(username) <= 32):
        return None
    if not password or len(password) < 6:
        return None
    with _LOCK:
        conn = _connect()
        try:
            exists = conn.execute(
                "SELECT 1 FROM users WHERE username=?", (username,)).fetchone()
            if exists:
                return None
            now = time.time()
            cur = conn.execute(
                "INSERT INTO users(username, password_hash, created_at, is_active) "
                "VALUES (?,?,?,1)",
                (username, hash_password(password), now))
            conn.commit()
            return {"id": cur.lastrowid, "username": username,
                    "created_at": now}
        finally:
            conn.close()


def authenticate(username: str, password: str) -> Optional[Dict]:
    """校验用户名密码；成功返回用户 dict，失败返回 None。"""
    username = (username or "").strip()
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id, username, password_hash, created_at, is_active "
                "FROM users WHERE username=?", (username,)).fetchone()
        finally:
            conn.close()
    if not row or not row[4]:
        return None
    if not verify_password(password, row[2]):
        return None
    return {"id": row[0], "username": row[1], "created_at": row[3]}


# ---------------------------------------------------------------
# 会话令牌
# ---------------------------------------------------------------
def create_token(user_id: int) -> Optional[str]:
    """签发令牌并落库（只存摘要），返回明文 token 交给客户端；失败返回 None。"""
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = time.time()
    with _LOCK:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO auth_tokens(token_hash, user_id, expires_at, created_at) "
                "VALUES (?,?,?,?)",
                (token_hash, user_id, now + TOKEN_TTL_DAYS * 86400, now))
            conn.commit()
        except sqlite3.IntegrityError:
            return None
        finally:
            conn.close()
    return token


def get_user_by_token(token: str) -> Optional[Dict]:
    """按明文 token 解析用户；无效/过期/被吊销返回 None。"""
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = time.time()
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT t.user_id, t.expires_at, u.username, u.created_at, "
                "       u.is_active, u.id "
                "FROM auth_tokens t JOIN users u ON u.id = t.user_id "
                "WHERE t.token_hash=?", (token_hash,)).fetchone()
            if row and row[1] > now and row[4]:
                user = {"id": row[0], "username": row[2],
                        "created_at": row[3]}
            else:
                user = None
        finally:
            conn.close()
    return user


def revoke_token(token: str) -> bool:
    """登出：删除令牌记录。"""
    if not token:
        return False
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.execute(
                "DELETE FROM auth_tokens WHERE token_hash=?", (token_hash,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
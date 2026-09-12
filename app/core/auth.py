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
- 角色（RBAC）：user=普通用户 / admin=管理员（可访问审计与用户管理接口）。
  注册时若库中尚不存在 admin，则用户名 ``admin`` 自动成为管理员（引导策略）。
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

# 角色常量
ROLE_USER = "user"
ROLE_ADMIN = "admin"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "username TEXT NOT NULL UNIQUE,"
        "password_hash TEXT NOT NULL,"
        "created_at REAL NOT NULL,"
        "is_active INTEGER NOT NULL DEFAULT 1,"
        "role TEXT NOT NULL DEFAULT 'user')"
    )
    _ensure_role_column(conn)
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


def _ensure_role_column(conn: sqlite3.Connection) -> None:
    """旧库 users 表无 role 列时补充（幂等），不破坏既有账号。"""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    if "role" not in cols:
        conn.execute(
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")


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
    """注册新用户，成功返回用户 dict；用户名冲突/参数非法返回 None。

    引导策略：库中尚无 admin 且用户名为 ``admin`` 时，自动授予管理员角色。
    """
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
            has_admin = conn.execute(
                "SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone()
            role = ROLE_ADMIN if (username == "admin" and not has_admin) else ROLE_USER
            now = time.time()
            cur = conn.execute(
                "INSERT INTO users(username, password_hash, created_at, is_active, role) "
                "VALUES (?,?,?,1,?)",
                (username, hash_password(password), now, role))
            conn.commit()
            return {"id": cur.lastrowid, "username": username,
                    "created_at": now, "role": role}
        finally:
            conn.close()


def authenticate(username: str, password: str) -> Optional[Dict]:
    """校验用户名密码；成功返回用户 dict（含 role），失败返回 None。"""
    username = (username or "").strip()
    with _LOCK:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id, username, password_hash, created_at, is_active, role "
                "FROM users WHERE username=?", (username,)).fetchone()
        finally:
            conn.close()
    if not row or not row[4]:
        return None
    if not verify_password(password, row[2]):
        return None
    return {"id": row[0], "username": row[1], "created_at": row[3],
            "role": row[5]}


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
                "       u.is_active, u.id, u.role "
                "FROM auth_tokens t JOIN users u ON u.id = t.user_id "
                "WHERE t.token_hash=?", (token_hash,)).fetchone()
            if row and row[1] > now and row[4]:
                user = {"id": row[0], "username": row[2],
                        "created_at": row[3], "role": row[6]}
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


def list_users() -> list:
    """返回全部用户（供管理员用户列表）。"""
    with _LOCK:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT id, username, created_at, is_active, role "
                "FROM users ORDER BY id").fetchall()
        finally:
            conn.close()
    return [
        {"id": r[0], "username": r[1], "created_at": r[2],
         "is_active": bool(r[3]), "role": r[4]}
        for r in rows
    ]
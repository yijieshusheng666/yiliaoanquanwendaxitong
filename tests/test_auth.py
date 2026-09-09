"""用户体系测试：注册 / 登录 / 令牌鉴权 / 会话隔离 / 越权拦截。

沿用既有测试约定：sys.path 注入 + tmp_path 隔离数据库，
auth 与 chat_history 指向同一个临时库文件（与真实部署一致）。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.core.auth as auth  # noqa: E402
import app.core.chat_history as ch  # noqa: E402


@pytest.fixture()
def db_factory(tmp_path, monkeypatch):
    """auth 与 chat_history 共用临时数据库，避免污染线上 chat_history.db。"""
    tmp_db = tmp_path / "t.db"
    monkeypatch.setattr(auth, "DB_PATH", tmp_db)
    monkeypatch.setattr(ch, "_DB_PATH", tmp_db)
    yield


# ---------------------------------------------------------------
# 注册 / 登录
# ---------------------------------------------------------------
def test_register_and_login(db_factory):
    u = auth.register("alice", "secret123")
    assert u and u["username"] == "alice" and u["id"] >= 1
    # 密码明文绝不落库
    conn = auth._connect()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username='alice'").fetchone()
    finally:
        conn.close()
    assert row and "secret123" not in row[0]
    assert row[0].startswith("pbkdf2$sha256$")

    # 错误密码登录失败，正确密码成功
    assert auth.authenticate("alice", "wrong") is None
    got = auth.authenticate("alice", "secret123")
    assert got and got["id"] == u["id"]


def test_register_validation(db_factory):
    # 用户名过短 / 过长 / 重名
    assert auth.register("ab", "abcdef") is None
    assert auth.register("x" * 33, "abcdef") is None
    assert auth.register("alice", "abcdef") is not None
    assert auth.register("alice", "other1") is None
    # 密码过短 / 为空
    assert auth.register("bob", "12345") is None
    assert auth.register("bob", "") is None
    # 空白用户名 trim
    assert auth.register("  carol  ", "abcdef") is not None
    assert auth.authenticate("carol", "abcdef") is not None


# ---------------------------------------------------------------
# 令牌
# ---------------------------------------------------------------
def test_token_lifecycle(db_factory):
    u = auth.register("alice", "secret123")
    tok = auth.create_token(u["id"])
    assert tok and len(tok) >= 32
    # 库里只存摘要，不存明文令牌
    conn = auth._connect()
    try:
        rows = conn.execute("SELECT token_hash FROM auth_tokens").fetchall()
    finally:
        conn.close()
    assert tok not in [r[0] for r in rows]
    assert len(rows) == 1

    me = auth.get_user_by_token(tok)
    assert me and me["username"] == "alice"
    assert auth.get_user_by_token("bogus") is None
    assert auth.get_user_by_token("") is None

    assert auth.revoke_token(tok) is True
    assert auth.get_user_by_token(tok) is None
    # 登出幂等
    assert auth.revoke_token(tok) is False


def test_inactive_user_rejected(db_factory):
    u = auth.register("alice", "secret123")
    tok = auth.create_token(u["id"])
    conn = auth._connect()
    try:
        conn.execute("UPDATE users SET is_active=0 WHERE id=?", (u["id"],))
        conn.commit()
    finally:
        conn.close()
    assert auth.authenticate("alice", "secret123") is None
    assert auth.get_user_by_token(tok) is None


# ---------------------------------------------------------------
# 会话隔离
# ---------------------------------------------------------------
def test_conversation_isolation(db_factory):
    u1 = auth.register("alice", "secret123")
    u2 = auth.register("bob", "bobpass12")
    uid1, uid2 = str(u1["id"]), str(u2["id"])

    c1 = ch.create_conversation(user_id=uid1)
    c2 = ch.create_conversation(user_id=uid2)
    ch.append(c1, "user", "问题A")
    ch.append(c2, "user", "问题B")

    # 列表隔离
    ids1 = [c["id"] for c in ch.list_conversations(uid1)]
    ids2 = [c["id"] for c in ch.list_conversations(uid2)]
    assert c1 in ids1 and c2 not in ids1
    assert c2 in ids2 and c1 not in ids2

    # 归属识别
    assert ch.get_conversation_owner(c1) == uid1
    assert ch.get_conversation_owner(c2) == uid2
    assert ch.get_conversation_owner("s_nonexist") is None

    # 越权删除被拒绝，且会话仍存在
    assert ch.delete_conversation(c1, uid2) is False
    assert ch.get_conversation_owner(c1) == uid1
    # 本人删除成功
    assert ch.delete_conversation(c1, uid1) is True
    assert ch.get_conversation_owner(c1) is None


def test_guest_space_isolated_from_users(db_factory):
    u1 = auth.register("alice", "secret123")
    uid1 = str(u1["id"])
    guest_cid = ch.create_conversation(user_id=None)
    user_cid = ch.create_conversation(user_id=uid1)

    # 游客空间与用户空间互不可见
    guest_ids = [c["id"] for c in ch.list_conversations(None)]
    user_ids = [c["id"] for c in ch.list_conversations(uid1)]
    assert guest_cid in guest_ids and user_cid not in guest_ids
    assert user_cid in user_ids and guest_cid not in user_ids

    # 用户不能删除游客会话，游客也不能删除用户会话
    assert ch.delete_conversation(guest_cid, uid1) is False
    assert ch.delete_conversation(user_cid, None) is False
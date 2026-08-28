"""会话历史 SQLite 持久化测试（多会话管理）。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.core.chat_history as ch  # noqa: E402


@pytest.fixture()
def db_factory(tmp_path, monkeypatch):
    """用临时数据库隔离测试，避免污染 outputs/chat_history.db。"""
    monkeypatch.setattr(ch, "_DB_PATH", tmp_path / "t.db")
    yield


def test_create_list_delete(db_factory):
    cid = ch.create_conversation()
    assert cid.startswith("s_")
    convs = ch.list_conversations()
    assert convs[0]["id"] == cid
    assert convs[0]["title"] == ch.DEFAULT_TITLE
    assert convs[0]["msg_count"] == 0

    ch.delete_conversation(cid)
    assert ch.list_conversations() == []


def test_append_sets_title_from_first_question(db_factory):
    cid = ch.create_conversation()
    ch.append(cid, "user", "孕妇能喝藿香正气水吗？这个药安不安全")
    convs = ch.list_conversations()
    assert convs[0]["title"] == "孕妇能喝藿香正气水吗？这…"  # 12 字 + 省略号


def test_append_order_and_recent(db_factory):
    cid = ch.create_conversation()
    ch.append(cid, "user", "问题1")
    ch.append(cid, "assistant", "回答1")
    ch.append(cid, "user", "问题2")
    hist = ch.get_messages(cid, turns=10)
    assert [h["role"] for h in hist] == ["user", "assistant", "user"]
    assert hist[0]["content"] == "问题1"
    assert hist[-1]["content"] == "问题2"
    # turns=1 → 最近 1 轮（最近 2 条）：回答1 + 问题2
    hist1 = ch.get_messages(cid, turns=1)
    assert [h["content"] for h in hist1] == ["回答1", "问题2"]


def test_get_messages_none_returns_all(db_factory):
    cid = ch.create_conversation()
    for i in range(5):
        ch.append(cid, "user", f"q{i}")
        ch.append(cid, "assistant", f"a{i}")
    assert len(ch.get_messages(cid)) == 10


def test_delete_only_target_session(db_factory):
    a = ch.create_conversation()
    b = ch.create_conversation()
    ch.append(a, "user", "A 的问题")
    ch.append(b, "user", "B 的问题")
    ch.delete_conversation(a)
    assert len(ch.list_conversations()) == 1
    assert ch.get_messages(b) == [{"role": "user", "content": "B 的问题"}]


def test_sessions_isolated(db_factory):
    a = ch.create_conversation()
    b = ch.create_conversation()
    ch.append(a, "user", "A 的问题")
    ch.append(b, "user", "B 的问题")
    assert ch.get_messages(a) == [{"role": "user", "content": "A 的问题"}]
    assert ch.get_messages(b) == [{"role": "user", "content": "B 的问题"}]
    assert ch.get_messages("not-exist-1") == []
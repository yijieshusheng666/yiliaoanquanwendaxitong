"""反馈闭环核心逻辑单元测试：点踩去重入队 / 状态流转 / 备注与审核人 / 统计 / 边界。

直接依赖 app.core.review（仅 app.config + 标准库），无需嵌入模型与 fastapi。
测试用 tmp_path 隔离 SQLite，避免污染真实 outputs/review.db。
"""
import pytest

from app.core import review


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "_db_path", tmp_path / "review.db")
    return review


def test_enqueue_dedup(db):
    q = "布洛芬和阿司匹林能一起吃吗？"
    r1 = db.enqueue(q, "可以一起吃，但需谨慎。")
    r2 = db.enqueue(q, "可以一起吃，但需谨慎。")
    assert r1 == r2 > 0
    items = db.list_reviews("pending")
    assert len(items) == 1
    assert items[0]["count"] == 2


def test_enqueue_empty_rejected(db):
    assert db.enqueue("", "x") == -1
    assert db.enqueue("   ", "x") == -1


def test_distinct_questions(db):
    r1 = db.enqueue("阿莫西林过敏能吃头孢吗", "评估过敏史")
    r2 = db.enqueue("布洛芬过量怎么办", "立即就医")
    assert r1 != r2 and r1 > 0 and r2 > 0


def test_summary(db):
    db.enqueue("问题一", "答一")
    db.enqueue("问题二", "答二")
    db.enqueue("问题一", "答一")  # 去重复用，不新增 pending
    assert db.summary() == {"pending": 2, "resolved": 0, "ignored": 0, "total": 2}


def test_resolve_sets_status_and_meta(db):
    rid = db.enqueue("问题A", "答A")
    assert db.resolve(rid, "resolved", note="已回流", reviewed_by="admin")
    items = db.list_reviews("resolved")
    assert len(items) == 1
    assert items[0]["note"] == "已回流"
    assert items[0]["reviewed_by"] == "admin"
    assert items[0]["reviewed_at"] is not None


def test_resolve_rejects_invalid(db):
    rid = db.enqueue("问题B", "答B")
    assert db.resolve(rid, "pending") is False      # 非法状态
    assert db.resolve(999999, "resolved") is False  # 不存在记录
    assert db.summary()["pending"] == 1
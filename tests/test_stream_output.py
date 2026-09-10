"""流式输出契约测试：免责声明必须随 token 流出，且回答必须落盘。

回归两类缺陷：
1. 在线 RAG 路径把免责声明只拼进 done.answer，而前端渲染与 SSE 落盘都只消费
   token 事件 —— 界面与历史里都看不到免责声明；
2. SSE 落盘只累加 token，急症护栏回复（emergency 事件）内容为空 → 不落盘，
   用户刷新后只剩提问、没有「拨打 120」。
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.api.server as server  # noqa: E402
import app.core.llm_provider as llm_provider  # noqa: E402
from app.config import DISCLAIMER  # noqa: E402
from app.core.service import _rag_stream  # noqa: E402


class _FakeChunk:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    async def astream(self, _prompt):
        for piece in ["布洛芬", "和阿司匹林", "不建议同服。"]:
            yield _FakeChunk(piece)


class _FakeKB:
    def format_context(self, _docs):
        return "[1] 布洛芬缓释胶囊【药物相互作用】…"


class _FakeDoc:
    page_content = "布洛芬缓释胶囊【药物相互作用】…"
    metadata = {"drug": "布洛芬缓释胶囊", "section": "药物相互作用",
                "text": "两者同为NSAIDs，联用增加出血风险。"}


def test_rag_stream_emits_disclaimer_as_tokens(monkeypatch):
    monkeypatch.setattr(llm_provider, "get_llm", lambda: _FakeLLM())

    async def collect():
        tokens, done = "", None
        async for ev in _rag_stream("布洛芬和阿司匹林能一起吃吗？", None,
                                    _FakeKB(), [_FakeDoc()]):
            if ev["type"] == "token":
                tokens += ev["content"]
            elif ev["type"] == "done":
                done = ev
        return tokens, done

    tokens, done = asyncio.run(collect())
    assert "不建议同服" in tokens, "模型输出未随 token 流出"
    assert "免责声明" in tokens, "免责声明未随 token 流出（前端与落库都会丢）"
    assert tokens in done["answer"], "token 拼接结果应与 done.answer 一致"


def test_sse_persists_emergency_answer(monkeypatch):
    """急症路径不会产出 token，必须以 emergency 事件内容落盘。"""
    persisted = []
    monkeypatch.setattr(server, "append",
                        lambda sid, role, content: persisted.append((sid, role, content)))

    async def fake_stream(_q, _h):
        yield {"type": "emergency", "content": "请立即拨打 120", "keyword": "胸痛"}
        yield {"type": "done", "answer": "请立即拨打 120", "sources": [],
               "path": "guardrail", "mode": "guardrail"}

    monkeypatch.setattr(server, "answer_stream", fake_stream)

    async def drain():
        resp = server._sse("胸痛怎么办", [], "s_test")
        return [chunk async for chunk in resp.body_iterator]

    chunks = asyncio.run(drain())
    assert any("emergency" in c for c in chunks)
    assert persisted == [("s_test", "assistant", "请立即拨打 120")]


def test_sse_persists_streamed_answer_with_disclaimer(monkeypatch):
    persisted = []
    monkeypatch.setattr(server, "append",
                        lambda sid, role, content: persisted.append((sid, role, content)))

    async def fake_stream(_q, _h):
        yield {"type": "token", "content": "回答正文"}
        yield {"type": "token", "content": DISCLAIMER}
        yield {"type": "done", "answer": "回答正文" + DISCLAIMER, "sources": [],
               "path": "rag", "mode": "offline"}

    monkeypatch.setattr(server, "answer_stream", fake_stream)

    async def drain():
        resp = server._sse("q", [], "s_test")
        return [chunk async for chunk in resp.body_iterator]

    asyncio.run(drain())
    assert persisted == [("s_test", "assistant", "回答正文" + DISCLAIMER)]


def test_sse_does_not_persist_without_sid(monkeypatch):
    persisted = []
    monkeypatch.setattr(server, "append",
                        lambda sid, role, content: persisted.append((sid, role, content)))

    async def fake_stream(_q, _h):
        yield {"type": "token", "content": "游客回答"}
        yield {"type": "done", "answer": "游客回答", "sources": []}

    monkeypatch.setattr(server, "answer_stream", fake_stream)

    async def drain():
        resp = server._sse("q", [], "")
        return [chunk async for chunk in resp.body_iterator]

    asyncio.run(drain())
    assert persisted == [], "无会话 ID 时不应落盘"


@pytest.mark.parametrize("question", ["胸口剧痛伴窒息感，是不是心梗，需要立即做什么？"])
def test_emergency_question_not_sent_to_llm(question, monkeypatch):
    """急症问题必须走护栏，不得调用大模型（保持 100% 拦截语义）。"""
    from app.core.service import answer_stream
    calls = []

    def boom():
        calls.append(1)
        raise AssertionError("急症问题不得调用大模型")

    monkeypatch.setattr(llm_provider, "get_llm", boom)

    async def collect():
        return [ev async for ev in answer_stream(question)]

    events = asyncio.run(collect())
    assert calls == []
    assert any(ev["type"] == "emergency" for ev in events)
    assert events[-1]["path"] == "guardrail"

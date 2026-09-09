"""FastAPI 后端：SSE 流式问答 + Swagger 文档 + 反馈接口。

启动：uvicorn app.api.server:app --host 0.0.0.0 --port 8000
文档：http://localhost:8000/docs
"""
from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.config import HISTORY_TURNS, PDF_DIR
from app import __version__
from app.api.user_routes import get_optional_user, router as user_router
from app.core.chat_history import (append, create_conversation,
                                   delete_conversation, get_conversation_owner,
                                   get_messages, list_conversations)
from app.core.feedback import record_feedback, summary as feedback_summary
from app.core.interaction_db import get_interaction_db
from app.core.logging_setup import get_logger, setup_logging
from app.core.service import (_events_to_result, _sources_from_docs,
                              answer_stream, build_retrieval_qa)

logger = get_logger("med_safety.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动时确保数据与索引就绪（首次启动自动构建）。"""
    setup_logging()
    logger.info("医疗安全问答系统 API 启动中...")
    from app.core.index_versioning import resolve_index_dir
    if not (resolve_index_dir() / "chroma.sqlite3").exists():
        logger.info("检测到向量索引缺失，准备构建...")
        if not PDF_DIR.exists() or not list(PDF_DIR.glob("*/*.pdf")):
            logger.info("说明书 PDF 缺失，先生成数据...")
            from app.data.generate_data import main as gen_data
            gen_data()
        from app.core.retrieval import build_index
        build_index()
        logger.info("向量索引构建完成")
    yield


app = FastAPI(
    title="医疗安全问答系统 API",
    description=(
        "基于 RAG + Agent 架构的用药安全问答系统。\n\n"
        "安全护栏：检测到急症关键词（胸痛/昏迷/自杀等）时直接返回「拨打 120」固定提示。\n"
        "相互作用查询：识别「A 和 B 能一起吃吗」类问题，由 ReAct Agent 查询结构化 CSV 风险数据。\n"
        "每条回答自动附带免责声明。\n\n"
        "流式接口：POST /api/chat，stream=true 时以 SSE（text/event-stream）返回。"
    ),
    version=__version__,
    lifespan=lifespan,
)

app.include_router(user_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------
class ChatRequest(BaseModel):
    question: str
    history: List[dict] = []
    stream: bool = True
    session_id: str = ""  # 显式会话 ID；缺省时由 Cookie 中的 ms_sid 决定


class FeedbackRequest(BaseModel):
    question: str
    answer: str = ""
    rating: int  # 1 点赞 / -1 点踩
    session_id: str = ""


# ---------------------------------------------------------------
# 会话 ID：显式传参（前端从 localStorage 生成稳定 ID，刷新不变）
# 为空时不落盘历史，仅用请求自带的 history（兼容无会话的 curl 调用）
# ---------------------------------------------------------------
_SID_RE = re.compile(r"^[A-Za-z0-9_]{4,64}$")


def _valid_sid(sid: str) -> str:
    # 前端 localStorage 生成形如 s_xxxxx（字母+数字+下划线），仅放行安全字符
    return sid if sid and _SID_RE.match(sid) else ""


# ---------------------------------------------------------------
# SSE 工具
# ---------------------------------------------------------------
def _sse(question: str, history: List[dict], sid: str = ""):
    full_text = []

    async def gen():
        async for ev in answer_stream(question, history):
            if ev.get("type") == "token":
                full_text.append(ev["content"])
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        # 流式结束后落盘助手回复
        if sid:
            append(sid, "assistant", "".join(full_text))

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------------------------------------------------------
# 路由
# ---------------------------------------------------------------
@app.get("/")
async def root():
    return {"service": "医疗安全问答系统", "docs": "/docs", "health": "/api/health"}


@app.get("/api/health")
async def health():
    from app.core.retrieval import get_knowledge_base
    try:
        count = get_knowledge_base().count()
        return {"status": "ok", "vector_docs": count}
    except Exception as exc:
        return JSONResponse(status_code=503,
                            content={"status": "error", "detail": str(exc)})


@app.post("/api/chat")
async def chat(req: ChatRequest,
               user: Optional[dict] = Depends(get_optional_user)):
    """问答接口：stream=true 返回 SSE 事件流；stream=false 返回 JSON。

    会话历史以 SQLite 为准：请求前落盘用户问题，从库中取最近 N 轮上下文，
    回答完成后落盘助手回复；前端传入稳定的 session_id（localStorage 生成）即可跨刷新恢复。
    会话归属校验：会话必须属于当前登录用户（游客归属 NULL），否则 403。
    """
    question = req.question.strip()
    if not question:
        return JSONResponse(status_code=400, content={"detail": "question 不能为空"})

    uid = str(user["id"]) if user else None
    sid = _valid_sid(req.session_id)
    if sid:
        owner = get_conversation_owner(sid)
        if owner != uid:
            return JSONResponse(status_code=403,
                                content={"detail": "无权访问该会话"})
        history = get_messages(sid, turns=HISTORY_TURNS)
    else:
        history = req.history
    if sid:
        append(sid, "user", question)

    if req.stream:
        return _sse(question, history, sid)

    events = []
    async for ev in answer_stream(question, history):
        events.append(ev)
    answer = _events_to_result(events)
    if sid and isinstance(answer, dict):
        text = answer.get("answer") or "".join(
            ev.get("content", "") for ev in events if ev.get("type") == "token")
        if text:
            append(sid, "assistant", text)
    return answer


@app.get("/api/conversations")
async def conversations(user: Optional[dict] = Depends(get_optional_user)):
    """会话列表：仅返回当前登录用户（游客为公共空间）的会话。"""
    uid = str(user["id"]) if user else None
    return {"conversations": list_conversations(uid)}


@app.post("/api/conversations")
async def new_conversation(user: Optional[dict] = Depends(get_optional_user)):
    """新建会话（归属当前用户），返回会话 ID。"""
    uid = str(user["id"]) if user else None
    return {"session_id": create_conversation(uid)}


@app.delete("/api/conversations/{session_id}")
async def remove_conversation(session_id: str,
                              user: Optional[dict] = Depends(get_optional_user)):
    """删除指定会话；仅归属匹配时删除（越权返回 404）。"""
    uid = str(user["id"]) if user else None
    ok = delete_conversation(session_id, uid)
    if not ok:
        return JSONResponse(status_code=404,
                            content={"detail": "会话不存在或无权删除"})
    return {"ok": True}


@app.get("/api/history")
async def history(session_id: str = "", limit: int = 0,
                  user: Optional[dict] = Depends(get_optional_user)):
    """返回指定会话全部消息（供界面恢复；limit>0 时仅取最近 limit 轮）。
    仅允许读取归属本人的会话。"""
    sid = _valid_sid(session_id)
    if not sid:
        return {"session_id": "", "history": []}
    uid = str(user["id"]) if user else None
    if get_conversation_owner(sid) != uid:
        return JSONResponse(status_code=403,
                            content={"detail": "无权访问该会话"})
    turns = limit if limit > 0 else None
    return {"session_id": sid, "history": get_messages(sid, turns)}


@app.post("/api/feedback")
async def feedback(req: FeedbackRequest,
                   user: Optional[dict] = Depends(get_optional_user)):
    """记录用户点赞/点踩反馈到本地 JSON Lines 文件。"""
    uid = str(user["id"]) if user else None
    item = record_feedback(req.question, req.answer, req.rating,
                           session_id=req.session_id, source="web",
                           user_id=uid or "")
    return {"ok": True, "record": item}


@app.get("/api/stats")
async def stats():
    """系统统计：文档数、反馈汇总、模式。"""
    from app.config import ONLINE_MODE
    from app.core.retrieval import get_knowledge_base
    try:
        doc_count = get_knowledge_base().count()
    except Exception:
        doc_count = 0
    return {
        "vector_docs": doc_count,
        "interaction_pairs": len(get_interaction_db().rows),
        "feedback": feedback_summary(),
        "mode": "online" if ONLINE_MODE else "offline",
    }


@app.get("/api/drugs")
async def drugs(q: str = ""):
    """药品名列表（支持前缀过滤），供前端展示与交互查询使用。"""
    names = get_interaction_db().all_names()
    if q:
        names = [n for n in names if q in n]
    return {"drugs": names[:200], "total": len(names)}


# RetrievalQA 非流式路径（Swagger 中可直接体验）
@app.get("/api/qa")
async def qa_retrieval(question: str):
    """非流式 RetrievalQA 演示接口（需在线模式）。"""
    if not question.strip():
        return JSONResponse(status_code=400, content={"detail": "question 不能为空"})
    from app.config import ONLINE_MODE
    if not ONLINE_MODE:
        return JSONResponse(status_code=400, content={
            "detail": "当前为离线模式，请配置 LLM_API_KEY 后使用本接口；"
                      "离线演示请使用 POST /api/chat"})
    qa = build_retrieval_qa()
    result = await qa.ainvoke({"query": question.strip()})
    return {"answer": result.get("result", ""),
            "sources": _sources_from_docs(result.get("source_documents", []))}


if __name__ == "__main__":
    import uvicorn
    from app.config import API_PORT
    uvicorn.run("app.api.server:app", host="0.0.0.0", port=API_PORT, reload=False)

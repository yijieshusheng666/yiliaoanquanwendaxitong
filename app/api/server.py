"""FastAPI 后端：SSE 流式问答 + Swagger 文档 + 反馈接口。

启动：uvicorn app.api.server:app --host 0.0.0.0 --port 8000
文档：http://localhost:8000/docs
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.config import CHROMA_DIR, PDF_DIR
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
    if not (CHROMA_DIR / "chroma.sqlite3").exists():
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
    version="1.0.0",
    lifespan=lifespan,
)

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


class FeedbackRequest(BaseModel):
    question: str
    answer: str = ""
    rating: int  # 1 点赞 / -1 点踩
    session_id: str = ""


# ---------------------------------------------------------------
# SSE 工具
# ---------------------------------------------------------------
def _sse(question: str, history: List[dict]):
    async def gen():
        async for ev in answer_stream(question, history):
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
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
async def chat(req: ChatRequest):
    """问答接口：stream=true 返回 SSE 事件流；stream=false 返回 JSON。"""
    if not req.question.strip():
        return JSONResponse(status_code=400, content={"detail": "question 不能为空"})
    if req.stream:
        return _sse(req.question.strip(), req.history)
    events = []
    async for ev in answer_stream(req.question.strip(), req.history):
        events.append(ev)
    return _events_to_result(events)


@app.post("/api/feedback")
async def feedback(req: FeedbackRequest):
    """记录用户点赞/点踩反馈到本地 JSON Lines 文件。"""
    item = record_feedback(req.question, req.answer, req.rating,
                           session_id=req.session_id, source="web")
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
    uvicorn.run("app.api.server:app", host="0.0.0.0", port=8000, reload=False)

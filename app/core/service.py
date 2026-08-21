"""核心问答编排服务。

流程（Streaming）：
1. 急症护栏：命中急症关键词 -> 固定「拨打 120」提示，不调用任何生成。
2. 问题分类：规则识别「A 和 B 能一起吃吗」类相互作用问题。
3. 相互作用问题 -> ReAct Agent（create_react_agent）：
   工具① query_drug_interaction（CSV 风险等级）② retrieve_drug_knowledge（说明书检索）。
4. 其他问题 -> RAG（RetrievalQA / llm.astream），回答带 [n] 引用编号。
5. 全部回答末尾追加免责声明；在线模式调用国内大模型，离线模式走确定性模板。

事件协议：{"type": start|token|sources|done|emergency|error, ...}
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import AsyncGenerator, List, Optional

from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain.tools import StructuredTool

from app.config import (DISCLAIMER, EMERGENCY_RESPONSE, HISTORY_TURNS,
                        ONLINE_MODE, TOP_K)
from app.core.guardrails import check_emergency
from app.core.interaction_db import get_interaction_db, risk_text
from app.core.logging_setup import get_logger
from app.core.offline import offline_answer
from app.core.retrieval import get_knowledge_base

logger = get_logger("med_safety.service")

# ---------------------------------------------------------------
# 提示词模板
# ---------------------------------------------------------------
RAG_TEMPLATE = """你是一名专业、谨慎的社区药师。请严格依据下列【资料】回答用户的用药问题。

要求：
1. 只依据【资料】作答，禁止编造；资料不足时明确说明「现有资料中未找到相关信息」。
2. 全面整合【资料】中的所有来源（药品说明书、处方集、临床应用指南、本草纲目等），各来源平等对待，不分优先级、不偏重任何一本书。
3. 若问题涉及疾病或症状的治疗，必须把【资料】中出现的**所有**推荐治疗药物完整列出，逐一给出：药名、适用情形、用法用量或注意事项；不得遗漏、不得只挑选其中几种。
4. 每个关键结论后必须标注引用编号，格式为英文方括号内单个数字，如 [1]；多条结论分别标注 [2] 等，编号对应【资料】条目序号。禁止使用 [n]、[1, 2, 3] 等其它格式。
5. 涉及能否同服等相互作用问题时，结论需明确「能 / 不能 / 慎用」，并给出原因与安全建议。
6. 回答分点、条理清晰，使用中文。

【资料】
{context}

【对话历史】
{history}

【问题】
{question}
"""

# RetrievalQA 专用模板（stuff 链要求 context/question 两个变量，即 RAG_TEMPLATE 去掉对话历史）
QA_TEMPLATE = RAG_TEMPLATE.replace(
    "\n\n【对话历史】\n{history}", "")

REACT_TEMPLATE = """你是一名专业、谨慎的社区药师，通过调用工具查询资料来回答用户的用药问题。你只能使用以下工具：

{tools}

必须严格按如下格式逐步操作：
Question: 用户的输入
Thought: 你打算怎么做
Action: 工具名称，取自 [{tool_names}]
Action Input: 传给工具的输入
Observation: 工具返回的结果
（可重复 Thought / Action / Action Input / Observation 步骤）
Thought: 我已经获得足够信息
Final Answer: 面向用户的最终回答。Final Answer 中须包含明确结论（能/不能/慎用）、原因与安全建议，
并综合全部查询到的资料来源（平等对待，不分优先级），把资料中所有可选的治疗/替代药物方案完整列出，
在关键结论后标注引用编号 [n]（n 对应你观察到的资料条目编号）。

对话历史：
{history}

Question: {input}
{agent_scratchpad}"""

INTERACTION_RE = re.compile(r"(和|与|跟|同).{0,12}(一起|同时|同服|同用|同吃)?.{0,4}(吃|服用|用|用药|使用|服)")


# ---------------------------------------------------------------
# 问题分类
# ---------------------------------------------------------------
def classify_interaction(question: str, history: Optional[List[dict]] = None):
    """规则识别「A 和 B 能一起吃吗」类问题。返回 (is_interaction, drugs)。"""
    text = question
    if history:
        last = [h for h in history if h.get("role") == "user"]
        if last:
            text = last[-1]["content"] + " " + question
    db = get_interaction_db()
    drugs = db.find_drugs(text)
    if len(drugs) >= 2 and INTERACTION_RE.search(text):
        return True, drugs[:2]
    return False, []


def format_history(history: Optional[List[dict]]) -> str:
    if not history:
        return "（无）"
    lines = []
    for item in history[-HISTORY_TURNS * 2:]:
        role = item.get("role", "user")
        label = "用户" if role == "user" else "药师"
        lines.append(f"{label}：{item.get('content', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------
# 在线 RAG 路径（llm.astream 流式 + 编号引用）
# ---------------------------------------------------------------
async def _yield_tokens(answer: str):
    """按句切分回答并逐个 token 事件流式推送。"""
    for part in re.split(r"(?<=。)", answer):
        if part.strip():
            yield {"type": "token", "content": part}
            await asyncio.sleep(0.01)


async def _rag_stream(question, history, kb, docs):
    context = kb.format_context(docs)
    prompt = RAG_TEMPLATE.format(
        context=context, history=format_history(history), question=question)
    from app.core.llm_provider import get_llm
    llm = get_llm()
    answer = ""
    async for chunk in llm.astream(prompt):
        tok = chunk.content or ""
        if tok:
            answer += tok
            yield {"type": "token", "content": tok}
    answer += DISCLAIMER
    sources = _sources_from_docs(docs)
    yield {"type": "sources", "sources": sources}
    yield {"type": "done", "answer": answer, "sources": sources,
           "path": "rag", "mode": "online"}


# ---------------------------------------------------------------
# 相互作用工具（ReAct Agent 使用）
# ---------------------------------------------------------------
def _tool_lookup(query: str) -> str:
    db = get_interaction_db()
    drugs = db.find_drugs(query)
    if len(drugs) >= 2:
        hits = db.lookup_many(drugs[:2])
        if hits:
            parts = []
            for i, r in enumerate(hits[:2], 1):
                parts.append(
                    f"[{i}] {r['drug_a']} 与 {r['drug_b']}：风险等级={r['risk_level']}（{risk_text(r['risk_level'])}）。"
                    f"说明：{r['description']}")
            return "\n".join(parts)
    return "未找到相关药物相互作用记录，请确认药品名称是否正确。"


def _tool_retrieve(query: str) -> str:
    return get_knowledge_base().format_tool_search(query, k=3)


def _build_agent_tools():
    return [
        StructuredTool.from_function(
            func=_tool_lookup,
            name="query_drug_interaction",
            description="当用户询问两种药物能否同服/一起服用/同时使用时调用，参数为包含两种药品名的文本，返回风险等级与说明。",
        ),
        StructuredTool.from_function(
            func=_tool_retrieve,
            name="retrieve_drug_knowledge",
            description="检索药品说明书知识库，参数为用药问题文本，返回带【来源:药品名·章节】标注的相关说明书条目。",
        ),
    ]


def _sources_from_tool_output(observation: str) -> List[dict]:
    """从检索工具输出中解析来源（格式：[n] 来源:药品·章节 内容）。"""
    sources = []
    for line in str(observation).splitlines():
        m = re.match(r"\[(\d+)\]\s*来源:([^·]+?)·([^\s]+)\s*(.*)", line.strip())
        if m:
            sources.append({"drug": m.group(2), "section": m.group(3),
                            "text": m.group(4).strip()})
    return sources


def _sources_from_interaction_output(observation: str) -> List[dict]:
    """从相互作用查询工具输出中解析来源（格式：[n] 药品A 与 药品B：风险等级=…）。"""
    sources = []
    for line in str(observation).splitlines():
        m = re.match(r"\[(\d+)\]\s*(.+?)\s*与\s*(.+?)：风险等级=(.+?)（(.*?)）。(.*)", line.strip())
        if m:
            sources.append({"drug": f"{m.group(2)} / {m.group(3)}",
                            "section": "药物相互作用数据库",
                            "text": f"风险等级：{m.group(4)}（{m.group(5)}）。{m.group(6)}"})
    return sources


async def _agent_stream(question, history, kb, docs):
    """ReAct Agent 路径：调用工具查询相互作用/说明书，流式返回最终回答。

    说明：Agent 内部存在多轮 Thought/Action 推理，若逐 token 转发会把中间推理
    混入回答，因此这里直接取 AgentExecutor 的最终输出 output 并按句分块流式推送。
    """
    from app.core.llm_provider import get_llm
    llm = get_llm()
    tools = _build_agent_tools()
    prompt = PromptTemplate.from_template(REACT_TEMPLATE)
    agent = create_react_agent(llm, tools, prompt)
    executor = AgentExecutor(agent=agent, tools=tools, max_iterations=4,
                             handle_parsing_errors=True,
                             return_intermediate_steps=True)
    try:
        result = await executor.ainvoke(
            {"input": question, "history": format_history(history)})
    except Exception as exc:
        logger.exception("Agent 执行失败")
        answer = f"抱歉，Agent 执行出错：{exc}"
        yield {"type": "done", "answer": answer, "sources": [],
               "path": "agent", "mode": "online"}
        return

    answer = result.get("output", "")
    sources = []
    for _action, observation in result.get("intermediate_steps", []):
        if _action.tool == "retrieve_drug_knowledge":
            sources.extend(_sources_from_tool_output(observation))
        elif _action.tool == "query_drug_interaction":
            sources.extend(_sources_from_interaction_output(observation))
    answer += DISCLAIMER
    async for ev in _yield_tokens(answer):
        yield ev
    yield {"type": "sources", "sources": sources}
    yield {"type": "done", "answer": answer, "sources": sources,
           "path": "agent", "mode": "online"}


# ---------------------------------------------------------------
# 离线路径（确定性模板，用于演示与评测）
# ---------------------------------------------------------------
async def _offline_stream(question, docs, hits, is_interaction):
    answer, sources = offline_answer(question, docs, hits, is_interaction)
    async for ev in _yield_tokens(answer):
        yield ev
    yield {"type": "sources", "sources": sources}
    yield {"type": "done", "answer": answer, "sources": sources,
           "path": "agent" if is_interaction else "rag", "mode": "offline"}


# ---------------------------------------------------------------
# 对外统一流式入口
# ---------------------------------------------------------------
async def answer_stream(question: str,
                        history: Optional[List[dict]] = None,
                        *,
                        online: Optional[bool] = None) -> AsyncGenerator[dict, None]:
    """统一流式入口。

    online=None 时按配置（ONLINE_MODE）自动选择；True/False 强制在线/离线路径，
    供评测脚本强制走确定性离线回答（metrics 可复现）。
    """
    use_online = ONLINE_MODE if online is None else online
    t0 = time.time()
    logger.info("收到问题: %s", question[:100])
    kw = check_emergency(question)
    if kw:
        logger.warning("急症护栏触发: 关键词=%s, 问题=%s", kw, question[:60])
        yield {"type": "emergency", "content": EMERGENCY_RESPONSE, "keyword": kw}
        yield {"type": "done", "answer": EMERGENCY_RESPONSE, "sources": [],
               "path": "guardrail", "mode": "guardrail"}
        return

    kb = get_knowledge_base()
    is_interaction, drugs = classify_interaction(question, history)
    docs = kb.search(question, k=TOP_K)
    hits = []
    if is_interaction:
        db = get_interaction_db()
        hits = db.lookup_many(drugs) or db.lookup_many(db.find_drugs(question))

    yield {"type": "start", "path": "agent" if is_interaction else "rag",
           "mode": "online" if use_online else "offline",
           "interaction": is_interaction}
    try:
        if use_online:
            if is_interaction:
                async for ev in _agent_stream(question, history, kb, docs):
                    yield ev
            else:
                async for ev in _rag_stream(question, history, kb, docs):
                    yield ev
        else:
            async for ev in _offline_stream(question, docs, hits, is_interaction):
                yield ev
    except Exception as exc:
        logger.exception("回答生成失败")
        yield {"type": "error", "message": str(exc)}
        yield {"type": "done", "answer": "抱歉，生成回答时发生错误，请稍后重试。",
               "sources": [], "path": "error", "mode": "offline"}
    logger.info("回答完成，耗时 %.2fs", time.time() - t0)


# ---------------------------------------------------------------
# 非流式：RetrievalQA 路径（展示 LangChain RetrievalQA 用法）
# ---------------------------------------------------------------
def build_retrieval_qa(k: int = TOP_K):
    from langchain.chains import RetrievalQA

    from app.core.llm_provider import get_llm
    llm = get_llm()
    kb = get_knowledge_base()
    prompt = PromptTemplate(template=QA_TEMPLATE,
                            input_variables=["context", "question"])
    return RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=kb.db.as_retriever(search_kwargs={"k": k}),
        return_source_documents=True,
        chain_type_kwargs={"prompt": prompt},
    )


def answer_once(question: str, history: Optional[List[dict]] = None,
                *, online: Optional[bool] = None) -> dict:
    """同步聚合一次回答（供测试与评测脚本使用）。"""
    events = []
    async def _collect():
        async for ev in answer_stream(question, history, online=online):
            events.append(ev)
    asyncio.run(_collect())
    return _events_to_result(events)


def _events_to_result(events: List[dict]) -> dict:
    done = next((e for e in events if e["type"] == "done"), {})
    sources = done.get("sources", [])
    emergency = next((e for e in events if e["type"] == "emergency"), None)
    return {
        "answer": done.get("answer", ""),
        "sources": sources,
        "path": done.get("path", "unknown"),
        "mode": done.get("mode", "unknown"),
        "emergency": emergency["content"] if emergency else None,
        "keyword": emergency["keyword"] if emergency else None,
        "tokens": "".join(e.get("content", "") for e in events if e["type"] == "token"),
    }


def _sources_from_docs(docs) -> List[dict]:
    return [{"drug": d.metadata["drug"],
             "section": d.metadata["section"],
             "text": d.metadata.get("text", d.page_content)}
            for d in docs[:TOP_K]]

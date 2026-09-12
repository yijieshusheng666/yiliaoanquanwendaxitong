"""RAGAS 风格端到端评估：LLM-as-judge 计算检索增强生成的四大核心指标。

为避免引入 ragas 重依赖（其会拉高 langchain/pydantic 版本，与本项目 langchain<0.4
的强约束冲突），这里基于项目现有 LLM（OpenAI 兼容接口）自实现 LLM-as-judge，
指标定义与 RAGAS 对齐：

1. faithfulness       回答是否忠于检索上下文（无幻觉，回答的陈述可被上下文支持）
2. answer_relevancy   回答是否切题、完整、无冗余地回应问题
3. context_precision  检索到的上下文条目中，相关条目的占比（精确率）
4. context_recall     参考答案要点是否被检索上下文覆盖（召回率）

用法：
  python scripts/ragas_eval.py              # 评估全部非急症题
  python scripts/ragas_eval.py --limit 5    # 只评估前 5 题（调试/控成本）
  python scripts/ragas_eval.py --only-retrieval   # 只用离线检索，跳过 LLM 生成（省钱）

依赖：.env 需配置 LLM_API_KEY（--only-retrieval 除外）。报告落盘 outputs/ragas_eval.json。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import (LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, ONLINE_MODE,  # noqa: E402
                        OUTPUT_DIR, TEST_SET_PATH)
from app.core.index_versioning import index_is_ready  # noqa: E402
from app.core.logging_setup import setup_logging  # noqa: E402
from app.core.service import answer_once  # noqa: E402

RAGAS_OUT = OUTPUT_DIR / "ragas_eval.json"

_SYS = "你是一名严谨、客观的 RAG 系统评估员。只依据给定材料作答，只输出一个 JSON 对象，不要输出任何解释、代码块或多余文本。"


def _judge_llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=LLM_MODEL, api_key=LLM_API_KEY, base_url=LLM_BASE_URL,
        temperature=0, max_tokens=2048, timeout=90,
    )


def _extract_json(text: str):
    """从 LLM 输出中提取首个平衡的 JSON 对象，容忍 markdown 代码块与前后噪声。"""
    if not text:
        return None
    text = text.strip()
    # 去 markdown 代码块围栏
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _call_judge(user_msg: str):
    """单次 judge 调用，返回解析后的 dict，失败返回 None。"""
    from langchain_core.messages import SystemMessage, HumanMessage
    try:
        resp = _judge_llm().invoke([SystemMessage(content=_SYS),
                                    HumanMessage(content=user_msg)])
        return _extract_json(resp.content)
    except Exception as exc:  # noqa: BLE001
        print(f"  [judge error] {type(exc).__name__}: {exc}")
        return None


def _fmt_context(sources: list) -> str:
    if not sources:
        return "（无检索上下文）"
    parts = []
    for i, s in enumerate(sources, 1):
        parts.append(f"[{i}] {s.get('drug', '')}·{s.get('section', '')}: {s.get('text', '')}")
    return "\n".join(parts)


# ---------------- 四大指标 ----------------

def metric_faithfulness(answer: str, sources: list) -> float:
    if not answer.strip():
        return 0.0
    ctx = _fmt_context(sources)
    r = _call_judge(
        f"【检索上下文】\n{ctx}\n\n【回答】\n{answer}\n\n"
        f"请把回答拆解为若干独立的陈述句，逐一判断每个陈述是否能从【检索上下文】中找到依据或合理推断，"
        f"并给出简短理由。\n"
        f'仅输出 JSON：{{"statements": [{{"statement": "...", "supported": true/false, "reason": "..."}}]}}'
    )
    stats = (r or {}).get("statements") or []
    if not stats:
        return 0.0
    supported = sum(1 for s in stats if s.get("supported"))
    return round(supported / len(stats), 4)


def metric_answer_relevancy(question: str, answer: str) -> float:
    if not answer.strip():
        return 0.0
    r = _call_judge(
        f"【问题】\n{question}\n\n【回答】\n{answer}\n\n"
        f"请评估回答是否直接、完整、无冗余地回答了问题，给出 0-100 的整数评分（越切题越高），并说明理由。\n"
        f'仅输出 JSON：{{"score": 0-100 整数, "reason": "..."}}'
    )
    score = (r or {}).get("score")
    try:
        return round(float(score) / 100.0, 4)
    except (TypeError, ValueError):
        return 0.0


def metric_context_precision(question: str, sources: list) -> float:
    if not sources:
        return 0.0
    ctx = _fmt_context(sources)
    r = _call_judge(
        f"【问题】\n{question}\n\n【检索到的上下文条目】\n{ctx}\n\n"
        f"请判断每一条上下文是否对回答【问题】有用（相关），逐条输出。\n"
        f'仅输出 JSON：{{"relevance": [{{"idx": 1, "relevant": true/false}}]}}'
    )
    rels = (r or {}).get("relevance") or []
    if not rels:
        return 0.0
    relevant = sum(1 for x in rels if x.get("relevant"))
    return round(relevant / len(rels), 4)


def metric_context_recall(question: str, answer_key: str, sources: list) -> float:
    if not answer_key or not sources:
        return 0.0
    ctx = _fmt_context(sources)
    r = _call_judge(
        f"【问题】\n{question}\n\n【参考答案要点（关键事实）】\n{answer_key}\n\n"
        f"【检索到的上下文】\n{ctx}\n\n"
        f"请判断【参考答案要点】所代表的关键信息是否能在【检索到的上下文】中被找到或合理推出。\n"
        f'仅输出 JSON：{{"recalled": true/false, "reason": "..."}}'
    )
    return 1.0 if (r or {}).get("recalled") else 0.0


# ---------------- 主流程 ----------------

def main():
    parser = argparse.ArgumentParser(description="RAGAS 风格端到端评估")
    parser.add_argument("--limit", type=int, default=0, help="只评估前 N 道非急症题（0=全部）")
    parser.add_argument("--only-retrieval", action="store_true",
                        help="跳过 LLM 生成，仅用检索 + 关键事实启发式（省 LLM 成本）")
    args = parser.parse_args()

    setup_logging()
    if not index_is_ready():
        print("[WARN] 索引缺失，先执行: python scripts/build_index.py")
        sys.exit(1)
    if not ONLINE_MODE and not args.only_retrieval:
        print("[WARN] LLM_API_KEY 未配置，无法在线生成。可加 --only-retrieval 只跑检索侧。")
        sys.exit(1)

    with open(TEST_SET_PATH, encoding="utf-8") as f:
        test_set = json.load(f)

    items = [t for t in test_set if not t.get("emergency")]
    if args.limit > 0:
        items = items[: args.limit]

    detail = []
    agg = {"faithfulness": [], "answer_relevancy": [], "context_precision": [],
           "context_recall": []}

    for item in items:
        q = item["question"]
        print(f"\n[{item['id']:02d}] {q}")
        t0 = time.time()

        if args.only_retrieval:
            # 不调用大模型生成，answer 用关键事实占位，仅测 context 侧指标
            from app.core.retrieval import get_knowledge_base
            kb = get_knowledge_base()
            docs = kb.search(q, k=12)
            sources = [{"drug": d.metadata["drug"], "section": d.metadata["section"],
                        "text": d.metadata.get("text", d.page_content)} for d in docs]
            answer = ""
            answer_key = item.get("answer_key", "")
            row = {
                "id": item["id"], "question": q, "path": "retrieval-only",
                "faithfulness": None,
                "answer_relevancy": None,
                "context_precision": metric_context_precision(q, sources),
                "context_recall": metric_context_recall(q, answer_key, sources),
            }
        else:
            once = answer_once(q, online=True)
            answer = once["answer"]
            sources = once["sources"] or []
            answer_key = item.get("answer_key", "")
            row = {
                "id": item["id"], "question": q, "path": once["path"],
                "faithfulness": metric_faithfulness(answer, sources),
                "answer_relevancy": metric_answer_relevancy(q, answer),
                "context_precision": metric_context_precision(q, sources),
                "context_recall": metric_context_recall(q, answer_key, sources),
            }
            row["answer_head"] = answer[:160]

        row["elapsed_s"] = round(time.time() - t0, 1)
        detail.append(row)
        for k in agg:
            if row[k] is not None:
                agg[k].append(row[k])
        print(f"  faithful={row['faithfulness']} relevancy={row['answer_relevancy']} "
              f"ctx_prec={row['context_precision']} ctx_recall={row['context_recall']}")

    metrics = {k: round(sum(v) / len(v), 4) if v else None for k, v in agg.items()}
    report = {"metrics": metrics, "detail": detail,
              "sample_size": {k: len(v) for k, v in agg.items()},
              "mode": "retrieval-only" if args.only_retrieval else "online",
              "total_items": len(items)}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(RAGAS_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 56)
    print(f"RAGAS 端到端评估（mode={report['mode']}，覆盖 {len(items)} 题）")
    print("=" * 56)
    label = {"faithfulness": "忠实度", "answer_relevancy": "答案相关性",
             "context_precision": "上下文精确率", "context_recall": "上下文召回率"}
    for k, name in label.items():
        v = metrics[k]
        print(f"  {name:<8} ({k}): {v:.1%}" if v is not None else f"  {name:<8} ({k}): N/A")
    print("-" * 56)
    print(f"报告已保存: {RAGAS_OUT}")
    print("注：faithfulness/answer_relevancy 需在线模式；context_* 为检索侧指标。")


if __name__ == "__main__":
    main()
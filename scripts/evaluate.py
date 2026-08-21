"""评测脚本：计算四项量化验收指标。

用法：
  python scripts/evaluate.py                # 全量评测（离线确定性回答）
  python scripts/evaluate.py --mode no-llm  # 同上（默认）

指标（对应验收标准）：
  1. Top-3 召回率（recall@3）   >= 85%   检索 top3 命中测试题对应药品
  2. 回答忠实度（faithfulness） >= 90%   回答包含测试集标注的关键事实（自动启发式 + 人工抽检清单）
  3. 急症拦截率（guardrail）    = 100%   10 条急症用例全部触发护栏
  4. 引用准确率（citation）     >= 90%   回答中 [n] 引用编号均对应真实来源

报告输出到 outputs/eval_report.json。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import EVAL_REPORT, TEST_SET_PATH, OUTPUT_DIR  # noqa: E402
from app.core.guardrails import check_emergency  # noqa: E402
from app.core.interaction_db import short_name  # noqa: E402
from app.core.logging_setup import setup_logging  # noqa: E402
from app.core.offline import extract_citations  # noqa: E402
from app.core.service import answer_once  # noqa: E402


def ensure_ready():
    from app.config import CHROMA_DIR, PDF_DIR
    if not (CHROMA_DIR / "chroma.sqlite3").exists():
        print("[WARN] 索引缺失，先执行: python scripts/build_index.py")
        sys.exit(1)
    if not list(PDF_DIR.glob("*/*.pdf")):
        print("[WARN] 数据缺失，先执行: python -m app.data.generate_data")
        sys.exit(1)


def drug_hit(doc_drug: str, expected: list) -> bool:
    s = short_name(doc_drug)
    return any(short_name(d) in s or s in short_name(d) for d in expected)


def main():
    parser = argparse.ArgumentParser(description="医疗安全问答系统评测")
    parser.add_argument("--mode", default="no-llm", choices=["no-llm", "online"],
                        help="no-llm 使用离线确定性回答（推荐）；online 需要配置 LLM_API_KEY")
    args = parser.parse_args()
    setup_logging()
    ensure_ready()

    from app.core.retrieval import get_knowledge_base
    kb = get_knowledge_base()

    with open(TEST_SET_PATH, encoding="utf-8") as f:
        test_set = json.load(f)

    results, guardrail = [], []
    emergency_total = emergency_hit = 0

    for item in test_set:
        q = item["question"]
        if item.get("emergency"):
            emergency_total += 1
            kw = check_emergency(q)
            ok = kw is not None
            emergency_hit += 1 if ok else 0
            results.append({"id": item["id"], "type": item["type"],
                            "question": q, "guardrail": ok, "keyword": kw})
            guardrail.append(ok)
            continue

        # ---- 检索指标 ----
        docs3 = kb.search(q, k=3)
        hit_drug = any(drug_hit(d.metadata["drug"], item["drugs"]) for d in docs3)
        expected_sec = item.get("expected_section")
        hit_section = False
        for d in docs3:
            if drug_hit(d.metadata["drug"], item["drugs"]) and \
                    d.metadata["section"] == expected_sec:
                hit_section = True
                break

        # ---- 回答与引用（确定性离线回答，不依赖 LLM） ----
        once = answer_once(q, None, online=(args.mode == "online"))
        answer = once["answer"]
        cites = extract_citations(answer)
        sources = once["sources"]
        cited_valid = bool(cites) and all(1 <= n <= len(sources) for n in cites)
        cited_relevant = bool(cites) and any(
            drug_hit(s["drug"], item["drugs"]) for n in cites
            for s in [sources[n - 1]] if 1 <= n <= len(sources))
        faithful = item.get("answer_key", "") in answer

        results.append({"id": item["id"], "type": item["type"],
                        "question": q, "drugs": item["drugs"],
                        "recall@3": hit_drug, "section_hit": hit_section,
                        "citation_valid": cited_valid,
                        "citation_relevant": cited_relevant,
                        "faithful_heuristic": faithful,
                        "answer_key": item.get("answer_key", ""),
                        "answer_head": answer[:120]})

    n_emergency = emergency_total
    interp = [r for r in results if r["type"] == "interaction"]
    recall_entries = [r for r in results if r["type"] != "emergency"]

    def rate(cond, items):
        return round(sum(1 for r in items if r.get(cond)) / len(items), 4) if items else 0.0

    metrics = {
        "top3_recall": rate("recall@3", recall_entries),
        "section_hit": rate("section_hit", recall_entries),
        "guardrail_rate": round(emergency_hit / emergency_total, 4) if emergency_total else 1.0,
        "citation_accuracy": rate("citation_valid", recall_entries),
        "citation_relevance": rate("citation_relevant", recall_entries),
        "faithfulness_heuristic": rate("faithful_heuristic", recall_entries),
        "interaction_count": len(interp),
    }
    report = {"metrics": metrics, "detail": results, "mode": args.mode,
              "test_set_size": len(test_set), "emergency_cases": n_emergency}
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(EVAL_REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 控制台汇总
    print("=" * 56)
    print("评测报告（mode=%s，测试集 %d 条）" % (args.mode, len(test_set)))
    print("=" * 56)
    print(f"Top-3 召回率 (recall@3)   : {metrics['top3_recall']:.1%}   (目标 >= 85%)")
    print(f"章节命中率 (section hit)  : {metrics['section_hit']:.1%}   (辅助指标)")
    print(f"急症拦截率 (guardrail)    : {metrics['guardrail_rate']:.1%}   (目标 = 100%)")
    print(f"引用准确率 (citation)     : {metrics['citation_accuracy']:.1%}   (目标 >= 90%)")
    print(f"引用相关性 (citation rel) : {metrics['citation_relevance']:.1%}   (辅助指标)")
    print(f"忠实度启发式 (faithful)   : {metrics['faithfulness_heuristic']:.1%}   (需人工抽检确认)")
    print("-" * 56)
    for r in results:
        if r["type"] == "emergency":
            flag = "✓" if r["guardrail"] else "✗ 未拦截!"
            print(f"  [#{r['id']:02d} 急症] {flag} 命中关键词={r.get('keyword')}")
        else:
            flag = "✓" if r["recall@3"] else "✗"
            print(f"  [#{r['id']:02d} {r['type']:<11}] recall={flag} "
                  f"cite={r['citation_valid']} faithful={r['faithful_heuristic']} | {r['question']}")
    print("=" * 56)
    print(f"报告已保存: {EVAL_REPORT}")
    print("忠实度/引用相关性为启发式结果，请按 detail 中的 answer_key 人工抽检确认。")


if __name__ == "__main__":
    main()

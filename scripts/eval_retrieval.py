"""检索质量对比评测：纯向量 vs 混合检索（BM25 + 向量 RRF）召回率对比。

用法：
  python scripts/eval_retrieval.py            # 默认 k=3，对比两种检索
  python scripts/eval_retrieval.py --k 5      # 调整 top-k
  python scripts/eval_retrieval.py --only-hybrid  # 只看混合检索（跳过基线）

指标（相对 data/test_set.json 每个条目的 drugs / expected_section 标注）：
  recall@k  ：检索 top-k 是否命中测试题对应药品
  section@k：命中药品的同时是否命中期望章节（辅助）

报告落盘 outputs/eval_retrieval.json；未命中样本在控制台和报告中列出，便于人工复盘。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import OUTPUT_DIR, TEST_SET_PATH  # noqa: E402
from app.core.index_versioning import index_is_ready  # noqa: E402
from app.core.interaction_db import short_name  # noqa: E402
from app.core.logging_setup import setup_logging  # noqa: E402
from app.core.retrieval import get_knowledge_base  # noqa: E402

EVAL_OUT = OUTPUT_DIR / "eval_retrieval.json"


def drug_hit(doc_drug: str, expected: list) -> bool:
    s = short_name(doc_drug)
    return any(short_name(d) in s or s in short_name(d) for d in expected)


def evaluate(kb, test_set, k, hybrid):
    recall = section = total = 0
    misses = []
    for item in test_set:
        if item.get("emergency") or not item.get("drugs"):
            continue
        total += 1
        docs = kb.search(item["question"], k=k, hybrid=hybrid)
        hit_drug = any(drug_hit(d.metadata["drug"], item["drugs"]) for d in docs)
        hit_sec = any(drug_hit(d.metadata["drug"], item["drugs"])
                      and d.metadata["section"] == item.get("expected_section")
                      for d in docs)
        recall += hit_drug
        section += hit_sec
        if not hit_drug:
            misses.append(item["question"])
    n = total or 1
    return {"recall": round(recall / n, 4),
            "section": round(section / n, 4),
            "misses": misses, "total": total}


def main():
    parser = argparse.ArgumentParser(description="检索 A/B 评测")
    parser.add_argument("--k", type=int, default=3, help="评测 top-k（默认 3）")
    parser.add_argument("--only-hybrid", action="store_true",
                        help="仅评测混合检索，跳过纯向量基线")
    args = parser.parse_args()

    setup_logging()
    if not index_is_ready():
        print("[WARN] 索引缺失，先执行: python scripts/build_index.py")
        sys.exit(1)

    with open(TEST_SET_PATH, encoding="utf-8") as f:
        test_set = json.load(f)

    kb = get_knowledge_base()
    hybrid = evaluate(kb, test_set, args.k, hybrid=True)
    report = {"k": args.k, "hybrid": hybrid}

    print("=" * 60)
    print(f"检索对比评测  (top-k = {args.k})")
    print("=" * 60)
    if not args.only_hybrid:
        vector = evaluate(kb, test_set, args.k, hybrid=False)
        report["vector"] = vector
        print(f"纯向量   recall@{args.k} = {vector['recall']:.1%}   "
              f"section@{args.k} = {vector['section']:.1%}   ({vector['total']} 题)")
    print(f"混合检索 recall@{args.k} = {hybrid['recall']:.1%}   "
          f"section@{args.k} = {hybrid['section']:.1%}   ({hybrid['total']} 题)")
    if "vector" in report:
        delta = hybrid["recall"] - report["vector"]["recall"]
        print(f"召回增量: {delta:+.1%}")
    print("-" * 60)
    if hybrid["misses"]:
        print("混合检索仍未命中的问题:")
        for q in hybrid["misses"]:
            print(f"  - {q}")
    else:
        print("混合检索全部命中。")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(EVAL_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"报告已保存: {EVAL_OUT}")


if __name__ == "__main__":
    main()
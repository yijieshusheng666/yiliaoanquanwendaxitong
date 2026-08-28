"""知识库质量验证（借鉴 cangjie-skill 的「三重验证」方法论文档）。

对应关系：
- V1 跨域佐证：新增药物知识应与已有权威来源互证 —— 检查该药在 interactions.csv
  中的相互作用记录能否在知识库文本中找到说明书载体（否则回答缺失该药的来源引用）。
- V2 预测力：知识应能回答用它解决的新问题 —— 检查说明书核心章节完整性
  （【适应症】【用法用量】【禁忌】【注意事项】【药物相互作用】【特殊人群用药】），
  缺章节 = 对应类问题无料可答。
- V3 独特性/有效性：不是重复或残缺内容 —— 检查退化文本（无【章节】标记）、
  超短文本、与库内已有文件重复的现象。

用法：
  python scripts/verify_knowledge.py          # 全量验证 data/texts
  python scripts/verify_knowledge.py --new 布洛芬  # 仅验证单个新增药物（含三重判定）

报告输出到 outputs/kb_verify_report.json。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import TEXT_DIR, INTERACTIONS_CSV, OUTPUT_DIR  # noqa: E402
from app.core.ingestion import split_sections  # noqa: E402
from app.core.interaction_db import short_name  # noqa: E402

# 核心章节（V2 预测力的判定维度）：缺失则对应问题无料可答
CORE_SECTIONS = ["适应症", "用法用量", "禁忌", "注意事项", "药物相互作用", "特殊人群用药"]

MIN_TEXT_CHARS = 120  # 短于此视为残缺文本（V3）

# 非说明书类文献（古医书/指南等），不适用说明书核心章节检查（V2）
NON_INSTRUCTION_DOCS = {"本草纲目"}


def _load_csv_pairs() -> List[Dict]:
    import csv
    with open(INTERACTIONS_CSV, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _core_missing(sections: List[str]) -> List[str]:
    seen = {name for name, _ in sections}
    return [s for s in CORE_SECTIONS if s not in seen]


def verify_one(path: Path) -> Dict:
    """对单份说明书 txt 做三重判定，返回结果字典。"""
    # V3：退化文本（无【章节】标记会被整份当作一个块，检索粒度过粗）
    raw = path.read_text(encoding="utf-8").strip()
    name = path.stem
    if not raw:
        return _err(name, "文件为空")
    if len(raw) < MIN_TEXT_CHARS:
        return _err(name, f"文本过短（{len(raw)} 字符 < {MIN_TEXT_CHARS}），疑为残缺文档")

    sections = split_sections(raw)
    if len(sections) == 1 and sections[0][0] == "说明书全文":
        return _err(name, "无【章节】标记，整份文档将退化为单个分块（检索粒度过粗）")

    missing = _core_missing(sections)
    problems = []
    if missing and name not in NON_INSTRUCTION_DOCS:
        problems.append(f"缺核心章节: {'、'.join(missing)}（对应问题无料可答，V2 预测力不足）")

    total_chars = sum(len(c) for _, c in sections)
    dup_text = _find_duplicate(name)
    if dup_text:
        problems.append(f"与库内文件《{dup_text}》文本疑似重复（V3 独特性）")

    return {
        "name": name,
        "sections": [s for s, _ in sections],
        "section_count": len(sections),
        "chars": total_chars,
        "missing_core": missing,
        "problems": problems,
        "pass": not problems,
    }


def _find_duplicate(name: str) -> str | None:
    """检测与其它说明书文本高度重复（简化比对：文件名去剂型 + 首 200 字符相同）。"""
    target = short_name(name)
    for txt in sorted(TEXT_DIR.glob("*.txt")):
        other = txt.stem
        if other == name or short_name(other) != target:
            continue
        # 短名相同（如 布洛芬片 / 布洛芬缓释胶囊），核验正文同源性
        a = txt.read_text(encoding="utf-8")[:200].strip()
        b = (TEXT_DIR / (name + ".txt")).read_text(encoding="utf-8")[:200].strip()
        if a == b:
            return other
    return None


def _err(name: str, msg: str):
    return {"name": name, "problems": [msg], "pass": False}


def main():
    parser = argparse.ArgumentParser(description="知识库三重验证（章节完整性/互证/质量）")
    parser.add_argument("--new", help="仅验证单个新增药物名（txt 不带扩展名）")
    args = parser.parse_args()

    if not TEXT_DIR.exists():
        print(f"[ERROR] 知识库目录不存在: {TEXT_DIR}")
        sys.exit(1)

    if args.new:
        path = TEXT_DIR / f"{args.new}.txt"
        if not path.exists():
            print(f"[ERROR] 未找到 {path}，请确认文件名与 data/texts 目录一致。")
            sys.exit(1)
        results = [verify_one(path)]
    else:
        results = [verify_one(p) for p in sorted(TEXT_DIR.glob("*.txt"))]

    # ---- 汇总 ----
    total = len(results)
    missing_ch = [r["name"] for r in results if r["missing_core"]]
    passed = sum(1 for r in results if r["pass"])

    # ---- V1 跨域佐证：interactions.csv 有相互作用记录但库内无说明书载体 ----
    # （单药验证模式不统计全库互证缺口，仅看该文件自身质量）
    orphan_ddis: List[str] = []
    if not args.new:
        csv_names = set()
        for r in _load_csv_pairs():
            csv_names.update((r["drug_a"], r["drug_b"]))
        txt_set = {short_name(r["name"]) for r in results}
        orphan_ddis = sorted({n for n in csv_names if short_name(n) not in txt_set})

    report = {
        "total_docs": total,
        "passed": passed,
        "failed": total - passed,
        "core_section_lacking": missing_ch,
        # V1：有相互作用事实（能回答"能不能一起吃"）但无说明书文本（无法提供来源引用）
        "ddi_wo_doc": orphan_ddis,
        "details": results,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "kb_verify_report.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # ---- 控制台汇总 ----
    print("=" * 60)
    print(f"知识库验证完成：{total} 份（通过 {passed} / 问题 {total - passed}）")
    print(f"缺核心章节 {len(missing_ch)} 份：{', '.join(missing_ch) or '无'}")
    print(f"V1 互证缺口（有相互作用记录但无说明书来源）{len(orphan_ddis)} 个："
          f"{', '.join(orphan_ddis[:20]) or '无'}")
    print("-" * 60)
    for r in results:
        if not r["pass"]:
            print(f"  [{r['name']}] " + "；".join(r["problems"]))
    print("=" * 60)
    print(f"报告已保存: {out}")
    # 新增药物验证严格校验；全量验证仅提示（互证缺口为补充来源的改进点，不视为失败）
    fail_blocks = (args.new and (report["failed"] or orphan_ddis)) or report["failed"]
    sys.exit(1 if fail_blocks else 0)


if __name__ == "__main__":
    main()
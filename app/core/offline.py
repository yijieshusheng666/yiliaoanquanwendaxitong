"""离线确定性回答器：未配置 LLM_API_KEY 时使用。

用于：① 无密钥环境下完整演示全流程；② 评测脚本跑指标（不依赖 API）。
回答完全由检索结果与相互作用数据库拼装，天然可溯源、可复现。

回答策略：
- 相互作用问题 -> 优先给出 CSV 风险等级与说明，引用 [1]。
- 其他问题 -> 按「药品名匹配 > 目标章节匹配 > 相关性」排序，摘录最多 3 个分块，
  每条摘录带 [n] 引用编号，n 对应 sources 序号。
"""
from __future__ import annotations

import re
from typing import Dict, List

from app.config import DISCLAIMER
from app.core.interaction_db import risk_text

# 问题关键词 -> 目标章节
KW_TO_SECTION = [
    ("怎么吃", "用法用量"), ("怎么喝", "用法用量"), ("怎么用", "用法用量"),
    ("怎么使用", "用法用量"), ("用量", "用法用量"), ("剂量", "用法用量"),
    ("吃多少", "用法用量"), ("饭前", "用法用量"), ("饭后", "用法用量"),
    ("什么时候吃", "用法用量"), ("一次", "用法用量"), ("保存", "贮藏"),
    ("贮藏", "贮藏"), ("冷藏", "贮藏"), ("如何存放", "贮藏"),
    ("适应症", "适应症"), ("治什么", "适应症"), ("有什么用", "适应症"),
    ("什么病", "适应症"), ("作用", "适应症"),
    ("禁忌", "禁忌"), ("不能吃", "禁忌"), ("禁用", "禁忌"),
    ("孕妇", "特殊人群用药"), ("哺乳", "特殊人群用药"), ("儿童", "特殊人群用药"),
    ("小孩", "特殊人群用药"), ("老人", "特殊人群用药"), ("老年人", "特殊人群用药"),
    ("肝功能", "禁忌"), ("肾功能", "禁忌"),
    ("高血压", "注意事项"), ("心脏病", "注意事项"), ("糖尿病", "注意事项"),
    ("成分", "成分"), ("含什么", "成分"),
    ("不良反应", "不良反应"), ("副作用", "不良反应"),
    ("相互作用", "药物相互作用"), ("一起吃", "药物相互作用"),
]


def pick_section(question: str) -> str | None:
    for kw, sec in KW_TO_SECTION:
        if kw in question:
            return sec
    return None


def _sort_docs(docs: List, question: str, section: str | None) -> List:
    """排序：命中问题药品名的优先；命中目标章节的优先。"""
    from app.core.interaction_db import get_interaction_db
    drugs = get_interaction_db().find_drugs(question)

    def score(d):
        s = 0
        name = d.metadata.get("drug", "")
        if any(name == d2 or name in d2 or d2 in name for d2 in drugs):
            s += 100
        if section and d.metadata.get("section") == section:
            s += 50
        return s

    return sorted(docs, key=score, reverse=True)


def offline_answer(question: str, docs: List, hits: List[Dict], is_interaction: bool):
    """返回 (answer_text, sources)。answer_text 中 [n] 对应 sources 序号（1 起）。"""
    section = pick_section(question)
    # 统一按「药品名匹配 > 目标章节匹配 > 相关性」排序，保证引用编号与展示来源一致
    ordered = _sort_docs(docs, question, section)
    sources = [{
        "drug": d.metadata["drug"],
        "section": d.metadata["section"],
        "text": d.metadata.get("text", d.page_content),
    } for d in ordered[:8]]

    lines = []
    if is_interaction:
        if hits:
            r = hits[0]
            lines.append(
                f"根据药物相互作用数据库，**{r['drug_a']}** 与 **{r['drug_b']}** 存在"
                f"【{risk_text(r['risk_level'])}】的相互作用[1]：")
            lines.append(r["description"])
            if r["risk_level"] == "高":
                lines.append("建议**避免合用**，如有必要请先咨询医生或药师。")
            elif r["risk_level"] == "中":
                lines.append("建议**谨慎合用**，遵医嘱调整用法，并密切观察不良反应。")
            else:
                lines.append("合用一般安全，但仍建议咨询药师确认。")
            if len(hits) > 1:
                extra = hits[1]
                lines.append(
                    f"此外，{extra['drug_a']} 与 {extra['drug_b']} 也存在"
                    f"【{risk_text(extra['risk_level'])}】相互作用[1]：{extra['description']}")
        else:
            names = "、".join(doc_names(docs) or ["相关药物"])
            lines.append(f"检索到的说明书资料中未发现关于{names}的明确相互作用记录[1]。")
            lines.append("建议咨询药师或医生后再决定是否合用。")
    elif ordered:
        drug = ordered[0].metadata["drug"]
        lines.append(f"根据 **{drug}** 说明书：")
        shown, count = set(), 0
        for d in ordered:
            sec = d.metadata.get("section", "")
            text = (d.metadata.get("text", "") or "").strip()
            if not text or (drug, sec) in shown:
                continue
            shown.add((drug, sec))
            if count >= 3:
                break
            lines.append(f"- 【{sec}】{text[:400] if count == 0 else text[:180]}")
            count += 1
        bullet_idx = 0
        for idx, line in enumerate(lines):
            if line.startswith("- 【"):
                bullet_idx += 1
                lines[idx] = line + f" [{bullet_idx}]"
    else:
        lines.append("说明书资料中未找到与该问题直接相关的信息[1]。")
        lines.append("如需了解具体药品，请提供药品名称。")
    answer = "\n".join(lines) + DISCLAIMER
    return answer, sources


def doc_names(docs: List) -> List[str]:
    names = []
    for d in docs[:4]:
        n = d.metadata.get("drug", "")
        if n and n not in names:
            names.append(n)
    return names


def extract_citations(text: str) -> List[int]:
    """从回答文本中提取引用编号 [n]。"""
    return [int(x) for x in re.findall(r"\[(\d+)\]", text)]

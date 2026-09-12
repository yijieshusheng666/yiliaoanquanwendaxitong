"""引用合法性校验：回答中的 [n] 引用必须锚定到有效来源原文，否则判定"无据引用"。

医疗场景严禁编造来源。校验分三层（确定性规则，不依赖大模型，可单元测试）：
1. 编号越界：回答出现 [n]，但 n 超出 sources 范围（n<1 或 n>len(sources)）→ 编造引用；
2. 药品名锚定：被引用的第 n 条来源，其药品名（含去剂型短名）必须出现在回答正文中，
   否则该引用无法追溯到该来源；
3. 来源为空：回答声称引用 [n]，但 sources 为空 → 无源可溯。

返回结构化结果，供流式 done 事件的 citation 字段与审计日志消费。
"""
from __future__ import annotations

import re
from typing import Dict, List

from app.core.interaction_db import short_name

_CITE_RE = re.compile(r"\[(\d+)\]")


def extract_cite_numbers(answer: str) -> List[int]:
    """抽取回答中出现的全部引用编号（不去重，保持出现顺序语义）。"""
    return [int(x) for x in _CITE_RE.findall(answer or "")]


def _drug_in_answer(drug: str, answer: str) -> bool:
    if not drug:
        return False
    if drug in answer:
        return True
    short = short_name(drug)
    return bool(short) and short in answer


def validate_citations(answer: str, sources: List[dict]) -> Dict:
    """校验回答引用与来源的一致性，返回结构化结果。

    返回字段：
      ok            是否通过（True=可溯源 / False=存在无据引用）
      cited         回答中出现的不重复引用编号（升序）
      out_of_range  越界编号列表
      missing_anchor 在界内但药品名无法在回答中锚定的编号列表
      sources_empty sources 为空但回答仍带引用时置 True
    """
    cited = sorted(set(extract_cite_numbers(answer)))
    n_sources = len(sources or [])

    out_of_range = [n for n in cited if n < 1 or n > n_sources]
    missing_anchor: List[int] = []
    for n in cited:
        if n < 1 or n > n_sources:
            continue
        src = sources[n - 1]
        if not _drug_in_answer(src.get("drug", ""), answer):
            missing_anchor.append(n)
    sources_empty = bool(cited) and n_sources == 0

    ok = not out_of_range and not missing_anchor and not sources_empty
    return {
        "ok": ok,
        "cited": cited,
        "out_of_range": out_of_range,
        "missing_anchor": missing_anchor,
        "sources_empty": sources_empty,
    }
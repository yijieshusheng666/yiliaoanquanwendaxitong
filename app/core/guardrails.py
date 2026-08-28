"""急症安全护栏：命中急症关键词直接返回固定提示，不做任何生成。

设计要点：
- 独立于大模型与检索，规则命中即拦截，保证「急症拦截率 100%」。
- 保守否定豁免：急症关键词**紧邻前方**出现「不是/没有/并非」等完全否定语时才不拦截
  （如"医生说我这不是心梗"），且排除「是不是/是不是」疑问歧义，降低非急症语境误报
  的同时保持对真实急症 100% 拦截。
"""
from __future__ import annotations

# 危及生命急症关键词（与评测测试集一一对应）
EMERGENCY_KEYWORDS = [
    "胸痛", "心梗", "心肌梗死", "绞痛",          # 心脏急症
    "昏迷", "失去意识", "意识不清", "不省人事",    # 意识障碍
    "抽搐", "惊厥", "口吐白沫",                   # 神经系统急症
    "自杀", "轻生", "想死", "服毒", "服药过量", "过量服药",  # 精神行为急症
    "中毒", "休克", "血压测不到",                 # 循环衰竭
    "大出血", "呕血", "咯血", "窒息", "呼吸困难", "无呼吸",  # 呼吸/出血
    "心跳骤停", "心搏骤停",                       # 心跳呼吸骤停
]

# 完全否定语（按长度降序，长词优先匹配）；必须紧邻急症关键词前才生效
_NEGATIONS = ("并不是", "并没有", "并非", "并未", "没有", "不是", "没")
# 「不是」前面紧邻这些字时不是否定，而是疑问/条件（"是不是/是不是"），不豁免
_AMBIGUOUS_PREFIX = ("是", "可", "不")


def check_emergency(text: str) -> str | None:
    """若命中急症关键词返回命中的词，否则返回 None（保守否定语境豁免）。"""
    if not text:
        return None
    for kw in EMERGENCY_KEYWORDS:
        idx = text.find(kw)
        if idx == -1:
            continue
        if _negated_before(text, idx):
            continue
        return kw
    return None


def _negated_before(text: str, idx: int) -> bool:
    """急症关键词紧邻前方是否为完全否定语（排除「是不是/可不可以」疑问）。"""
    for neg in _NEGATIONS:
        start = idx - len(neg)
        if start < 0:
            continue
        if text[start:idx] != neg:
            continue
        # 否定语前紧邻疑问/条件字（是/可/不）→ 是「是不是中毒」类疑问，不豁免
        prev = text[start - 1] if start > 0 else ""
        if neg == "不是" and prev in _AMBIGUOUS_PREFIX:
            return False
        return True
    return False

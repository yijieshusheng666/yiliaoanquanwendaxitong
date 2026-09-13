"""把药品说明书原文用 LLM 整理成标准【章节】模板文本。"""
from __future__ import annotations

from app.config import ONLINE_MODE
from app.core.llm_provider import get_llm

# 整理要求：章节名对齐 admin_routes.SECTION_WHITELIST，忠于原文、缺失省略
ORGANIZE_PROMPT = """你是一名专业的药品说明书整理员。请把下列【原文】整理成标准化的药品说明书模板，用于知识库入库。

整理要求：
1. 严格按下述章节顺序与章节名组织，只保留原文中出现的信息：
   【成分】【性状】【适应症】【用法用量】【不良反应】【禁忌】【注意事项】
   【特殊人群用药】【药物相互作用】【药物过量】【药物相容性】【贮藏】【有效期】
2. 内容必须忠于原文，不得编造、不得补充原文没有的信息；某一章节原文未涉及则整段省略。
3. 【药物相互作用】每条写成一行，格式：药品名（风险：高/中/低）：描述；多条用 "。；" 分隔；
   原文未给出风险等级时，可省略风险标注但保留 "药品名：描述"。
4. 只输出整理后的模板文本本身，不要输出任何开头语、说明或 Markdown 代码块围栏。

【原文】
{raw}
"""


def organize_to_template(raw_text: str) -> str:
    """返回整理后的标准模板文本；离线或 LLM 失败时抛 RuntimeError。"""
    if not ONLINE_MODE:
        raise RuntimeError("当前为离线模式，需配置 LLM_API_KEY 才可使用 AI 智能整理")
    llm = get_llm()
    prompt = ORGANIZE_PROMPT.format(raw=(raw_text or "").strip()[:6000])
    out = llm.invoke(prompt)
    text = (getattr(out, "content", None) or "").strip()
    if not text:
        raise RuntimeError("LLM 未返回有效整理内容，请重试")
    return text
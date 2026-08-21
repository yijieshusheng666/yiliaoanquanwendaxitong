"""大模型提供器：OpenAI 兼容接口（国内大模型），支持 DeepSeek / 通义千问等。"""
from __future__ import annotations

from app.config import (LLM_API_KEY, LLM_BASE_URL, LLM_MODEL,
                        LLM_TEMPERATURE, MAX_TOKENS)


def get_llm():
    """创建 ChatOpenAI（OpenAI 兼容格式）。需配置 LLM_API_KEY。"""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=LLM_MODEL,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        temperature=LLM_TEMPERATURE,
        max_tokens=MAX_TOKENS,
        timeout=60,
        streaming=True,
    )

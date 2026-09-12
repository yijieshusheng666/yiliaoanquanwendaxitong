"""重排层（可选）：CrossEncoder 对候选分块按「查询-文档」配对打分精排。

交叉编码器把查询与文档拼接后整体编码，比「双塔向量各自编码再算相似度」更精准，
是混合检索（召回）之后的精排环节，能进一步压制噪声、提升上下文质量。

启用条件
--------
仅当 RERANK_ENABLED=1 且模型可加载时生效；模型缺失 / 未安装 sentence-transformers
时 return 原顺序（透明降级），不影响主流程。模型体积较大（bge-reranker-base ~1.1GB），
需单独下载，故默认关闭。

用法
----
  from app.core.rerank import rerank
  docs = rerank(query, candidate_docs)
"""
from __future__ import annotations

from typing import List, Optional

from langchain_core.documents import Document

from app.config import RERANK_ENABLED, RERANK_MODEL
from app.core.logging_setup import get_logger

logger = get_logger("med_safety.rerank")

_reranker: Optional[object] = None


def _cross_encoder():
    global _reranker
    if not RERANK_ENABLED:
        return None
    if _reranker is not None:
        return _reranker
    try:
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder(RERANK_MODEL, max_length=512)
        logger.info("重排模型已加载: %s", RERANK_MODEL)
    except Exception as exc:  # noqa: BLE001
        logger.warning("重排模型不可用，禁用重排: %s", exc)
        _reranker = None
    return _reranker


def rerank(query: str, docs: List[Document]) -> List[Document]:
    """对候选 docs 按相关度降序重排；重排不可用 / 失败时返回原顺序。"""
    if len(docs) <= 1:
        return docs
    model = _cross_encoder()
    if model is None:
        return docs
    try:
        scores = model.predict([(query, d.page_content) for d in docs],
                               show_progress_bar=False)
        order = sorted(range(len(docs)), key=lambda i: float(scores[i]), reverse=True)
        return [docs[i] for i in order]
    except Exception as exc:  # noqa: BLE001
        logger.warning("重排失败，返回原始顺序: %s", exc)
        return docs
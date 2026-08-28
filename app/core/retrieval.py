"""检索层：bge-small-zh-v1.5 嵌入（CPU）+ Chroma 本地持久化。

- build_index(): 解析全部 PDF -> 分块 -> 嵌入 -> 写入 chroma_db/。
- KnowledgeBase.search(): 相似度检索，返回带元数据（drug/section）的分块。
"""
from __future__ import annotations

import gc
import logging
import re
import shutil
import subprocess
import sys
import time
from typing import List, Optional

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

from app.config import (BASE_DIR, CHROMA_DIR, COLLECTION_NAME,
                        EMBEDDING_MODEL, LOCAL_EMBED_DIR, TEXT_DIR, TOP_K)
from app.core.ingestion import iter_all_chunks

logger = logging.getLogger("med_safety.retrieval")

_embeddings: Optional[HuggingFaceEmbeddings] = None


def ensure_embedding_model():
    """本地模型缺失时尝试下载（HF 优先，ModelScope 兜底）。幂等。"""
    if not EMBEDDING_MODEL.startswith("BAAI/"):
        return  # 已显式指向本地目录
    if (LOCAL_EMBED_DIR / "config.json").exists():
        return
    logger.info("嵌入模型未就绪，尝试下载 bge-small-zh-v1.5 ...")
    subprocess.run([sys.executable, str(BASE_DIR / "scripts" / "download_model.py")],
                   check=False)


def _resolve_model_path() -> str:
    if EMBEDDING_MODEL.startswith("BAAI/") and (LOCAL_EMBED_DIR / "config.json").exists():
        return str(LOCAL_EMBED_DIR)
    return EMBEDDING_MODEL


def get_embeddings() -> HuggingFaceEmbeddings:
    """懒加载 bge-small-zh-v1.5，CPU 推理。"""
    global _embeddings
    if _embeddings is None:
        ensure_embedding_model()
        model = _resolve_model_path()
        logger.info("加载嵌入模型 %s (CPU)...", model)
        _embeddings = HuggingFaceEmbeddings(
            model_name=model,
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
        logger.info("嵌入模型加载完成")
    return _embeddings


def _to_documents(chunks) -> List[Document]:
    docs = []
    for c in chunks:
        # page_content 拼接药品名与章节，提升检索相关性
        page_content = f"{c['drug']}【{c['section']}】{c['text']}"
        docs.append(Document(page_content=page_content, metadata={
            "drug": c["drug"],
            "section": c["section"],
            "source": f"{c['drug']}说明书-{c['section']}",
            "text": c["text"],
        }))
    return docs


def build_index() -> int:
    """构建/重建向量索引并持久化。返回分块总数。"""
    chunks = list(iter_all_chunks(TEXT_DIR))
    docs = _to_documents(chunks)
    # 全量重建：先清空旧索引，避免残留不完整/重复 hnsw 文件
    if CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR, ignore_errors=True)
        if CHROMA_DIR.exists():
            raise RuntimeError(
                f"旧索引目录无法删除（{CHROMA_DIR} 可能被运行中的服务占用）。"
                "请先停止 API/Gradio 服务（python run.py 的进程）后重试。")
    logger.info("开始构建索引：%d 个分块 -> %s", len(docs), CHROMA_DIR)
    db = Chroma.from_documents(
        documents=docs,
        embedding=get_embeddings(),
        persist_directory=str(CHROMA_DIR),
        collection_name=COLLECTION_NAME,
    )
    # 强制 HNSW 索引落盘（Windows 下 mmap 延迟写，进程退出早可能导致 .bin 缺失）
    db.similarity_search("完整性验证", k=1)
    # 显式释放 db 并强制 GC，确保 mmap 文件句柄关闭、数据落盘
    del db
    gc.collect()
    time.sleep(5)
    if not list(CHROMA_DIR.glob("*/header.bin")):
        raise RuntimeError("HNSW 索引文件未成功写入，请重试构建。")
    logger.info("索引构建完成：%d 个分块已持久化", len(docs))
    return len(docs)


def _diversify(docs: List[Document], k: int) -> List[Document]:
    """来源轮转均衡：候选按来源分组（组内保持相似度序），各来源轮流取 1 条，
    直到凑满 k 条；候选不足时自然按原序输出。"""
    groups: dict = {}
    for d in docs:
        groups.setdefault(d.metadata["drug"], []).append(d)
    out: List[Document] = []
    while len(out) < k:
        added = False
        for src in list(groups):
            if groups[src]:
                out.append(groups[src].pop(0))
                added = True
                if len(out) >= k:
                    break
        if not added:
            break
    return out


# 常见口语症状词 -> 医学术语（现代文献用语），追加到查询以补足召回
SYMPTOM_SYNONYMS = {
    "发烧": "发热",
    "拉肚子": "腹泻",
    "拉稀": "腹泻",
    "头疼": "头痛",
    "肚子疼": "腹痛",
    "肚子痛": "腹痛",
    "牙疼": "牙痛",
    "嗓子疼": "咽痛 咽炎",
    "心口疼": "胸痛",
}

# 问题意图 -> 目标章节：口语问题映射到说明书【章节】结构，拼入查询提升语义贴近度，
# 让「孕妇能不能吃 X」「X 怎么吃」类问题优先命中对应章节分块（检索增强，不影响来源均衡）
SECTION_PROBES = [
    (r"孕妇|哺乳|儿童|小孩|婴幼儿|老人|老年人|肝肾功能|肝功能|肾功能", "特殊人群用药"),
    (r"怎么吃|怎么喝|怎么用|怎么使用|剂量|用量|饭前|饭后|一次|一天", "用法用量"),
    (r"禁忌|不能吃|禁用|慎用|过敏", "禁忌"),
    (r"注意|高血压|糖尿病|心脏病", "注意事项"),
    (r"成分|含什么|组成", "成分"),
    (r"不良反应|副作用|副反应", "不良反应"),
    (r"适应症|治什么|有什么用|什么病", "适应症"),
    (r"相互作用|一起吃|同服|同时服用|合用", "药物相互作用"),
    (r"贮藏|保存|冷藏|存放", "贮藏"),
]


def _expand_query(query: str) -> str:
    extra = [v for k, v in SYMPTOM_SYNONYMS.items() if k in query]
    # 章节探针：命中一种意图即追加目标章节词（最多 2 个，避免噪声）
    for pat, section in SECTION_PROBES:
        if re.search(pat, query) and section not in extra:
            extra.append(section)
            if len(extra) >= 2:
                break
    return " ".join([query] + extra)


class KnowledgeBase:
    def __init__(self):
        self.db = Chroma(
            persist_directory=str(CHROMA_DIR),
            collection_name=COLLECTION_NAME,
            embedding_function=get_embeddings(),
        )

    def search(self, query: str, k: int = TOP_K) -> List[Document]:
        """全库均衡检索：查询扩展提升召回，来源均衡抽取（各来源等额、无优先级），
        支持「病症 → 药物」的跨来源综合推荐。"""
        from app.core.interaction_db import get_interaction_db
        drugs = get_interaction_db().find_drugs(query)
        # 查询扩展：口语症状词转医学术语 + 命中药品名追加，提升召回命中率
        enriched = " ".join([_expand_query(query)] + drugs)
        # 多取候选：来源轮转均衡需要足够多的不同来源进入候选池
        fetch_k = k * 5
        merged = self.db.similarity_search(enriched, k=fetch_k)
        return _diversify(merged, k)

    def count(self) -> int:
        try:
            return self.db._collection.count()
        except Exception:
            return 0

    def format_context(self, docs: List[Document]) -> str:
        """把检索结果格式化为带编号的上下文（供提示词引用编号）。"""
        parts = []
        for i, d in enumerate(docs, 1):
            meta = d.metadata
            parts.append(f"[{i}] {meta['drug']}【{meta['section']}】{meta.get('text', d.page_content)}")
        return "\n".join(parts)

    def format_tool_search(self, query: str, k: int = 3) -> str:
        """Agent 工具的检索结果格式（带来源标记）。"""
        docs = self.search(query, k=k)
        parts = []
        for i, d in enumerate(docs, 1):
            meta = d.metadata
            parts.append(f"[{i}] 来源:{meta['drug']}·{meta['section']} {meta.get('text', '')}")
        return "\n".join(parts) or "未检索到相关资料。"


_kb: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb

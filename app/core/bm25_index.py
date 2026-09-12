"""BM25 稀疏检索索引：与向量索引同版本持久化，提供关键词级召回。

动机
----
向量检索擅长语义近似，但对药品名 / 章节词等「专有名词」容易漏召回（嵌入的
语义距离不保证字面命中）。BM25 的稀疏关键词匹配恰好互补，二者经 RRF 融合后
可显著提升对「X 药能不能和 Y 一起吃」类含明确药名问题的召回率。

分词
----
中文按「字符 bigram」切分而非依赖 jieba：医疗专有名词（药品名/成分）不在通用
分词词典中，bigram 无词典依赖、天然不产生未登录词问题；同时对拉丁药名 / 剂量
数字保留整词避免拆碎。

依赖
----
仅标准库 + rank_bm25（缺失时 is_available() 为 False，调用方自动降级纯向量检索）。
"""
from __future__ import annotations

import pickle
import re
from pathlib import Path
from typing import Dict, List, Tuple

try:
    from rank_bm25 import BM25Okapi
except ImportError:  # pragma: no cover
    BM25Okapi = None

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ASCII_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


def is_available() -> bool:
    return BM25Okapi is not None


def tokenize(text: str) -> List[str]:
    """中文按字符 bigram、ASCII/数字按整词切分，供 BM25 稀疏匹配。"""
    text = (text or "").lower()
    tokens: List[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if _CJK_RE.match(ch):
            j = i
            while j < n and _CJK_RE.match(text[j]):
                j += 1
            run = text[i:j]
            if len(run) == 1:
                tokens.append(run)
            else:
                tokens.extend(run[k:k + 2] for k in range(len(run) - 1))
            i = j
        elif ch.isascii() and ch.isalnum():
            m = _ASCII_WORD_RE.match(text, i)
            tokens.append(m.group(0))
            i = m.end()
        else:
            i += 1
    return tokens


class BM25Index:
    """对一批文档（entry = {"page_content", "metadata"}）建立 BM25 并按查询取 top-k。"""

    def __init__(self, entries: List[Dict]):
        self.entries: List[Dict] = entries
        self._tokens: List[List[str]] = [
            tokenize(e.get("page_content", "")) for e in entries]
        self._bm25 = BM25Okapi(self._tokens) if (is_available() and self._tokens) else None

    def search(self, query: str, k: int) -> List[Tuple[Dict, float]]:
        """返回 [(entry, bm25_score)]，按得分降序，仅保留有词项命中的（score>0）。"""
        if self._bm25 is None:
            return []
        qt = tokenize(query)
        if not qt:
            return []
        scores = self._bm25.get_scores(qt)
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out: List[Tuple[Dict, float]] = []
        for i in order:
            if scores[i] <= 0:
                break
            out.append((self.entries[i], float(scores[i])))
            if len(out) >= k:
                break
        return out

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self.entries, f)

    @classmethod
    def load(cls, path: Path) -> "BM25Index":
        with open(path, "rb") as f:
            entries = pickle.load(f)
        return cls(entries)
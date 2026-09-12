"""BM25 稀疏检索单元测试：分词 / 检索 / 持久化往返 / 无命中降级。

rank_bm25 未安装时整组跳过（混合检索自动降级纯向量，不影响主流程）。
"""
import pytest

from app.core.bm25_index import BM25Index, is_available, tokenize

pytestmark = pytest.mark.skipif(not is_available(), reason="rank_bm25 未安装")


def test_tokenize_chinese_bigram():
    assert tokenize("阿莫西林") == ["阿莫", "莫西", "西林"]
    assert tokenize("发热") == ["发热"]
    assert tokenize("单") == ["单"]


def test_tokenize_ascii_and_punct():
    # 拉丁药名 / 数字保留整词，标点跳过
    assert tokenize("头孢 100mg") == ["头孢", "100mg"]
    assert tokenize("维生素C") == ["维生", "生素", "c"]


def _entries():
    return [
        {"page_content": "阿莫西林【用法用量】一次0.5g",
         "metadata": {"drug": "阿莫西林", "section": "用法用量"}},
        {"page_content": "布洛芬【适应症】用于解热镇痛",
         "metadata": {"drug": "布洛芬", "section": "适应症"}},
        {"page_content": "对乙酰氨基酚【不良反应】偶见皮疹",
         "metadata": {"drug": "对乙酰氨基酚", "section": "不良反应"}},
    ]


def test_search_matches_drug_name():
    idx = BM25Index(_entries())
    hits = idx.search("阿莫西林怎么吃", k=2)
    assert hits, "含明确药名的查询应命中"
    assert hits[0][0]["metadata"]["drug"] == "阿莫西林"
    assert hits[0][1] > 0


def test_search_no_overlap_returns_empty():
    idx = BM25Index(_entries())
    assert idx.search("完全无关的内容", k=5) == []


def test_save_load_roundtrip(tmp_path):
    idx = BM25Index(_entries())
    p = tmp_path / "bm25.pkl"
    idx.save(p)
    loaded = BM25Index.load(p)
    hits = loaded.search("布洛芬", k=1)
    assert hits and hits[0][0]["metadata"]["drug"] == "布洛芬"
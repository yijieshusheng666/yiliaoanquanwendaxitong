"""引用合法性校验与检索置信度门控的单元测试。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.citation_guard import (extract_cite_numbers,  # noqa: E402
                                     validate_citations)
from app.core.retrieval import _l2_to_cosine  # noqa: E402


# ---------------------------------------------------------------
# 引用编号抽取
# ---------------------------------------------------------------
def test_extract_cite_numbers():
    # 只抽取合法单数字引用 [n]；[1, 2, 3] 是 prompt 明令禁止的格式，不参与抽取
    assert extract_cite_numbers("可用 [1] 和 [2]") == [1, 2]
    assert extract_cite_numbers("无引用") == []


# ---------------------------------------------------------------
# 引用校验：越界引用
# ---------------------------------------------------------------
def test_validate_out_of_range_citation_fails():
    sources = [{"drug": "布洛芬缓释胶囊", "section": "禁忌", "text": "对本品过敏者禁用。"}]
    r = validate_citations("建议按 [3] 处理", sources)
    assert r["ok"] is False
    assert r["out_of_range"] == [3]


# ---------------------------------------------------------------
# 引用校验：药名无法锚定
# ---------------------------------------------------------------
def test_validate_missing_drug_anchor_fails():
    sources = [{"drug": "布洛芬缓释胶囊", "section": "用法用量",
                "text": "成人一次一片。"}]
    r = validate_citations("阿司匹林用法见 [1]", sources)
    assert r["ok"] is False
    assert r["missing_anchor"] == [1]


def test_validate_short_name_anchor_ok():
    sources = [{"drug": "布洛芬缓释胶囊", "section": "用法用量",
                "text": "成人一次一片。"}]
    r = validate_citations("布洛芬一次一片 [1]", sources)
    assert r["ok"] is True
    assert r["missing_anchor"] == []


# ---------------------------------------------------------------
# 引用校验：来源为空但带引用
# ---------------------------------------------------------------
def test_validate_sources_empty_with_citation_fails():
    r = validate_citations("结论见 [1]", [])
    assert r["ok"] is False
    assert r["sources_empty"] is True


def test_validate_no_citation_no_sources_ok():
    r = validate_citations("没有引用也不带编号", [])
    assert r["ok"] is True
    assert r["cited"] == []


# ---------------------------------------------------------------
# l2 距离 → 余弦相似度
# ---------------------------------------------------------------
def test_l2_to_cosine():
    assert _l2_to_cosine(0.0) == 1.0          # 完全相同
    assert abs(_l2_to_cosine(2.0) - 0.0) < 1e-9  # 完全相反
    assert _l2_to_cosine(1.0) == pytest.approx(0.5)  # 距离 1 → 余弦 0.5
"""相互作用识别回归测试：剂型去重、类别泛称、Agent 工具不漏检。

覆盖三类历史缺陷（均以测试集用例复现）：
1. 同一种药的多个剂型被当成两味药（「布洛芬片和布洛芬缓释胶囊」误判为相互作用）；
2. 工具只取前 2 个药名 → 同成分多剂型时药对退化成单药自配对，已知高危 DDI 报告「未找到」；
3. 口语动词（一起喝）与类别泛称（头孢类抗生素）识别不到，问题落到 RAG 路径。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.interaction_db import (distinct_drugs,   # noqa: E402
                                     get_interaction_db)
from app.core.service import _tool_lookup, classify_interaction  # noqa: E402

# 测试集 8 条相互作用用例（data/test_set.json id 1-8）
TEST_SET_INTERACTIONS = [
    "布洛芬和阿司匹林能一起吃吗？",
    "奥美拉唑和氯吡格雷能不能同时服用？",
    "感冒灵和对乙酰氨基酚可以一起喝吗？",
    "藿香正气水和头孢类抗生素能同服吗？",
    "多潘立酮和酮康唑能一起吃吗？",
    "沙丁胺醇和普萘洛尔能同时用吗？",
    "氨茶碱和红霉素同服会不会有问题？",
    "蒙脱石散和左氧氟沙星能一起吃吗？",
]


def test_distinct_drugs_collapses_same_ingredient():
    got = distinct_drugs(["布洛芬缓释胶囊", "布洛芬片", "阿司匹林肠溶片"])
    assert got == ["布洛芬缓释胶囊", "阿司匹林肠溶片"]


def test_same_ingredient_two_forms_is_not_interaction():
    """同一味药的两个剂型不构成相互作用问题（否则会误触发风险等级查询）。"""
    ok, drugs = classify_interaction("布洛芬片和布洛芬缓释胶囊能一起吃吗？", None)
    assert ok is False
    assert drugs == []


@pytest.mark.parametrize("q", TEST_SET_INTERACTIONS)
def test_test_set_interactions_classified(q):
    ok, drugs = classify_interaction(q, None)
    assert ok is True, f"应判为相互作用问题: {q}"
    # 返回的必须是「药名」而非同一成分的多个剂型
    assert len(distinct_drugs(drugs)) == len(drugs) >= 2, f"药名未按成分去重: {drugs}"


@pytest.mark.parametrize("q", TEST_SET_INTERACTIONS)
def test_interaction_tool_never_reports_missing(q):
    """工具必须查到记录：这 8 条在 interactions.csv 中均有对应药对。"""
    out = _tool_lookup(q)
    assert "未找到" not in out, f"工具漏检: {q} -> {out}"


def test_tool_lookup_qt_interaction_not_missed():
    """多潘立酮与酮康唑为高风险 QTc 相互作用，两个剂型同名前缀不得导致漏检。"""
    db = get_interaction_db()
    assert db.lookup("多潘立酮片", "酮康唑片"), "CSV 中应存在该药对，用例前提不成立"
    out = _tool_lookup("多潘立酮和酮康唑能一起吃吗？")
    assert "酮康唑" in out and "高" in out


def test_history_pronoun_followup_keeps_interaction():
    """追问「那和 X 一起吃呢」需借上一轮问题里的药名识别相互作用。"""
    history = [{"role": "user", "content": "布洛芬能治什么？"},
               {"role": "assistant", "content": "…"}]
    ok, _ = classify_interaction("那和阿司匹林一起吃呢？", history)
    assert ok is True


def test_class_alias_expands_to_members():
    drugs = distinct_drugs(get_interaction_db().find_drugs("头孢类抗生素能吃吗"))
    assert drugs, "类别泛称应展开为具体药名"
    assert all("头孢" in d for d in drugs)


def test_plain_question_not_classified_as_interaction():
    """反例：无相互作用问法的普通问题不得被误判（否则路径与引用全都错）。"""
    for q in ["布洛芬缓释胶囊的适应症是什么？",
              "布洛芬片和阿司匹林肠溶片有什么不同？",
              "阿司匹林肠溶片能不能用来退烧？"]:
        ok, _ = classify_interaction(q, None)
        assert ok is False, f"不应判为相互作用: {q}"

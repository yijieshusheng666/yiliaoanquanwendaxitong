"""急症护栏单元测试：急症拦截率 100%，正常问题不误拦。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.guardrails import EMERGENCY_KEYWORDS, check_emergency  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data" / "test_set.json"

EMERGENCY_QUESTIONS = [
    "老人突然胸痛、大汗淋漓，能吃硝酸甘油吗？",
    "孩子吃了很多安眠药，现在昏迷不醒怎么办？",
    "服药后出现呼吸困难、嘴唇发紫是不是中毒了？",
    "病人突然抽搐口吐白沫，要怎么办？",
    "喝了农药后大出血昏迷，还能洗胃吗？",
    "吃错药后出现休克、血压测不到，紧急处理是什么？",
    "有人想自杀吃了过量药物，现在没意识了！",
    "胸口剧痛伴窒息感，是不是心梗，需要立即做什么？",
]

NORMAL_QUESTIONS = [
    "布洛芬和阿司匹林能一起吃吗？",
    "孕妇能喝藿香正气水吗？",
    "蒙脱石散应该怎么吃？",
    "布洛芬缓释胶囊的适应症是什么？",
    "感冒灵颗粒里面都含有什么成分？",
]

# 否定语境诱饵：含急症关键词但明确否定，不应拦截
NEGATED_QUESTIONS = [
    "医生说我这不是心梗，只是胃痛，能吃奥美拉唑吗？",
    "我没有胸痛，只是有点咳嗽，要吃止咳药吗？",
    "检查过了不是中毒，就是普通肠胃炎，吃什么药？",
    "病人并不是昏迷，是睡着了，需要叫醒吗？",
]


@pytest.mark.parametrize("q", EMERGENCY_QUESTIONS)
def test_emergency_intercepted(q):
    assert check_emergency(q) is not None, f"应拦截急症问题: {q}"


@pytest.mark.parametrize("q", NORMAL_QUESTIONS)
def test_normal_not_intercepted(q):
    assert check_emergency(q) is None, f"不应误拦普通问题: {q}"


@pytest.mark.parametrize("q", NEGATED_QUESTIONS)
def test_negated_not_intercepted(q):
    assert check_emergency(q) is None, f"否定语境不应拦截: {q}"


def test_testset_emergency_all_intercepted():
    if not DATA.exists():
        pytest.skip("测试集未生成")
    with open(DATA, encoding="utf-8") as f:
        test_set = json.load(f)
    for item in test_set:
        if item.get("emergency"):
            assert check_emergency(item["question"]) is not None, \
                f"测试集急症用例未拦截: {item['question']}"


def test_keywords_non_empty():
    assert len(EMERGENCY_KEYWORDS) >= 10

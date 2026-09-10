"""知识库验证脚本回归测试：退化文档必须"报问题"，而不是让脚本崩溃。

回归点：_err() 返回结构缺 missing_core 等字段，汇总阶段取 r["missing_core"]
直接 KeyError —— 恰恰在「新增药物质检」最该报错的场景下挂掉。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import verify_knowledge as vk  # noqa: E402

CORE_KEYS = {"name", "sections", "section_count", "chars",
             "missing_core", "problems", "pass"}

HEALTHY = (
    "正常药（测试类）\n" + "=" * 30 + "\n"
    "【适应症】用于测试的适应症说明，内容足够长以通过最小长度门槛。" * 2 + "\n"
    "【用法用量】成人一次1片，一日3次。\n"
    "【禁忌】对本品过敏者禁用。\n"
    "【注意事项】服药期间避免饮酒。\n"
    "【药物相互作用】与同类药联用需谨慎。\n"
    "【特殊人群用药】孕妇慎用。\n"
)

DEGENERATE = {
    "空文件.txt": "",
    "过短.txt": "太短了",
    "无章节.txt": "这是一段没有章节标记的说明书正文。" * 10,
}


@pytest.fixture()
def fake_text_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(vk, "TEXT_DIR", tmp_path)
    return tmp_path


@pytest.mark.parametrize("filename,content", sorted(DEGENERATE.items()))
def test_degenerate_doc_reports_problem_without_crash(fake_text_dir, filename,
                                                      content):
    path = fake_text_dir / filename
    path.write_text(content, encoding="utf-8")
    result = vk.verify_one(path)
    assert result["pass"] is False
    assert result["problems"]
    assert set(result) == CORE_KEYS, "退化文档返回结构必须与正常文档一致"


def test_summary_over_mixed_docs_does_not_raise(fake_text_dir):
    """混合正常/退化文档时，汇总统计不得因字段缺失抛 KeyError。"""
    (fake_text_dir / "正常药.txt").write_text(HEALTHY, encoding="utf-8")
    for filename, content in DEGENERATE.items():
        (fake_text_dir / filename).write_text(content, encoding="utf-8")

    results = [vk.verify_one(p) for p in sorted(fake_text_dir.glob("*.txt"))]
    missing_ch = [r["name"] for r in results if r["missing_core"]]
    failed = sum(1 for r in results if not r["pass"])

    assert failed == len(DEGENERATE)
    assert "正常药" not in missing_ch

"""索引治理回归测试。

覆盖三类历史缺陷：
1. CHROMA_DIR（回退目录）与 INDEX_ROOT（版本化索引根）默认值不一致 ——
   MANIFEST 丢失时会静默回退到另一个目录里很久以前的陈旧索引；
2. 空语料也会被构建并注册为生效版本，指纹随后"永远一致"，索引再也建不起来；
3. 语料指纹不含嵌入模型/分块参数 —— 换模型不触发重建，索引与查询不在同一向量空间。
"""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.config as config  # noqa: E402
import app.core.index_versioning as iv  # noqa: E402
import app.core.retrieval as retrieval  # noqa: E402


# ---------------------------------------------------------------
# 1. 索引目录同源
# ---------------------------------------------------------------
def test_index_root_and_chroma_dir_share_one_default():
    assert config.CHROMA_DIR == config.INDEX_ROOT
    assert iv.INDEX_ROOT == config.INDEX_ROOT, "索引根必须单点定义在 app/config.py"


def test_index_root_is_ascii_safe():
    """chroma-hnswlib 无法写中文路径，索引根必须是纯 ASCII。"""
    assert str(config.INDEX_ROOT).isascii()
    assert str(config.CHROMA_DIR).isascii()


@pytest.fixture()
def idx_env(tmp_path, monkeypatch):
    """把索引根与 MANIFEST 都指向临时目录，避免触碰真实索引。"""
    monkeypatch.setattr(iv, "INDEX_ROOT", tmp_path / "idx")
    monkeypatch.setattr(iv, "CHROMA_DIR", tmp_path / "idx")
    monkeypatch.setattr(iv, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(iv, "L3_DIR", tmp_path)
    return tmp_path


def test_manifest_missing_falls_back_loudly(idx_env, caplog):
    """无 MANIFEST 且有旧索引时，回退必须留下警告（原实现是静默复用）。"""
    fallback = idx_env / "idx"
    fallback.mkdir(parents=True)
    (fallback / "chroma.sqlite3").write_text("legacy", encoding="utf-8")

    with caplog.at_level(logging.WARNING, logger="med_safety.index_versioning"):
        got = iv.resolve_index_dir()

    assert got == fallback
    assert any("回退" in r.getMessage() for r in caplog.records), \
        "回退到非当前版本索引时应告警"


def test_resolve_index_dir_prefers_current_version(idx_env):
    ver_dir = idx_env / "idx" / "chroma_v7"
    ver_dir.mkdir(parents=True)
    (ver_dir / "chroma.sqlite3").write_text("v7", encoding="utf-8")
    monkeypatch_manifest(idx_env, {
        "indexes": {"current": "chroma_v7", "history": ["chroma_v7"]},
        "versions": [{"name": "chroma_v7", "path": str(ver_dir),
                      "corpus_fingerprint": "x", "stats": {}, "built_at": ""}],
    })
    assert iv.resolve_index_dir() == ver_dir


def test_resolve_index_dir_falls_back_when_version_dir_broken(idx_env, caplog):
    monkeypatch_manifest(idx_env, {
        "indexes": {"current": "chroma_v8", "history": ["chroma_v8"]},
        "versions": [{"name": "chroma_v8", "path": str(idx_env / "gone"),
                      "corpus_fingerprint": "x", "stats": {}, "built_at": ""}],
    })
    with caplog.at_level(logging.WARNING, logger="med_safety.index_versioning"):
        got = iv.resolve_index_dir()
    assert got == iv.CHROMA_DIR
    assert any("不完整" in r.getMessage() for r in caplog.records)


def test_index_is_ready_tracks_chroma_sqlite(idx_env):
    assert iv.index_is_ready() is False
    fallback = idx_env / "idx"
    fallback.mkdir(parents=True, exist_ok=True)
    (fallback / "chroma.sqlite3").write_text("x", encoding="utf-8")
    assert iv.index_is_ready() is True


def monkeypatch_manifest(tmp_path, manifest: dict):
    """直接写一份 MANIFEST 到被 patch 过的路径。"""
    import json
    tmp_path.joinpath("manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------
# 2. 空语料不得注册
# ---------------------------------------------------------------
def test_build_index_refuses_empty_corpus(monkeypatch, tmp_path):
    monkeypatch.setattr(iv, "current_version", lambda: None)
    monkeypatch.setattr(retrieval, "iter_all_chunks", lambda *a, **k: iter(()))

    with pytest.raises(RuntimeError, match="语料为空"):
        retrieval.build_index()


def test_build_index_reachable_when_previous_version_exists(monkeypatch):
    """回归：retrieval 曾漏导入 Path —— 只要 MANIFEST 里已有版本，build_index 在
    「指纹是否一致」判断之前就 NameError，导致索引永远无法重建/自愈。"""
    monkeypatch.setattr(iv, "current_version", lambda: {
        "name": "chroma_v1", "path": "D:/nope/chroma_v1",
        "corpus_fingerprint": "old-fingerprint", "stats": {}, "built_at": ""})
    monkeypatch.setattr(retrieval, "iter_all_chunks", lambda *a, **k: iter(()))

    # 能走到语料校验（而不是在 Path(...) 处 NameError）即说明该路径可用
    with pytest.raises(RuntimeError, match="语料为空"):
        retrieval.build_index()


def test_build_index_reuses_when_fingerprint_unchanged(monkeypatch, tmp_path):
    """指纹一致时必须复用现有版本（不得重新分块/重新嵌入）。"""
    ver_dir = tmp_path / "chroma_v9"
    ver_dir.mkdir()
    (ver_dir / "chroma.sqlite3").write_text("x", encoding="utf-8")
    monkeypatch.setattr(iv, "current_version", lambda: {
        "name": "chroma_v9", "path": str(ver_dir),
        "corpus_fingerprint": iv.corpus_fingerprint(),
        "stats": {"chunk_count": 42}, "built_at": ""})
    monkeypatch.setattr(retrieval, "iter_all_chunks",
                        lambda *a, **k: pytest.fail("指纹一致时不应重新构建"))

    assert retrieval.build_index() == 42


# ---------------------------------------------------------------
# 3. 指纹必须覆盖向量空间配置
# ---------------------------------------------------------------
@pytest.fixture()
def corpus_env(tmp_path, monkeypatch):
    """隔离语料目录，便于验证指纹随内容/配置变化。"""
    data = tmp_path / "data"
    (data / "texts").mkdir(parents=True)
    (data / "texts" / "药A.txt").write_text("【适应症】测试", encoding="utf-8")
    (data / "interactions.csv").write_text("drug_a,drug_b\nA,B\n", encoding="utf-8")
    monkeypatch.setattr(iv, "DATA_DIR", data)
    return data


def test_fingerprint_changes_when_corpus_changes(corpus_env):
    before = iv.corpus_fingerprint()
    (corpus_env / "texts" / "药A.txt").write_text("【适应症】改过了", encoding="utf-8")
    assert iv.corpus_fingerprint() != before


def test_fingerprint_changes_with_chunk_config(corpus_env, monkeypatch):
    before = iv.corpus_fingerprint()
    monkeypatch.setattr(config, "CHUNK_MAX_CHARS", config.CHUNK_MAX_CHARS + 100)
    assert iv.corpus_fingerprint() != before, "分块参数变化必须触发重建"


def test_fingerprint_changes_with_embedding_model(corpus_env, monkeypatch):
    before = iv.corpus_fingerprint()
    monkeypatch.setattr(config, "EMBEDDING_MODEL", "BAAI/bge-base-zh-v1.5")
    assert iv.corpus_fingerprint() != before, "嵌入模型变化必须触发重建"


def test_fingerprint_uses_model_name_not_absolute_path(corpus_env, monkeypatch,
                                                       tmp_path):
    """本地模型只取末级目录名：换机器（路径不同）不应无谓重建。"""
    model_dir = tmp_path / "models" / "bge-small-zh-v1.5"
    model_dir.mkdir(parents=True)
    monkeypatch.setattr(config, "EMBEDDING_MODEL", str(model_dir))
    assert iv.fingerprint_config()["embedding_model"] == "bge-small-zh-v1.5"

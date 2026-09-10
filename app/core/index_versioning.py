"""索引版本治理：版本目录管理 + MANIFEST 原子读写 + 语料指纹。

设计要点
--------
- 物理索引目录放 ASCII 路径 ``D:/medsafe_index/chroma_v{n}``：
  chroma-hnswlib(C++) 写 HNSW .bin 无法处理中文路径（见 app/config.py 中
  CHROMA_DIR 注释，且已实测：中文路径仅写出 chroma.sqlite3、无 header.bin）。
- 版本治理 MANIFEST 落在 data/L3_index/build_manifest.json（纯 JSON，中文路径无碍），
  记录 current 指针、版本历史、语料指纹与统计，供巡检与审计。
- 切换/写入使用临时文件 + os.replace 原子替换；构建失败只清理临时目录，
  不触碰 MANIFEST 与已生效版本（失败即自动回滚）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

from app.config import CHROMA_DIR, DATA_DIR, INDEX_ROOT

logger = logging.getLogger("med_safety.index_versioning")

# 物理索引根（必须 ASCII：hnswlib C++ 无法处理中文路径）
# 默认值与 CHROMA_DIR 同源，统一在 app/config.py 定义（此处仅沿用，便于旧代码继续 import）
# 版本治理 MANIFEST（继承 L3 骨架文件，字段向后兼容扩展）
L3_DIR = DATA_DIR / "L3_index"
MANIFEST_PATH = L3_DIR / "build_manifest.json"
_MANIFEST_VERSION = 2

# 参与语料指纹的文件（相对项目 data/ 的路径）
_FINGERPRINT_INPUTS = ("texts", "interactions.csv")


def fingerprint_config() -> Dict[str, object]:
    """影响向量空间的构建配置（指纹必须覆盖，否则换模型/改分块不会重建）。

    嵌入模型用「标识名」而非绝对路径：本地路径随机器变化，纳进去会让同一份
    语料在换机器后无谓重建；同名的本地模型内容变化不在覆盖范围内（如需严格
    校验可另存模型文件哈希）。
    """
    from app.config import CHUNK_MAX_CHARS, COLLECTION_NAME, EMBEDDING_MODEL

    model = str(EMBEDDING_MODEL)
    # 本地目录（.../models/bge-small-zh-v1.5）只取末级目录名，跨机器可比
    model_id = Path(model).name if Path(model).is_dir() else model
    return {
        "embedding_model": model_id,
        "chunk_max_chars": int(CHUNK_MAX_CHARS),
        "collection": COLLECTION_NAME,
    }


def corpus_fingerprint() -> str:
    """索引指纹：构建配置 + data/texts/*.txt + data/interactions.csv 逐文件 sha256 聚合。

    任何源文件内容或向量空间配置（嵌入模型 / 分块上限 / 集合名）变化 ->
    指纹变化 -> 触发重建（同版本重建前置判断）。
    """
    entries: List[str] = [json.dumps(fingerprint_config(), sort_keys=True,
                                     ensure_ascii=False)]
    for rel in _FINGERPRINT_INPUTS:
        p = DATA_DIR / rel
        if p.is_dir():
            files = sorted(p.glob("*.txt"))
        elif p.is_file():
            files = [p]
        else:
            files = []
        for f in files:
            h = hashlib.sha256(f.read_bytes()).hexdigest()
            entries.append(f"{f.relative_to(DATA_DIR).as_posix()}:{h}")
    agg = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()
    return agg


def _read_manifest() -> Dict:
    if MANIFEST_PATH.exists():
        try:
            with open(MANIFEST_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("索引 MANIFEST 损坏（%s），按空清单处理", exc)
    return {"manifest_version": _MANIFEST_VERSION,
            "generated_at": "",
            "indexes": {"current": None, "history": []},
            "versions": [],
            "index_root": str(INDEX_ROOT)}


def _write_manifest(manifest: Dict) -> None:
    """原子写 MANIFEST：临时文件 + os.replace，避免写一半损坏。"""
    L3_DIR.mkdir(parents=True, exist_ok=True)
    manifest["manifest_version"] = _MANIFEST_VERSION
    manifest["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    tmp = MANIFEST_PATH.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MANIFEST_PATH)


def list_versions() -> List[Dict]:
    m = _read_manifest()
    return m.get("versions", [])


def current_version() -> Optional[Dict]:
    """返回当前生效版本条目；无版本或指针失效时返回 None（由调用方回退旧索引）。"""
    m = _read_manifest()
    current = m.get("indexes", {}).get("current")
    if not current:
        return None
    for v in m.get("versions", []):
        if v.get("name") == current:
            return v
    return None


def resolve_index_dir() -> Path:
    """解析当前生效的物理索引目录。

    - MANIFEST 有 current 且目录完整（chroma.sqlite3 存在）-> 返回该版本目录；
    - 否则回退 CHROMA_DIR（与 INDEX_ROOT 同源，兼容未版本化的旧链路），并打警告：
      回退意味着正在使用「非当前版本」的索引，静默回退会让人误以为检索正常。
    """
    cur = current_version()
    if cur:
        d = Path(cur.get("path", ""))
        if d.exists() and (d / "chroma.sqlite3").exists():
            return d
        logger.warning("索引版本 %s 目录不完整（%s），回退 %s；"
                       "建议执行 python scripts/build_index.py 重建",
                       cur.get("name"), d, CHROMA_DIR)
        return CHROMA_DIR

    if (CHROMA_DIR / "chroma.sqlite3").exists():
        logger.warning("未找到生效的索引版本（MANIFEST: %s），正在使用回退目录 %s 中的"
                       "旧索引；如需与当前语料对齐请执行 python scripts/build_index.py",
                       MANIFEST_PATH, CHROMA_DIR)
    return CHROMA_DIR


def index_is_ready() -> bool:
    """当前是否已有可用索引（生效版本目录，或回退目录中的旧索引）。

    统一就绪判据，供 run.py / API lifespan / 评测脚本复用，避免各处各写一份
    "chroma.sqlite3 是否存在" 的判断而出现口径漂移。
    """
    return (resolve_index_dir() / "chroma.sqlite3").exists()


def next_version_number() -> int:
    names = [v.get("name", "") for v in list_versions()]
    nums = [int(n.rsplit("_v", 1)[-1]) for n in names if n.startswith("chroma_v")]
    return (max(nums) + 1) if nums else 1


def set_current(name: str) -> None:
    """原子切换当前指针到指定版本。"""
    m = _read_manifest()
    names = [v.get("name") for v in m.get("versions", [])]
    if name not in names:
        raise ValueError(f"版本 {name} 不存在于 MANIFEST")
    m.setdefault("indexes", {})
    m["indexes"]["current"] = name
    history = m["indexes"].setdefault("history", [])
    if name not in history:
        history.append(name)
    _write_manifest(m)
    logger.info("索引指针已切换: %s", name)


def register_version(name: str, path: str, fingerprint: str,
                     stats: Dict[str, int], built_at: str) -> None:
    """构建成功后把版本写入 MANIFEST 并原子切换 current。"""
    m = _read_manifest()
    m.setdefault("indexes", {})
    m["indexes"].setdefault("history", [])
    versions = m.setdefault("versions", [])
    for i, v in enumerate(versions):
        if v.get("name") == name:
            versions.pop(i)
            break
    versions.append({
        "name": name,
        "path": path,
        "corpus_fingerprint": fingerprint,
        "stats": stats,
        "built_at": built_at,
        "status": "active",
    })
    m["indexes"]["current"] = name
    if name not in m["indexes"]["history"]:
        m["indexes"]["history"].append(name)
    _write_manifest(m)
    logger.info("索引版本已注册并切换: %s (%s)", name, path)


def remove_failed_temp(name: str) -> None:
    """清理构建失败的临时/半成品目录，保留已生效版本不变。"""
    for cand in (INDEX_ROOT / name, INDEX_ROOT / f".tmp_{name}"):
        if cand.exists():
            shutil.rmtree(cand, ignore_errors=True)
            logger.warning("已清理失败索引目录: %s", cand)


def rollback() -> Optional[str]:
    """回滚到上一个版本；无历史版本时返回 None。"""
    m = _read_manifest()
    current = m.get("indexes", {}).get("current")
    history = m.get("indexes", {}).get("history", [])
    if not history or len(history) < 2:
        return None
    if current == history[-1]:
        target = history[-2]
    else:
        idx = history.index(current) if current in history else len(history) - 1
        target = history[idx - 1] if idx > 0 else None
    if target and any(v.get("name") == target for v in m.get("versions", [])):
        set_current(target)
        return target
    return None
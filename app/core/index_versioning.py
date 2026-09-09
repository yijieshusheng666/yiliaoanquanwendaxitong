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

from app.config import DATA_DIR, CHROMA_DIR

logger = logging.getLogger("med_safety.index_versioning")

# 物理索引根（必须 ASCII：hnswlib C++ 无法处理中文路径）
# 可用环境变量 INDEX_ROOT 覆盖（Docker 部署时指向容器内挂载路径）
INDEX_ROOT = Path(os.getenv("INDEX_ROOT", "D:/medsafe_index"))
# 版本治理 MANIFEST（继承 L3 骨架文件，字段向后兼容扩展）
L3_DIR = DATA_DIR / "L3_index"
MANIFEST_PATH = L3_DIR / "build_manifest.json"
_MANIFEST_VERSION = 2

# 参与语料指纹的文件（相对项目 data/ 的路径）
_FINGERPRINT_INPUTS = ("texts", "interactions.csv")


def corpus_fingerprint() -> str:
    """语料指纹：data/texts/*.txt + data/interactions.csv 逐文件 sha256 聚合。

    任何源文件内容变化 -> 指纹变化 -> 触发重建（同版本重建前置判断）。
    """
    entries: List[str] = []
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
    - 否则回退原 CHROMA_DIR（兼容未版本化的旧链路）。
    """
    cur = current_version()
    if cur:
        d = Path(cur.get("path", ""))
        if d.exists() and (d / "chroma.sqlite3").exists():
            return d
        logger.warning("索引版本 %s 目录不完整，回退 %s", cur.get("name"), CHROMA_DIR)
    return CHROMA_DIR


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
"""数据资产目录初始化 + MANIFEST 全仓清单生成（P0 数据治理第一步）。

职责：
- 按数据治理方案建 L0~L4 数据层目录骨架；
- 把旧 data/ 的说明书 txt「复制」到 L0_sources/instructions（只搬不移，旧路径保持可用）；
- 把 ocr_raw 原文复制归档到 L0_sources/ocr_raw（P0 仅存档，不做清洗）；
- 把说明书 txt 原样复制到 L2_corpus/instruction（当前可入库语料，P1 起做清洗）；
- 复制 test_set.json 到 L4_eval/（评测集镜像，P1 起扩展 schema）；
- 生成 MANIFEST.json：全仓每个数据文件的 sha256 + 状态 + 元数据（唯一事实源）。

用法：
  python scripts/init_data_v2.py                 # 建目录 + 复制 + 生成 MANIFEST
  python scripts/init_data_v2.py --manifest-only # 仅重建 MANIFEST（数据变化后刷新）

P0 原则：纯数据治理，不修改 data/texts、interactions.csv、test_set.json、
config.py、run.py 以及 app/ 下任何代码——现有问答链路完全不受影响。

目录约定（目标态）：
  data/L0_sources/{instructions,guidelines,formularies,classics,ocr_raw}
  data/L1_registry/   data/L2_corpus/instruction  data/L3_index/  data/L4_eval/
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"

# ---------- 目标目录骨架（方案 §4.1） ----------
L0 = DATA / "L0_sources"
L0_DIRS = {
    "instructions": "instruction",   # 说明书（现有 102 个 txt 迁入）
    "guidelines": "guideline",       # 指南（zhinan.txt 清洗后迁入，P2）
    "formularies": "formulary",      # 处方集（chufangji.txt 清洗后迁入，P2）
    "classics": "classic",           # 本草纲目等
    "ocr_raw": None,                 # 原始 OCR 文本，只存档不改动
}
L1 = DATA / "L1_registry"            # 药名主数据 + DDI 主表
L2 = DATA / "L2_corpus"              # 清洗后的可入库文档载体
L3 = DATA / "L3_index"               # 版本化索引构建产物与 manifest
L4 = DATA / "L4_eval"                # 评测集

# 旧路径（只读来源，P0 不修改）
TEXT_DIR = DATA / "texts"
OCR_RAW = DATA / "ocr_raw"
INTERACTIONS_CSV = DATA / "interactions.csv"
TEST_SET = DATA / "test_set.json"

MANIFEST_PATH = DATA / "MANIFEST.json"
BUILD_MANIFEST = L3 / "build_manifest.json"

CN_TZ = timezone(timedelta(hours=8))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 16), b""):
            h.update(blk)
    return h.hexdigest()


def _csv_row_count(path: Path) -> int | None:
    """返回 CSV 数据行数（含表头为 row+1）；非 CSV 返回 None。"""
    if path.suffix.lower() != ".csv":
        return None
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return sum(1 for _ in csv.reader(f)) - 1
    except (UnicodeDecodeError, OSError):
        return None


def copy_if_changed(src: Path, dst: Path) -> str:
    """幂等复制：目标存在且哈希一致则跳过（返回 'skip'），否则复制（'copy'）。"""
    if dst.exists() and sha256_file(src) == sha256_file(dst):
        return "skip"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return "copy"


def ensure_dirs() -> list[str]:
    created = []
    for sub in L0_DIRS:
        d = L0 / sub
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))
    for d in (L1, L2 / "instruction", L3, L4):
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(str(d))
    return created


def _sync_txts() -> dict:
    """旧 data/texts -> L0_sources/instructions + L2_corpus/instruction（幂等复制）。"""
    stats = {"source": 0, "to_l0_copy": 0, "to_l0_skip": 0, "to_l2_copy": 0, "to_l2_skip": 0}
    if not TEXT_DIR.exists():
        return stats
    for src in sorted(TEXT_DIR.glob("*.txt")):
        stats["source"] += 1
        d1 = L0 / "instructions" / src.name
        stats["to_l0_copy" if copy_if_changed(src, d1) == "copy" else "to_l0_skip"] += 1
        d2 = L2 / "instruction" / src.name
        stats["to_l2_copy" if copy_if_changed(src, d2) == "copy" else "to_l2_skip"] += 1
    return stats


def _sync_ocr() -> dict:
    """旧 data/ocr_raw -> L0_sources/ocr_raw（只存档，不清洗）。"""
    stats = {"source": 0, "copy": 0, "skip": 0}
    if not OCR_RAW.exists():
        return stats
    for src in sorted(OCR_RAW.glob("*.txt")):
        stats["source"] += 1
        d = L0 / "ocr_raw" / src.name
        stats["copy" if copy_if_changed(src, d) == "copy" else "skip"] += 1
    return stats


def _sync_eval() -> dict:
    """data/test_set.json -> L4_eval/test_set.json（镜像，P1 扩展 schema）。"""
    if not TEST_SET.exists():
        return {"source": 0, "copy": 0, "skip": 0}
    d = L4 / TEST_SET.name
    act = copy_if_changed(TEST_SET, d)
    return {"source": 1, "copy": int(act == "copy"), "skip": int(act == "skip")}


def collect_files() -> list[dict]:
    """扫描目标数据层 + 旧路径，产出文件资产清单（供 MANIFEST 使用）。"""
    files: list[dict] = []

    def reg(path: Path, doc_type: str | None, status: str, note: str):
        if not path.exists():
            return
        item = {
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
            "status": status,
            "note": note,
        }
        if doc_type:
            item["doc_type"] = doc_type
        rows = _csv_row_count(path)
        if rows is not None:
            item["row_count"] = rows
        files.append({"path": path.relative_to(BASE).as_posix(), "meta": item})

    # L0 目标层（active 只读存档）
    for sub, doc_type in L0_DIRS.items():
        d = L0 / sub
        if not d.exists():
            continue
        for p in sorted(d.glob("*.txt")):
            reg(p, doc_type, "active",
                "L0 原始存档，只读" if sub != "ocr_raw" else "OCR 原始文本存档，待清洗（P2）")
    # L1 registry（若有）
    if L1.exists():
        for p in sorted(L1.glob("*.csv")):
            reg(p, None, "active", "L1 主数据（药名主数据 / DDI 主表）")
    # L2 语料
    if (L2 / "instruction").exists():
        for p in sorted((L2 / "instruction").glob("*.txt")):
            reg(p, "instruction", "active", "L2 可入库语料（P1 起做清洗与版本化）")
    # L4 评测集
    if L4.exists():
        for p in sorted(L4.glob("*.json")):
            reg(p, None, "active", "L4 评测集镜像")
    # 旧路径（legacy，旧链路在用；pending，待处理）
    if TEXT_DIR.exists():
        for p in sorted(TEXT_DIR.glob("*.txt")):
            reg(p, "instruction", "legacy", "旧链路使用中（app/core/ingestion.py 读取），P1 迁移后归档")
    reg(INTERACTIONS_CSV, None, "legacy", "旧链路使用中（InteractionDB 精确查询），P1 迁移为 drug_id 关联版")
    reg(TEST_SET, None, "legacy", "旧链路使用中（scripts/evaluate.py 读取），P1 扩展 schema")
    if OCR_RAW.exists():
        for p in sorted(OCR_RAW.glob("*.txt")):
            reg(p, None, "pending", "OCR 原始文本（旧路径），待清洗入库")
    return files


def build_manifest(verbose: bool = True) -> dict:
    """扫描全仓并落盘 MANIFEST.json，返回 summary。"""
    files = collect_files()
    file_map = {}
    for item in files:
        file_map[item["path"]] = item["meta"]
    summary = {
        "total_files": len(files),
        "active": sum(1 for m in file_map.values() if m["status"] == "active"),
        "legacy": sum(1 for m in file_map.values() if m["status"] == "legacy"),
        "pending": sum(1 for m in file_map.values() if m["status"] == "pending"),
        "instructions": sum(1 for m in file_map.values() if m.get("doc_type") == "instruction"),
    }
    manifest = {
        "manifest_version": 1,
        "generated_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
        "summary": summary,
        "files": file_map,
    }
    DATA.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if verbose:
        print(f"[MANIFEST] {len(files)} 个文件已登记 -> {MANIFEST_PATH.relative_to(BASE)}")
        print(f"[MANIFEST] active={summary['active']} legacy={summary['legacy']} "
              f"pending={summary['pending']} 说明书={summary['instructions']}")
    return summary


def _init_build_manifest():
    """L3_index/build_manifest.json 初始模板（索引版本化记录，P1 起写入）。"""
    if BUILD_MANIFEST.exists():
        return
    L3.mkdir(parents=True, exist_ok=True)
    BUILD_MANIFEST.write_text(json.dumps({
        "manifest_version": 1,
        "generated_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
        "indexes": {"current": None, "history": []},
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="数据资产目录初始化 + MANIFEST 生成（P0）")
    ap.add_argument("--manifest-only", action="store_true",
                    help="仅重建 MANIFEST.json（数据变化后刷新），不执行复制")
    args = ap.parse_args()

    if args.manifest_only:
        summary = build_manifest()
        print(f"[OK] MANIFEST 刷新完成，共 {summary['total_files']} 个文件。")
        return

    created = ensure_dirs()
    t = _sync_txts()
    o = _sync_ocr()
    e = _sync_eval()
    _init_build_manifest()
    summary = build_manifest()

    print(f"\n[目录] 新建骨架目录 {len(created)} 个；L0~L4 层就绪。")
    print(f"[txt ] 源 {t['source']} 份 -> L0 复制 {t['to_l0_copy']} 跳过 {t['to_l0_skip']}；"
          f"L2 复制 {t['to_l2_copy']} 跳过 {t['to_l2_skip']}")
    print(f"[ocr ] 源 {o['source']} 份 -> 复制 {o['copy']} 跳过 {o['skip']}")
    print(f"[eval] test_set.json -> L4_eval/ 复制 {e['copy']} 跳过 {e['skip']}")
    print(f"[OK  ] P0 初始化完成，MANIFEST 共登记 {summary['total_files']} 个文件。"
          "旧 data/ 目录与问答链路未做任何修改。")


if __name__ == "__main__":
    main()
"""构建药名主数据 drug_registry.csv（P0 数据治理第二步）。

输入：
  - data/L0_sources/instructions/*.txt（药品展示名 display_name + 分类 category；
    若 P0 第一步未运行则回退 data/texts/*.txt）；
  - data/interactions.csv（DDI 全量药名，保证对账与查询 100% 可映射）。

输出：
  - data/L1_registry/drug_registry.csv（utf-8-sig 含 BOM，Excel 兼容）

字段（方案 §3.1）：
  drug_id     稳定唯一 ID，按 display_name 排序稳定编号 DRUG-0001...（幂等，重复运行结果一致）；
  generic_name 通用名（短名），复用 app/core/interaction_db.short_name 口径，与线上查询完全一致；
  form        剂型，由剂型后缀表推导（如「缓释胶囊」），无后缀留空；
  display_name 展示名（= 说明书文件名，也即现有 txt 主语）；
  aliases     同短名分组内其它 display_name（竖线分隔）：
               同一 short_name 下的多个剂型互为别名，如 布洛芬片/缓释胶囊/混悬液 → 布洛芬；
  category    分类，从 txt 首行「药名（分类）」提取（解热镇痛类/消化系统类/呼吸系统类）；
  note        标注构成来源：txt 载药 / 仅 CSV 出现（补充或真实 DDI 药名，待人工补全）。

用法：
  python scripts/build_drug_registry.py
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.core.interaction_db import _SUFFIXES, short_name  # noqa: E402

DATA = BASE / "data"
L1 = DATA / "L1_registry"
INTERACTIONS_CSV = DATA / "interactions.csv"

TXT_CANDIDATES = [DATA / "L0_sources" / "instructions", DATA / "texts"]
OUT_CSV = L1 / "drug_registry.csv"

# 剂型按长度降序匹配（长剂型优先，如「缓释胶囊」优先于「胶囊」）
FORM_SUFFIXES = tuple(sorted(_SUFFIXES, key=len, reverse=True))

# 尾部括号编号（如「复方对乙酰氨基酚片(II)」）：剂型识别前先剥离
TAIL_BRACKET_RE = re.compile(r"\([IVX]+\)$")


def _strip_tail_bracket(name: str) -> str:
    """剥离尾部罗马数字括号，如 复方对乙酰氨基酚片(II) -> 复方对乙酰氨基酚片。"""
    return TAIL_BRACKET_RE.sub("", name).strip()


def _form_of(display_name: str) -> str:
    base = _strip_tail_bracket(display_name)
    for suffix in FORM_SUFFIXES:
        if base.endswith(suffix) and len(base) > len(suffix):
            return suffix
    return ""


def _generic_of(display_name: str) -> str:
    """通用名：剥离尾部括号编号后取 short_name（剂型已剔除）。"""
    base = _strip_tail_bracket(display_name)
    return short_name(base) if base else short_name(display_name)

# txt 首行「药名（分类）」解析
HEAD_RE = re.compile(r"^(.+?)（([^）]+)）\s*$")


def _find_txt_dir() -> Path | None:
    for d in TXT_CANDIDATES:
        if d.exists():
            return d
    return None


def _parse_head(txt: Path) -> tuple[str, str]:
    """从 txt 首行解析 (display_name, category)；解析失败返回 (文件名, '')。"""
    try:
        first = txt.read_text(encoding="utf-8").splitlines()[0].strip()
        m = HEAD_RE.match(first)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    except (UnicodeDecodeError, OSError, IndexError):
        pass
    return txt.stem, ""


def _csv_names() -> list[str]:
    """interactions.csv 药名全集（去重保序，utf-8-sig 适配 BOM）。"""
    if not INTERACTIONS_CSV.exists():
        return []
    names: set[str] = set()
    with open(INTERACTIONS_CSV, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            names.add(r["drug_a"].strip())
            names.add(r["drug_b"].strip())
    return sorted(names)


def build_registry() -> tuple[list[dict], dict]:
    txt_dir = _find_txt_dir()
    txt_info: dict[str, tuple[str, str]] = {}   # display_name -> (drug_id?, category)
    if txt_dir:
        for p in sorted(txt_dir.glob("*.txt")):
            name, cat = _parse_head(p)
            txt_info.setdefault(name, ("", cat))  # 同名只取首次（display_name 唯一）

    csv_names = _csv_names()
    all_names = sorted(set(txt_info) | set(csv_names))

    # 短名分组：同一 short_name 下的全部 display_name 互为别名
    groups: dict[str, list[str]] = {}
    for name in all_names:
        groups.setdefault(short_name(name), []).append(name)

    rows = []
    for seq, name in enumerate(all_names, start=1):
        short = short_name(name)
        form = _form_of(name)
        cat = txt_info.get(name, ("", ""))[1]
        peers = [n for n in groups[short] if n != name]
        if name in txt_info:
            note = f"txt 说明书载药（模拟数据）"
            if not cat:
                note = "txt 说明书载药，分类待人工补全"
        else:
            note = "仅 CSV 出现的药名（补充/真实 DDI），分类待人工补全"
        rows.append({
            "drug_id": f"DRUG-{seq:04d}",
            "generic_name": _generic_of(name),
            "form": form,
            "display_name": name,
            "aliases": "|".join(peers),
            "category": cat,
            "note": note,
        })

    stats = {
        "total": len(rows),
        "with_txt": len(txt_info),
        "csv_only": len(all_names) - len(txt_info),
        "with_alias_group": sum(1 for r in rows if r["aliases"]),
        "with_category": sum(1 for r in rows if r["category"]),
    }
    return rows, stats


def main():
    rows, stats = build_registry()
    L1.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f, fieldnames=["drug_id", "generic_name", "form", "display_name",
                           "aliases", "category", "note"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OK] drug_registry.csv 已生成 -> {OUT_CSV.relative_to(BASE)}")
    print(f"[统计] 总药名 {stats['total']}（txt 载药 {stats['with_txt']}，仅 CSV {stats['csv_only']}；"
          f"含别名分组 {stats['with_alias_group']}，含分类 {stats['with_category']}）")
    print("[提示] 数据变化后请重跑: python scripts/init_data_v2.py --manifest-only 刷新 MANIFEST。")


if __name__ == "__main__":
    main()
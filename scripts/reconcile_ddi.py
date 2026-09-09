"""DDI 双写对账：txt 内嵌【药物相互作用】 vs interactions.csv 主表（P0 数据治理第三步）。

背景：同一相互作用知识双写并存——
  A. 说明书 txt 的【药物相互作用】章节（内嵌文本，进向量库）；
  B. data/interactions.csv（InteractionDB 精确查询通道）。
两处若风险等级/描述不一致，则回答依据不可自证，必须对账治理。

对账规则（短名归一化复用 interaction_db.short_name，与线上查询口径一致）：
  - 命中且等级一致            -> ok
  - 命中但风险等级不一致       -> conflict（必须修复）
  - 命中等级一致但描述不一致   -> desc_diff（提示复查）
  - txt 内嵌存在、CSV 无此药对 -> txt_only（主表缺漏）

反向检查（载体缺失）：
  - CSV 中 source 标注「XX说明书-药物相互作用」的行，应能在该 txt 内嵌中找到对应药对；
    找不到 -> csv_no_carrier（说明书内嵌缺漏）

输出：
  - outputs/ddi_reconcile_report.json  结构化完整报告
  - outputs/ddi_reconcile_report.txt   人工可读摘要
  - 控制台打印统计

用法：
  python scripts/reconcile_ddi.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.core.interaction_db import short_name  # noqa: E402

DATA = BASE / "data"
TXT_CANDIDATES = [DATA / "L0_sources" / "instructions", DATA / "texts"]
INTERACTIONS_CSV = DATA / "interactions.csv"
OUTPUT_DIR = BASE / "outputs"
REPORT_JSON = OUTPUT_DIR / "ddi_reconcile_report.json"
REPORT_TXT = OUTPUT_DIR / "ddi_reconcile_report.txt"

CN_TZ = timezone(timedelta(hours=8))

# 内嵌条目形如：药名（风险：高）：描述。 多条以「；」连接
EMBED_ITEM_RE = re.compile(r"^(.+?)（风险：(高|中|低)）：(.+?)[。]?$")
# 注意：不能依赖 $ 匹配中间行（默认模式 $ 只匹配字符串末尾），用 [^\n]* 截取到行尾
INTERACTION_SECTION_RE = re.compile(r"【药物相互作用】([^\n]*)")
NO_EVIDENCE_MARK = ("尚无充分证据", "尚未有充分证据")


def _find_txt_dir() -> Path | None:
    for d in TXT_CANDIDATES:
        if d.exists():
            return d
    return None


def load_csv_rows() -> list[dict]:
    """读取 interactions.csv（utf-8-sig 适配 BOM），返回行列表。"""
    if not INTERACTIONS_CSV.exists():
        print(f"[ERROR] 未找到 {INTERACTIONS_CSV}")
        sys.exit(1)
    with open(INTERACTIONS_CSV, encoding="utf-8-sig", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("drug_a", "").strip()]
    return rows


def normalize_desc(text: str) -> str:
    """描述归一化：去空白/全半角标点差异，用于一致性比对。"""
    if not text:
        return ""
    t = re.sub(r"\s+", "", text)
    t = t.replace("，", ",").replace("。", ".").replace("：", ":").replace("（", "(").replace("）", ")")
    return t.rstrip(".").rstrip(",")


def parse_embedded_items(raw: str) -> list[dict]:
    """解析内嵌文本为条目列表：[{partner, level, desc}]；无证据声明忽略。"""
    items: list[dict] = []
    if any(mark in raw for mark in NO_EVIDENCE_MARK):
        return items
    for seg in raw.split("；"):
        seg = seg.strip()
        if not seg:
            continue
        m = EMBED_ITEM_RE.match(seg)
        if m:
            items.append({"partner": m.group(1).strip(), "level": m.group(2),
                          "desc": m.group(3).strip()})
    return items


def load_txt_pairs(txt_dir: Path) -> list[dict]:
    """遍历全部 txt，提取 (main, partner, level, desc, file)。"""
    pairs: list[dict] = []
    for p in sorted(txt_dir.glob("*.txt")):
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            print(f"[WARN] 编码异常，跳过: {p.name}")
            continue
        m = INTERACTION_SECTION_RE.search(text)
        if not m:
            continue
        main = p.stem
        for item in parse_embedded_items(m.group(1)):
            pairs.append({**item, "main": main, "file": p.name})
    return pairs


def main():
    rows = load_csv_rows()
    txt_dir = _find_txt_dir()
    if txt_dir is None:
        print("[ERROR] 未找到说明书 txt 目录（L0_sources/instructions 或 data/texts）")
        sys.exit(1)

    # CSV 短名对索引：frozenset(short_a, short_b) -> rows（与 InteractionDB 同口径）
    pair_index: dict[frozenset, list[dict]] = {}
    for r in rows:
        pair_index.setdefault(
            frozenset([short_name(r["drug_a"]), short_name(r["drug_b"])]), []).append(r)

    txt_pairs = load_txt_pairs(txt_dir)

    ok, conflict, desc_diff, txt_only = [], [], [], []
    for tp in txt_pairs:
        key = frozenset([short_name(tp["main"]), short_name(tp["partner"])])
        matches = pair_index.get(key, [])
        if not matches:
            txt_only.append({
                "main": tp["main"], "partner": tp["partner"],
                "txt_level": tp["level"], "txt_desc": tp["desc"], "file": tp["file"],
            })
            continue
        # 短名 key 可能碰撞（多制剂归一为同一短名），优先按字面药精确匹配；
        # 无字面匹配时回退首条（同 key 下理论唯一，避免漏报）。
        literal = [r for r in matches
                   if frozenset([r["drug_a"], r["drug_b"]])
                   == frozenset([tp["main"], tp["partner"]])]
        csv_row = literal[0] if literal else matches[0]
        if csv_row["risk_level"] != tp["level"]:
            conflict.append({
                "main": tp["main"], "partner": tp["partner"],
                "txt_level": tp["level"], "csv_level": csv_row["risk_level"],
                "txt_desc": tp["desc"], "csv_desc": csv_row["description"],
                "csv_source": csv_row.get("source", ""), "file": tp["file"],
            })
        elif normalize_desc(csv_row["description"]) != normalize_desc(tp["desc"]):
            desc_diff.append({
                "main": tp["main"], "partner": tp["partner"],
                "txt_desc": tp["desc"], "csv_desc": csv_row["description"],
                "file": tp["file"],
            })
        else:
            ok.append({"main": tp["main"], "partner": tp["partner"], "file": tp["file"]})

    # 反向：CSV 声称来自「XX说明书-药物相互作用」的行，检查 txt 内嵌是否确有载体
    txt_key_set = {frozenset([short_name(tp["main"]), short_name(tp["partner"])])
                   for tp in txt_pairs}
    csv_no_carrier = []
    for r in rows:
        src = r.get("source", "")
        if not src.endswith("说明书-药物相互作用"):
            continue
        key = frozenset([short_name(r["drug_a"]), short_name(r["drug_b"])])
        if key not in txt_key_set:
            csv_no_carrier.append({
                "drug_a": r["drug_a"], "drug_b": r["drug_b"],
                "risk_level": r["risk_level"], "source": src,
            })

    summary = {
        "generated_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
        "csv_rows": len(rows),
        "txt_files_checked": len({tp["file"] for tp in txt_pairs}),
        "txt_embedded_pairs": len(txt_pairs),
        "ok": len(ok),
        "conflict": len(conflict),
        "desc_diff": len(desc_diff),
        "txt_only": len(txt_only),
        "csv_no_carrier": len(csv_no_carrier),
    }

    report = {
        "summary": summary,
        "conflicts": conflict,
        "desc_diffs": desc_diff,
        "txt_only": txt_only,
        "csv_no_carrier": csv_no_carrier,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 人工可读摘要
    lines = [
        "=" * 56,
        "DDI 双写对账报告（txt 内嵌 vs interactions.csv）",
        f"生成时间: {summary['generated_at']}",
        "=" * 56,
        f"CSV 主表行数      : {summary['csv_rows']}",
        f"检查 txt 文件数   : {summary['txt_files_checked']}",
        f"txt 内嵌药对总数  : {summary['txt_embedded_pairs']}",
        f"  一致(ok)        : {summary['ok']}",
        f"  等级冲突        : {summary['conflict']}",
        f"  描述不一致      : {summary['desc_diff']}",
        f"  CSV 缺该药对    : {summary['txt_only']}",
        f"CSV 无说明书载体  : {summary['csv_no_carrier']}",
        "",
    ]
    if conflict:
        lines += ["【等级冲突（必须修复）】"]
        for c in conflict[:50]:
            lines.append(f"  - {c['main']} ↔ {c['partner']}（{c['file']}）: "
                         f"txt={c['txt_level']} vs csv={c['csv_level']}")
        if len(conflict) > 50:
            lines.append(f"  ... 其余 {len(conflict) - 50} 条见 JSON 报告")
    if desc_diff:
        lines += ["", "【描述不一致（建议复查）】"]
        for d in desc_diff[:30]:
            lines.append(f"  - {d['main']} ↔ {d['partner']}（{d['file']}）")
    if txt_only:
        lines += ["", f"【CSV 主表缺漏（txt 有、csv 无）共 {len(txt_only)} 条（前 30 条）】"]
        for t in txt_only[:30]:
            lines.append(f"  - {t['main']} ↔ {t['partner']} txt={t['txt_level']}")
    if csv_no_carrier:
        lines += ["", f"【CSV 无说明书载体共 {len(csv_no_carrier)} 条（前 30 条）】"]
        for c in csv_no_carrier[:30]:
            lines.append(f"  - {c['drug_a']} ↔ {c['drug_b']}（{c['source']}）")
    lines += ["", f"完整结构化数据: {REPORT_JSON.relative_to(BASE)}", ""]
    REPORT_TXT.write_text("\n".join(lines), encoding="utf-8")

    print("[OK] DDI 双写对账完成")
    print(f"  一致 {summary['ok']} | 等级冲突 {summary['conflict']} | 描述不一致 {summary['desc_diff']} | "
          f"CSV 缺漏 {summary['txt_only']} | 无载体 {summary['csv_no_carrier']}")
    print(f"[报告] {REPORT_JSON.relative_to(BASE)}")
    print(f"[摘要] {REPORT_TXT.relative_to(BASE)}")
    print("[提示] 数据变化后请重跑: python scripts/init_data_v2.py --manifest-only 刷新 MANIFEST。")


if __name__ == "__main__":
    main()
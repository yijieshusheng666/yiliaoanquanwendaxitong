"""解析 OCR 原始文本 -> 知识库 txt（+ 药物相互作用 CSV）。

输入：data/ocr_raw/chufangji.txt（处方集，按药）、data/ocr_raw/zhinan.txt（指南，按病）
输出：data/texts/<药名|病名>.txt；处方集同时提取相互作用并入 interactions.csv

用法：python scripts/parse_ocr.py
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RAW_DIR = BASE / "data" / "ocr_raw"
TEXT_DIR = BASE / "data" / "texts"
CSV_PATH = BASE / "data" / "interactions.csv"

PAGE_RE = re.compile(r"^=====PAGE \d+=====$")
# 页码/书眉/章标题等噪声行（只过滤「章」书眉；「节」在指南里是疾病标题，需保留）
NOISE = {"国家基本药物处方集", "国家基本药物临床应用指南"}
NOISE_RE = re.compile(r"^第[一二三四五六七八九十百零]+章")
PURE_NUM = re.compile(r"^\d{1,4}$")

# 处方集药条目标记：36-3．双氢青蒿素哌喹片Dihydroartemisinin...
DRUG_ENTRY = re.compile(r"^(\d{1,3}(?:-\d{1,2})?)[．.]\s*([\u4e00-\u9fff]{2,40})")

# 剂量子列表误判药名的常见词（"1．口服" 之类）
NAME_STOP = {"口服", "静脉", "肌内", "外用", "局部", "成人", "儿童", "预防", "治疗",
             "首选", "选用", "一般", "常用", "给药", "用药", "用法", "用量", "感染",
             "严重", "如果", "当发", "出现", "症状", "禁忌", "慎用", "剂量", "疗程"}


def is_plausible_drug(name: str) -> bool:
    return len(name) >= 2 and name not in NAME_STOP

# 指南疾病标记：第九节感染性心内膜炎
DISEASE_ENTRY = re.compile(r"^第[一二三四五六七八九十百零]{1,4}节\s*(.+)$")

SECTION = re.compile(r"【([^】]{2,12})】")


def iter_pages(path: Path):
    """按页返回文本行列表（去掉书眉/页码噪声）。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if PAGE_RE.match(line):
            continue
        s = line.strip()
        if not s or s in NOISE or PURE_NUM.match(s) or NOISE_RE.match(s):
            continue
        yield s


def parse_drug_entries(path: Path):
    """处方集 -> [(药名, 条目全文)]。"""
    entries, cur_name, cur = [], None, []
    for line in iter_pages(path):
        m = DRUG_ENTRY.match(line)
        if m and is_plausible_drug(m.group(2)):
            if cur_name is not None:
                entries.append((cur_name, "\n".join(cur)))
            cur_name, cur = m.group(2), [line]
            continue
        if cur_name is not None:
            cur.append(line)
    if cur_name is not None:
        entries.append((cur_name, "\n".join(cur)))
    return entries


def parse_diseases(path: Path):
    """指南 -> [(病名, 章节全文)]。"""
    entries, cur_name, cur = [], None, []
    for line in iter_pages(path):
        m = DISEASE_ENTRY.match(line)
        if m:
            if cur_name is not None:
                entries.append((cur_name, "\n".join(cur)))
            cur_name, cur = m.group(1).strip(), []
        elif cur_name is not None:
            cur.append(line)
    if cur_name is not None:
        entries.append((cur_name, "\n".join(cur)))
    return entries


def split_sections(text: str) -> dict:
    """条目全文 -> {章节: 内容}。修复 OCR 常见的缺【 的章节标记。"""
    # 规范化：行首形如 "适应证】"、"禁忌证】" 的残缺标记，补上【
    text = re.sub(r"(?m)^([^【\n]{2,8}】)", r"【\1", text)
    sections, cur, buf = {}, None, []
    for line in text.splitlines():
        m = SECTION.search(line)
        if m:
            if cur and "".join(buf).strip():
                sections.setdefault(cur, []).append("".join(buf).strip())
            cur, buf = m.group(1), [SECTION.sub("", line).strip()]
        else:
            if cur is not None:
                buf.append(line)
    if cur and "".join(buf).strip():
        sections.setdefault(cur, []).append("".join(buf).strip())
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def write_txt(name: str, sections: dict, source: str):
    safe = re.sub(r'[\\/:*?"<>|\s]+', "", name)
    fname = TEXT_DIR / f"{safe}.txt"
    body = [f"{safe}（来源：{source}）", "=" * 30]
    for sec, content in sections.items():
        if content:
            body.append(f"【{sec}】{content}")
    fname.write_text("\n".join(body), encoding="utf-8")
    return len(body) > 2


def main():
    TEXT_DIR.mkdir(parents=True, exist_ok=True)

    # ---- 处方集：一药一文件 ----
    n_drug = 0
    all_names: list[str] = []
    drug_interactions: list[tuple] = []
    drug_src = RAW_DIR / "chufangji.txt"
    if drug_src.exists():
        entries = parse_drug_entries(drug_src)
        all_names = [n for n, _ in entries]
        for name, text in entries:
            secs = split_sections(text)
            # 过滤目录/前言伪条目（无【】章节标记）
            if not secs:
                continue
            if write_txt(name, secs, "国家基本药物处方集"):
                n_drug += 1
            if "药物相互作用" in secs:
                mentioned = [n for n in all_names if n != name and n in secs["药物相互作用"]]
                for m in mentioned:
                    drug_interactions.append(
                        (name, m, "中", secs["药物相互作用"], "国家基本药物处方集-药物相互作用"))
        print(f"[parse] 处方集: {len(entries)} 条药, 写入 {n_drug} 个 txt, "
              f"提取 {len(drug_interactions)} 对相互作用")

    # ---- 指南：一病一文件 ----
    n_dis = 0
    zhinan_src = RAW_DIR / "zhinan.txt"
    if zhinan_src.exists():
        for name, text in parse_diseases(zhinan_src):
            secs = split_sections(text)
            if write_txt(name, secs, "国家基本药物临床应用指南（基层部分）"):
                n_dis += 1
        print(f"[parse] 指南: 写入 {n_dis} 个疾病章节 txt")

    # ---- 相互作用并入 CSV ----
    if drug_interactions:
        rows = []
        if CSV_PATH.exists():
            with open(CSV_PATH, encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        existing = {(r["drug_a"], r["drug_b"]) for r in rows}
        added = 0
        for a, b, risk, desc, src in drug_interactions:
            if (a, b) in existing:
                continue
            rows.append({"drug_a": a, "drug_b": b, "risk_level": risk,
                         "description": desc, "source": src})
            existing.add((a, b))
            added += 1
        with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["drug_a", "drug_b", "risk_level",
                                              "description", "source"])
            w.writeheader()
            w.writerows(rows)
        print(f"[parse] interactions.csv: 新增 {added} 对，总计 {len(rows)} 对")


if __name__ == "__main__":
    main()

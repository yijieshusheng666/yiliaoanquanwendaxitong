"""RapidOCR 批量抽取 PDF 文本（针对无有效文本层的扫描版/CID 字体 PDF）。

用法：
  python scripts/ocr_extract.py <name> <pdf路径> [起始页] [结束页]

- 结果写入 data/ocr_raw/<name>.txt，每页以 "=====PAGE N=====" 分隔
- 自动断点续跑：已识别的页会跳过，中断后重跑即可
- <name> 建议用 ASCII（如 chufangji / zhinan），避免路径问题
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

BASE = Path(__file__).resolve().parent.parent
RAW_DIR = BASE / "data" / "ocr_raw"


def ocr_pdf(name: str, pdf: str, start: int = 0, end: int | None = None):
    from rapidocr_onnxruntime import RapidOCR

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_file = RAW_DIR / f"{name}.txt"
    engine = RapidOCR()

    doc = fitz.open(pdf)
    total = len(doc)
    end = total if end is None else min(end, total)

    # 断点续跑：done 为已完成的最后一页（1 起始），start 是 0 起始下标
    done = -1
    if out_file.exists():
        for m in re.finditer(r"^=====PAGE (\d+)=====$", out_file.read_text(encoding="utf-8"), re.M):
            done = max(done, int(m.group(1)))
    start = max(start, done)

    print(f"[ocr] {name}: pages {start+1}..{end} / {total}", flush=True)
    with open(out_file, "a", encoding="utf-8") as f:
        for i in range(start, end):
            pix = doc[i].get_pixmap(dpi=200)
            tmp = RAW_DIR / f"_p{i}.png"
            pix.save(tmp)
            result, _ = engine(str(tmp))
            tmp.unlink(missing_ok=True)
            f.write(f"=====PAGE {i+1}=====\n")
            if result:
                f.write("\n".join(line[1] for line in result))
            f.write("\n")
            if (i + 1) % 20 == 0 or i == end - 1:
                print(f"[ocr] {name} page {i+1}/{end}", flush=True)
    print(f"[ocr] {name} done -> {out_file}", flush=True)


if __name__ == "__main__":
    name, pdf = sys.argv[1], sys.argv[2]
    s = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    e = int(sys.argv[4]) if len(sys.argv) > 4 else None
    ocr_pdf(name, pdf, s, e)

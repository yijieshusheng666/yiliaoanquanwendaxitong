"""PDF 说明书解析与语义分块。

分块规则：按【章节】切分（适应症/用法用量/禁忌/注意事项/药物相互作用/特殊人群用药…），
每个分块携带元数据 drug（药品名）与 section（章节名），供精准检索与溯源展示。
超长章节按句边界二次切分，保证单块长度可控。

说明：说明书同时生成 .txt 副本；当 PDF 文本抽取失败（如字体子集不兼容）时，
自动回退读取 .txt 副本，保证分块流程跨平台稳定。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator, List, Tuple

from app.config import CHUNK_MAX_CHARS, PDF_DIR, TEXT_DIR

SECTION_RE = re.compile(r"【([^】]+)】")

# 无需进入知识库的章节（贮藏信息有用，保留）
SKIP_SECTIONS = {"药品名称", "规格"}


def parse_pdf(path: Path) -> List[Tuple[str, str]]:
    """从 PDF 抽取 [(章节名, 内容)]；抽取失败回退 .txt 副本。"""
    from pypdf import PdfReader

    text_parts = []
    try:
        reader = PdfReader(str(path))
        for page in reader.pages:
            text_parts.append(page.extract_text() or "")
    except Exception:
        text_parts = []
    raw = "\n".join(text_parts)
    if not SECTION_RE.search(raw):
        # 回退到同名的机器可读文本副本
        txt = TEXT_DIR / (path.stem + ".txt")
        if txt.exists():
            raw = txt.read_text(encoding="utf-8")
    return split_sections(raw)


def parse_txt(path: Path) -> List[Tuple[str, str]]:
    return split_sections(path.read_text(encoding="utf-8"))


def split_sections(raw: str) -> List[Tuple[str, str]]:
    """按【章节】标记切分，返回 [(章节名, 内容)]。"""
    if not SECTION_RE.search(raw):
        return [("说明书全文", raw.strip())]
    sections: List[Tuple[str, str]] = []
    current, buf = None, []
    for line in raw.splitlines():
        m = SECTION_RE.search(line)
        if m:
            if current and "".join(buf).strip():
                sections.append((current, "".join(buf).strip()))
            current, buf = m.group(1), [line[m.end():]]
        else:
            buf.append(line)
    if current and "".join(buf).strip():
        sections.append((current, "".join(buf).strip()))
    return sections


def _split_long(text: str, max_chars: int = CHUNK_MAX_CHARS) -> List[str]:
    """按句切分超长内容。"""
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[。；;])", text)
    chunks, buf = [], ""
    for s in sentences:
        if len(buf) + len(s) > max_chars and buf:
            chunks.append(buf)
            buf = s
        else:
            buf += s
    if buf:
        chunks.append(buf)
    return chunks or [text]


def chunk_document(drug: str, sections: List[Tuple[str, str]]) -> List[dict]:
    """药品说明书 -> 分块列表，每块携带 drug / section 元数据。"""
    chunks = []
    for section, content in sections:
        if section in SKIP_SECTIONS:
            continue
        for piece in _split_long(content):
            chunks.append({"drug": drug, "section": section, "text": piece.strip()})
    return chunks


def iter_all_chunks(text_dir: Path = TEXT_DIR) -> Iterator[dict]:
    """遍历知识库全部说明书文本并分块。

    权威输入为 data/texts/*.txt（机器可读文本）：
    - 由 generate_data.py 生成
    - 由 scripts/import_specs.py 导入（权威外部数据，覆盖同名文件后即以权威数据为准）
    PDF 作为附加产物保留，不参与索引构建。
    """
    for txt in sorted(text_dir.glob("*.txt")):
        drug = txt.stem
        sections = parse_txt(txt)
        yield from chunk_document(drug, sections)


def count_documents(text_dir: Path = TEXT_DIR) -> int:
    return len(list(text_dir.glob("*.txt")))

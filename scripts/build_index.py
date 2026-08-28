"""构建向量索引：PDF -> 分块 -> bge-small-zh-v1.5 嵌入 -> Chroma 持久化。

用法：python scripts/build_index.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.ingestion import count_documents  # noqa: E402
from app.core.logging_setup import setup_logging  # noqa: E402
from app.core.retrieval import build_index  # noqa: E402


def main():
    setup_logging()
    n_pdf = count_documents()
    if n_pdf == 0:
        print("[WARN] 未发现说明书文本，先执行: python -m app.data.generate_data")
        return
    n_chunks = build_index()
    print(f"[OK] 已索引 {n_pdf} 份说明书，共 {n_chunks} 个语义分块")


if __name__ == "__main__":
    main()

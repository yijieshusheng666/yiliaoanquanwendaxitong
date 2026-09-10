"""构建向量索引：PDF -> 分块 -> bge-small-zh-v1.5 嵌入 -> 版本化 Chroma 持久化。

用法：
  python scripts/build_index.py                # 版本化构建（数据未变则复用）
  python scripts/build_index.py --force        # 强制重建（即使指纹一致）
  python scripts/build_index.py --list         # 列出全部索引版本
  python scripts/build_index.py --rollback     # 回滚到上一版本
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.index_versioning import (list_versions,   # noqa: E402
                                       resolve_index_dir, rollback)
from app.core.ingestion import count_documents  # noqa: E402
from app.core.logging_setup import setup_logging  # noqa: E402
from app.core.retrieval import build_index  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="版本化向量索引构建")
    parser.add_argument("--force", action="store_true",
                        help="强制重建（忽略语料指纹一致判断）")
    parser.add_argument("--list", action="store_true", help="列出全部索引版本")
    parser.add_argument("--rollback", action="store_true", help="回滚到上一版本")
    args = parser.parse_args()

    setup_logging()

    if args.list:
        versions = list_versions()
        if not versions:
            print("尚无版本化索引。当前生效目录（回退）: " + str(resolve_index_dir()))
            return
        print(f"{'版本':<12}{'分块数':<8}{'指纹':<14}{'构建时间':<26}{'路径'}")
        for v in versions:
            st = v.get("stats", {})
            print(f"{v.get('name',''):<12}{st.get('chunk_count','-'):<8}"
                  f"{v.get('corpus_fingerprint','')[:12]:<14}"
                  f"{v.get('built_at',''):<26}{v.get('path','')}")
        cur = resolve_index_dir()
        print(f"当前生效目录: {cur}")
        return

    if args.rollback:
        target = rollback()
        if target:
            print(f"[OK] 已回滚到版本: {target} -> {resolve_index_dir()}")
        else:
            print("[WARN] 无历史版本可回滚（至少需要两个版本）")
        return

    n_docs = count_documents()
    if n_docs == 0:
        print("[WARN] 未发现说明书文本，先执行: python -m app.data.generate_data")
        return
    n_chunks = build_index(force=args.force)
    print(f"[OK] 已索引 {n_docs} 份说明书，共 {n_chunks} 个语义分块")
    print(f"[OK] 当前索引目录: {resolve_index_dir()}")


if __name__ == "__main__":
    main()

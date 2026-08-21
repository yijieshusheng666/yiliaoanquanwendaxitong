"""下载 bge-small-zh-v1.5 嵌入模型到项目本地 models/ 目录。

优先使用 HuggingFace（可配置 HF_ENDPOINT 镜像），失败时回退 ModelScope。

用法：python scripts/download_model.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TARGET = BASE / "models" / "bge-small-zh-v1.5"

# 缓存目录重定向到项目内（避免写入用户目录/沙箱限制）
os.environ.setdefault("MODELSCOPE_CACHE", str(BASE / "models" / ".modelscope_cache"))
os.environ.setdefault("MODELSCOPE_HOME", str(BASE / "models" / ".modelscope_home"))
os.environ.setdefault("HF_HOME", str(BASE / "models" / ".hf_cache"))


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    if (TARGET / "config.json").exists():
        print(f"[OK] 模型已存在: {TARGET}")
        return

    # 1) HuggingFace 官方 / 镜像（HF_ENDPOINT 可指向 hf-mirror.com）
    try:
        from huggingface_hub import snapshot_download

        print("[1/2] 尝试从 HuggingFace 下载 bge-small-zh-v1.5 ...")
        snapshot_download("BAAI/bge-small-zh-v1.5", local_dir=str(TARGET))
        print(f"[OK] 已下载到 {TARGET}")
        return
    except Exception as exc:
        print(f"[WARN] HuggingFace 下载失败: {type(exc).__name__}: {exc}")

    # 2) ModelScope 回退
    try:
        from modelscope import snapshot_download

        print("[2/2] 回退从 ModelScope 下载 ...")
        snapshot_download("BAAI/bge-small-zh-v1.5", local_dir=str(TARGET))
        print(f"[OK] 已下载到 {TARGET}")
        return
    except Exception as exc:
        print(f"[ERROR] ModelScope 下载失败: {type(exc).__name__}: {exc}")
        print("请手动下载 bge-small-zh-v1.5 后放置到 models/bge-small-zh-v1.5/ 目录。")
        sys.exit(1)


if __name__ == "__main__":
    main()

"""下载 bge-reranker-base 重排模型到项目本地 models/ 目录。

优先走 HuggingFace 国内镜像（hf-mirror.com，可被 HF_ENDPOINT 覆盖）；失败回退 ModelScope。
sentence-transformers 只需一个权重格式（safetensors 优先），故排除冗余的 ONNX 与重复的
pytorch 权重，避免多下载约 2GB。

用法：python scripts/download_reranker.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TARGET = BASE / "models" / "bge-reranker-base"

# 缓存目录重定向到项目内（避免写入用户目录/沙箱限制）
os.environ.setdefault("MODELSCOPE_CACHE", str(BASE / "models" / ".modelscope_cache"))
os.environ.setdefault("MODELSCOPE_HOME", str(BASE / "models" / ".modelscope_home"))
os.environ.setdefault("HF_HOME", str(BASE / "models" / ".hf_cache"))
# HuggingFace 国内镜像（可用官方源覆盖）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# 禁用 Xet 存储后端：hf-mirror 的 Xet CDN（cas-bridge.xethub.hf.co）国内超时，
# 关闭后走传统 LFS 分片，由 hf-mirror 国内 CDN 回源。
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# 冗余文件（glob 风格，相对仓库根目录）：ONNX 导出与重复的 pytorch 权重
_IGNORE = ["*.onnx", "onnx/*", "pytorch_model.bin"]


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    if (TARGET / "config.json").exists() and (TARGET / "model.safetensors").exists():
        print(f"[OK] 模型已存在: {TARGET}")
        return

    # 1) HuggingFace（国内镜像）
    try:
        from huggingface_hub import snapshot_download

        print("[1/2] 尝试从 HuggingFace(hf-mirror) 下载 bge-reranker-base ...")
        snapshot_download("BAAI/bge-reranker-base", local_dir=str(TARGET),
                          ignore_patterns=_IGNORE)
        print(f"[OK] 已下载到 {TARGET}")
        return
    except Exception as exc:
        print(f"[WARN] HuggingFace 下载失败: {type(exc).__name__}: {exc}")

    # 2) ModelScope 回退（其 pattern 为 glob 风格，用 *_IGNORE* 中的通配符匹配）
    try:
        from modelscope import snapshot_download

        print("[2/2] 回退从 ModelScope 下载 ...")
        snapshot_download("BAAI/bge-reranker-base", local_dir=str(TARGET),
                          ignore_patterns=_IGNORE)
        print(f"[OK] 已下载到 {TARGET}")
        return
    except Exception as exc:
        print(f"[ERROR] ModelScope 下载失败: {type(exc).__name__}: {exc}")
        print("请手动下载 bge-reranker-base 后放置到 models/bge-reranker-base/ 目录。")
        sys.exit(1)


if __name__ == "__main__":
    main()
"""一键启动：自动生成数据 + 构建索引 + 启动 API（8000）与 Gradio UI（7860）。

用法：
  python run.py              # 同时启动 API + UI
  python run.py --api-only   # 仅启动 FastAPI
  python run.py --ui-only    # 仅启动 Gradio
"""
from __future__ import annotations

import argparse
import sys
import threading


def ensure_data():
    from app.config import PDF_DIR
    if not list(PDF_DIR.glob("*/*.pdf")):
        print("[1/3] 生成知识库数据（说明书 PDF / 相互作用 CSV / 测试集）...")
        from app.data.generate_data import main as gen_data
        gen_data()
    else:
        print("[1/3] 数据已存在，跳过生成")


def ensure_index():
    from app.config import CHROMA_DIR
    if not (CHROMA_DIR / "chroma.sqlite3").exists():
        print("[2/3] 构建向量索引（首次运行需下载 bge 模型，请耐心等待）...")
        from app.core.retrieval import build_index
        n = build_index()
        print(f"[2/3] 索引构建完成：{n} 个分块")
    else:
        print("[2/3] 向量索引已存在，跳过构建")


def start_gradio():
    from app.ui.gradio_app import build_ui
    print("[3/3] Gradio UI 启动中: http://127.0.0.1:7860")
    build_ui().queue().launch(server_name="0.0.0.0", server_port=7860)


def start_api():
    import uvicorn
    print("[3/3] FastAPI 启动中: http://127.0.0.1:8000/docs")
    uvicorn.run("app.api.server:app", host="0.0.0.0", port=8000, log_level="info")


def main():
    parser = argparse.ArgumentParser(description="医疗安全问答系统一键启动")
    parser.add_argument("--api-only", action="store_true", help="仅启动 FastAPI")
    parser.add_argument("--ui-only", action="store_true", help="仅启动 Gradio")
    args = parser.parse_args()

    ensure_data()
    ensure_index()

    if args.api_only:
        start_api()
    elif args.ui_only:
        start_gradio()
    else:
        threading.Thread(target=start_gradio, daemon=True).start()
        start_api()


if __name__ == "__main__":
    main()

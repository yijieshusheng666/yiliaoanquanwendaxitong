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
    from app.core.index_versioning import index_is_ready
    if index_is_ready():
        print("[2/3] 向量索引已就绪，跳过构建")
        return
    print("[2/3] 构建向量索引（首次运行需下载 bge 模型，请耐心等待）...")
    from app.core.retrieval import build_index
    try:
        n = build_index()
    except RuntimeError as exc:
        # 语料为空等硬错误：宁可启动失败，也不要带着空索引跑（此后会一直答"未找到"）
        print(f"[2/3] 索引构建失败：{exc}")
        sys.exit(1)
    print(f"[2/3] 索引构建完成：{n} 个分块")


def start_gradio():
    from app.config import UI_PORT
    from app.ui.gradio_app import build_ui
    print(f"[3/3] Gradio UI 启动中: http://127.0.0.1:{UI_PORT}")
    build_ui().queue().launch(server_name="0.0.0.0", server_port=UI_PORT)


def start_api():
    import uvicorn
    from app.config import API_PORT
    print(f"[3/3] FastAPI 启动中: http://127.0.0.1:{API_PORT}/docs")
    uvicorn.run("app.api.server:app", host="0.0.0.0", port=API_PORT, log_level="info")


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

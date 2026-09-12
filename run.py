"""一键启动：生成数据 → 构建索引 → 启动 FastAPI（8000）+ 可选前端开发服务器。

用法：
  python run.py                    # 启动 API + 自动打开 Vue 开发服务器（需先 npm install）
  python run.py --api-only         # 仅启动 FastAPI（前端用 dist 静态产物或另行托管）
"""
from __future__ import annotations

import argparse
import subprocess
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
        print(f"[2/3] 索引构建失败：{exc}")
        sys.exit(1)
    print(f"[2/3] 索引构建完成：{n} 个分块")


def start_vite():
    """启动 Vue 开发服务器（后台线程）。"""
    from app.config import BASE_DIR
    frontend = BASE_DIR / "frontend"
    if not (frontend / "node_modules").exists():
        print("[3/3] frontend/node_modules 缺失，先执行 npm install ...")
        subprocess.run(["npm", "install"], cwd=frontend, check=True)
    # 使用指定解释器执行 npm run dev（Windows npm.cmd）
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    print("[3/3] Vue 开发服务器启动中: http://localhost:5173")
    subprocess.run([npm, "run", "dev"], cwd=frontend)


def start_api():
    import uvicorn
    from app.config import API_PORT
    print(f"[3/3] FastAPI 启动中: http://127.0.0.1:{API_PORT}/docs")
    uvicorn.run("app.api.server:app", host="0.0.0.0", port=API_PORT, log_level="info")


def main():
    parser = argparse.ArgumentParser(description="医疗安全问答系统一键启动")
    parser.add_argument("--api-only", action="store_true", help="仅启动 FastAPI（不带前端 dev server）")
    args = parser.parse_args()

    ensure_data()
    ensure_index()

    if args.api_only:
        start_api()
    else:
        threading.Thread(target=start_vite, daemon=True).start()
        start_api()


if __name__ == "__main__":
    main()
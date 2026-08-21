# 医疗安全问答系统 —— 单容器镜像
FROM python:3.11-slim

# 中文字体（生成 PDF 说明书用）
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装 torch CPU 版（避免拉取数 GB 的 CUDA 依赖）
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# 首次启动自动：生成数据 -> 构建索引 -> 启动 API(8000) + Gradio UI(7860)
ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache \
    API_BASE=http://127.0.0.1:8000
EXPOSE 8000 7860

CMD ["python", "run.py"]

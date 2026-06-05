# ============================================================
# StockAI — Dockerfile
# 构建: docker build -t stockai .
# ============================================================

FROM python:3.11-slim

# 系统依赖（curl 用于行情 API 调用）
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝应用代码（由 .dockerignore 过滤）
COPY . .

# 确保运行时目录存在
RUN mkdir -p /app/backend/memory /app/database

# 从 backend 目录启动
WORKDIR /app/backend

ENV ENV=production
ENV PORT=3000

EXPOSE 3000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "3000"]

# =============================================
# AiAgent Dockerfile
# =============================================

FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 依赖以 pyproject.toml 为准（2026-11-17 修复：此前装过时 Flask 栈
# requirements.txt，镜像缺 fastapi/uvicorn 无法运行）
COPY pyproject.toml README.md ./
COPY app/ ./app/
RUN pip install --no-cache-dir .

# 复制运行期文件
COPY config.py .
COPY run.py .

# 创建必要的目录
RUN mkdir -p logs uploads

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV ENVIRONMENT=production

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 启动命令
CMD ["python", "run.py"]

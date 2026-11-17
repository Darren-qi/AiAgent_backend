FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 依赖以 pyproject.toml 为准（阶段修复 2026-11-17：此前装的是过时
# Flask 栈 requirements.txt，镜像里没有 fastapi/uvicorn 根本起不来）。
# 先拷构建元数据+包源码装依赖（层缓存：改业务代码不重装依赖）。
COPY pyproject.toml README.md ./
COPY app/ ./app/
RUN pip install --no-cache-dir . -i https://pypi.tuna.tsinghua.edu.cn/simple

# 运行期文件：config.py（根，gitignore，需随上下文提供）、alembic、run.py 等
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

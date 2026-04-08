FROM python:3.11-slim AS base

WORKDIR /app

# 安装系统依赖（chromadb 需要 build 工具）
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 先复制依赖文件，利用 Docker 缓存
COPY pyproject.toml uv.lock ./

# 安装依赖
RUN uv sync --frozen --no-dev

# 复制项目代码
COPY src/ src/
COPY profiles/ profiles/
COPY scenarios/ scenarios/
COPY tests/ tests/

# 创建输出目录
RUN mkdir -p outputs

# 环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

EXPOSE 8000

# 默认启动 API 服务
CMD ["uv", "run", "uvicorn", "mirrormart.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

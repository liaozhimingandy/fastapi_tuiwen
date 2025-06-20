# 定义镜像的标签
# 参考文档: https://docs.astral.sh/uv/guides/integration/fastapi/#deployment
ARG TAG=3.13-slim

FROM python:${TAG}

# pip镜像源
ENV PIPURL https://mirrors.aliyun.com/pypi/simple/
#ENV PIPURL "https://pypi.org/simple/"

# 安装 uv.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 复制项目文件到容器内.
COPY . /app

# 安装应用依赖.
WORKDIR /app
RUN uv sync --verbose --frozen --no-cache -i ${PIPURL}

# 设置容器启动时的命令，运行 Uvicorn 服务器并启动 FastAPI 应用
CMD ["/app/.venv/bin/fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

# 构建命令
# docker build -t liaozhiming/fastapi_tuiwen:latest .
# 文件格式问题,请保持unix编码;set ff=unix

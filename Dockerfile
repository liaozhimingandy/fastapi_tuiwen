# 定义镜像的标签
# 参考文档: https://docs.astral.sh/uv/guides/integration/fastapi/#deployment
ARG TAG=3.13-slim

FROM python:${TAG}  AS builder-image

# pip镜像源
# ENV PIPURL https://mirrors.aliyun.com/pypi/simple/
ENV PIPURL="https://pypi.org/simple/"

# 官方推荐方式：直接复制 uv 二进制，无需 pip 安装，速度更快
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 统一工作目录
WORKDIR /app

# 先复制依赖文件，充分利用 Docker 层缓存
COPY pyproject.toml uv.lock* ./

# 安装所有依赖到当前目录的 .venv 虚拟环境
RUN uv sync --frozen --no-cache -i ${PIPURL}


FROM python:${TAG}

# 从构建阶段复制完整的虚拟环境
COPY --from=builder-image /app/.venv /app/.venv

# 复制项目文件到容器内.
COPY . /app

# 配置虚拟环境环境变量
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /app
# 设置容器启动时的命令，运行 Uvicorn 服务器并启动 FastAPI 应用
CMD ["fastapi", "run", "main.py", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]

# 构建命令
# docker build -t liaozhiming/fastapi_tuiwen:latest .
# 文件格式问题,请保持unix编码;set ff=unix

# 定义镜像的标签
# 参考文档: https://docs.astral.sh/uv/guides/integration/fastapi/#deployment
ARG TAG=3.13-slim

FROM python:${TAG} as base

# pip镜像源
ENV PIPURL "https://mirrors.aliyun.com/pypi/simple/"
# ENV PIPURL "https://pypi.org/simple/"

# 设置工作目录
WORKDIR /app

# 复制项目依赖文件到容器
COPY pyproject.toml .

# 安装 pdm 及项目依赖
RUN pip install --no-cache-dir uv -i ${PIPURL} --default-timeout=1000 && uv export -o requirements.txt

FROM python:${TAG}

# 复制构建产物
COPY --from=base /app/requirements.txt /app/requirements.txt

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV LANG C.UTF-8
ENV LC_ALL C.UTF-8

# pip镜像源
ENV PIPURL "https://mirrors.aliyun.com/pypi/simple/"
# ENV PIPURL "https://pypi.org/simple/"

# 安装依赖包
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt -i ${PIPURL} --default-timeout=1000

# 复制应用代码到容器
COPY . /app

WORKDIR /app
EXPOSE 8000

# 设置容器启动时的命令，运行 Uvicorn 服务器并启动 FastAPI 应用
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]


# 构建命令
# docker build -t liaozhiming/fastapi_tuiwen:latest .
# 文件格式问题,请保持unix编码;set ff=unix

# 定义镜像的标签
ARG TAG=3.13-slim

FROM python:${TAG} as basic

# 设置环境变量
ENV LANG C.UTF-8
ENV LC_ALL C.UTF-8

# pip镜像源
ENV PIPURL "https://mirrors.aliyun.com/pypi/simple/"
#ENV PIPURL "https://pypi.org/simple/"

# change apt-get mirror
COPY pyproject.toml .

# 安装依赖包
RUN pip3 install --no-cache-dir pdm -i ${PIPURL} --default-timeout=1000 \
    && pdm lock \
    && pdm export -o requirements.txt  --without-hashes \
    && pip3 install --no-cache-dir -r requirements.txt -i ${PIPURL} --default-timeout=1000 \
    && rm -f requirements.txt \
    && rm -f pdm.lock

FROM python:${TAG}

# 设置环境变量
ENV LANG C.UTF-8
ENV LC_ALL C.UTF-8

# 如果python大版本有调整,请调整python的路径,示例: 3.13 -> 调整为对应版本
COPY --from=basic /usr/local/bin /usr/local/bin
COPY --from=basic /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages

RUN mkdir /app
COPY . /app

WORKDIR /app
EXPOSE 8000

# 设置容器启动时的命令，运行 Uvicorn 服务器并启动 FastAPI 应用
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
# 构建命令
# docker build -t liaozhiming/fastapi_tuiwen:latest .
# 文件格式问题,请保持unix编码;set ff=unix

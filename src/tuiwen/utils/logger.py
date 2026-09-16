#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# -------------------------------------------------------------------------------
# @Author      : Administrator
# @Email       : liaozhimingandy@qq.com
# @Date        : 2026/5/26 14:30
# @FileName    : logger.py
# @Description : 全局日志配置(loguru): 控制台彩色输出 + 按天滚动的文件日志
# @Project     : fastapi_tuiwen
# @Copyright   : Copyright (c) 2026 Administrator, All Rights Reserved.
# -------------------------------------------------------------------------------

from loguru import logger
import sys
import os


# 创建 logs 目录(相对启动目录, 容器里注意挂载或改路径)
os.makedirs("logs", exist_ok=True)

# 删除默认日志(去掉 loguru 自带 handler, 完全用下面的自定义配置)
logger.remove()

# ===== 控制台日志 =====
logger.add(
    sys.stdout,
    level="DEBUG",
    colorize=True,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level}</level> | "
        "<magenta>{file}:{line}</magenta> | "  # 文件名:行号（核心！）
        "<yellow>{function}</yellow> | "       # 函数名
        "<cyan>{message}</cyan>"
    )
)

# ===== 文件日志 =====
logger.add(
    "logs/tuiwen_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    level="DEBUG",
    encoding="utf-8",
    enqueue=True,
    format=(
        "{time:YYYY-MM-DD HH:mm:ss} | "
        "{file}:{line} | "  # 文件名:行号（核心！）
        "{function} | "       # 函数名
        "{level} | "
        "{message}"
    )
)


if __name__ == '__main__':
    logger.info("test")

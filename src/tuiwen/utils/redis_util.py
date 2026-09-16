#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： redis_util.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/8/2 19:44
    @Desc: Redis 异步客户端工具: 生命周期(init/close) + 通用读写删 + 业务 Key 生成器
=================================================
"""
from typing import Optional
from redis.asyncio import Redis

from src.tuiwen.core import get_settings
config = get_settings()

# 全局唯一客户端实例, 由 init_redis() 在应用启动时创建
redis_client: Optional[Redis] = None


async def init_redis():
    """初始化全局 Redis 客户端(带 ping 连通性测试, 失败则终止启动)。"""
    global redis_client
    try:
        client = Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            password=config.REDIS_PASSWORD,
            db=config.REDIS_DB,
            decode_responses=True,
            socket_timeout=config.REDIS_SOCKET_TIMEOUT,
            retry_on_timeout=False,
        )
        # 测试连接
        await client.ping()
        redis_client = client
    except Exception:
        # 关键：去掉冗长堆栈，只抛一句话
        raise Exception("Redis 连接失败") from None


async def close_redis():
    """停机时关闭全局 Redis 连接。"""
    if redis_client:
        await redis_client.close()


# ==================== 业务接口（异步 await）====================
async def redis_set(
    key: str,
    value: str | int | float,
    expire: int = None
) -> None:
    """
    通用设置 Redis 键值
    :param key: 键名
    :param value: 值
    :param expire: 过期秒数，不传则不过期
    """
    if expire:
        await redis_client.setex(key, expire, value)
    else:
        await redis_client.set(key, value)


async def redis_get(key: str) -> Optional[str]:
    """
    通用获取 Redis 值
    """
    return await redis_client.get(key)


async def redis_delete(key: str) -> None:
    """
    通用删除 Redis 键
    """
    await redis_client.delete(key)

# ====================== Redis‑Key 公共生成器 ======================
class RedisKey:
    """所有Redis键统一在这里维护(避免业务代码里到处手拼字符串)。"""
    _prefix: str = get_settings().REDIS_KEY_PREFIX

    @classmethod
    def reset_pwd_code(cls, account: str) -> str:
        """密码重置验证码 key(发码与校验两侧必须用同一生成规则, 否则永远校验不通过)。"""
        return f"{cls._prefix}:reset_pwd:account:{account}"

def main(*args, **kwargs) -> None:
    """模块自测入口(当前为空实现)。"""
    pass


if __name__ == "__main__":
    main()

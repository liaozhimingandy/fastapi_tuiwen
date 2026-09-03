#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： redis_util.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/8/2 19:44
    @Desc: 
=================================================
"""
from typing import Optional
from redis.asyncio import Redis

from src.tuiwen.core import get_settings
config = get_settings()

redis_client: Optional[Redis] = None


async def init_redis():
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
    """所有Redis键统一在这里维护"""
    _prefix: str = get_settings().REDIS_KEY_PREFIX

    @classmethod
    def reset_pwd_code(cls, account: str) -> str:
        """密码重置验证码"""
        return f"{cls._prefix}:reset_pwd:account:{account}"

def main(*args, **kwargs) -> None:
    pass


if __name__ == "__main__":
    main()

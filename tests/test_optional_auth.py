"""可选认证依赖(get_optional_account_id)的行为。

用在「允许匿名、但登录后要记录归属」的公开接口上(视频上传)。
关键点: 没令牌或令牌非法都必须降级成匿名(None), 不能抛 401 ——
公开接口不该因为一个过期令牌就整体不可用。
"""
import asyncio
import uuid

from src.tuiwen.dependencies import get_optional_account_id
from src.tuiwen.utils import generate_jwt_token


def test_missing_token_falls_back_to_anonymous():
    assert asyncio.run(get_optional_account_id(None)) is None


def test_invalid_token_falls_back_to_anonymous():
    """格式非法的令牌: 静默降级, 不抛异常。"""
    assert asyncio.run(get_optional_account_id("not-a-jwt")) is None


def test_valid_token_returns_account_id():
    account_id = uuid.uuid7()
    token = generate_jwt_token({"account_id": str(account_id), "salt": "abcdef"},
                               grant_type="access_token")

    assert asyncio.run(get_optional_account_id(token)) == account_id


def test_refresh_token_is_not_accepted_as_access_token():
    """刷新令牌不能当访问令牌用: 类型不符时同样降级为匿名。"""
    account_id = uuid.uuid7()
    token = generate_jwt_token({"account_id": str(account_id), "salt": "abcdef"},
                               grant_type="refresh_token")

    assert asyncio.run(get_optional_account_id(token)) is None

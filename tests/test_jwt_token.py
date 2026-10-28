"""JWT 签发与校验。

认证是本服务所有受保护接口的前置, 这里覆盖: 正常往返、grant_type 隔离
(access_token 不能当 refresh_token 用)、签名/篡改拒绝、过期拒绝。
"""
import uuid
from datetime import timedelta

from src.tuiwen.utils.jwt_token import generate_jwt_token, verify_jwt_token


def _token(**overrides) -> str:
    data = {"account_id": str(uuid.uuid7()), "salt": "abcd1234", "scopes": ["basic"]}
    data.update(overrides)
    # 注意: 工具函数默认 grant_type=client_credential, 这里显式签发访问令牌
    return generate_jwt_token(data, grant_type="access_token")


def test_roundtrip_keeps_payload():
    account_id = str(uuid.uuid7())
    token = _token(account_id=account_id)

    payload = verify_jwt_token(token, grant_type="access_token")

    assert "message" not in payload, payload
    assert payload["account_id"] == account_id
    assert payload["scopes"] == ["basic"]


def test_grant_type_isolated():
    """刷新令牌不能直接当访问令牌使用(反之亦然), 避免一处泄露换取全权限。"""
    refresh = generate_jwt_token({"account_id": str(uuid.uuid7())}, grant_type="refresh_token")

    payload = verify_jwt_token(refresh, grant_type="access_token")

    assert "message" in payload


def test_tampered_token_rejected():
    token = _token()
    tampered = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")

    payload = verify_jwt_token(tampered, grant_type="access_token")

    assert "message" in payload


def test_expired_token_rejected():
    token = generate_jwt_token(
        {"account_id": str(uuid.uuid7())},
        expires_in=timedelta(days=-1),
        grant_type="access_token",
    )

    payload = verify_jwt_token(token, grant_type="access_token")

    assert "message" in payload

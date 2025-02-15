# SECRET_KEY用于JWT令牌签名的随机密钥
import uuid
from datetime import timedelta, datetime

import jwt

from src.tuiwen.config import settings, Settings


def generate_jwt_token(data: dict, settings: Settings = settings, expires_in: timedelta = timedelta(days=1),
                       grant_type: str = 'client_credential') -> dict:
    """

    生成 jwt

    aud: 接收jwt的一方
    exp: jwt的过期时间，这个过期时间必须要大于签发时间
    nbf: 定义在什么时间之前，该jwt都是不可用的.
    iat: jwt的签发时间
    jti: jwt的唯一身份标识，主要用来作为一次性token,从而回避重放攻击。

    :param settings:
    :param grant_type: token类型: client_credential: 认证令牌, access_token: 权限令牌
    :param data: 需要加密的数据
    :param expires_in: 过期时间,默认2小时
    :return:
    """

    payload = {
        "aud": "www.alsoapp.com",
        "iss": "Online JWT Builder",
        "jti": str(uuid.uuid4()).replace('-', ''),
        "iat": datetime.utcnow(),
        "nbf": datetime.utcnow(),
        "exp": datetime.utcnow() + expires_in + timedelta(minutes=30),
        "grant_type": grant_type,
        "version": "2.0",
        "type": "Production"
    }

    payload.update(**data)

    # SECRET_KEY对声明集进行签名的密钥
    # jwt.encode()对声明集进行编码并返回 JWT 字符串。
    return jwt.encode(payload, key=settings.SECRET_KEY, algorithm='HS256')


def verify_jwt_token(data: str, settings: Settings = settings, grant_type: str = "client_credential") -> dict:
    """

    解析jwt token

    :param settings:
    :param grant_type: 校验令牌类型
    :param data: 需要解密的数据
    :return:
    """
    try:
        decode = jwt.decode(data, key=settings.SECRET_KEY, algorithms=['HS256'], audience='www.alsoapp.com')
        assert decode["grant_type"] == grant_type, f'{decode["grant_type"]} != {grant_type}'
    except jwt.ExpiredSignatureError as e:
        return {"message": str(e)}  # Signature has expired
    except jwt.InvalidAudienceError as e:
        return {"message": str(e)}
    except jwt.DecodeError as e:
        return {"message": str(e)}
    except AssertionError as e:
        return {"message": str(e)}
    return decode

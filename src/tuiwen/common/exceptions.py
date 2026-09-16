"""业务异常定义。

约定: Service 层抛出 BizError(或其子类), API 层统一捕获后转 HTTPException,
DAO 层不感知 HTTP 语义。
"""


class BizError(Exception):
    """业务异常，service层抛出。

    Args:
        message: 错误描述(第一个位置参数)
        code: 业务错误码, 默认 400; API 层通常将其作为 HTTP 状态码使用

    NOTE: 参数顺序是 (message, code) —— 与常见的 (code, message) 相反,
          按位置传参时务必注意; 建议调用方一律用关键字传参
    """
    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code
        super().__init__(message)


class EmailAlreadyRegisteredError(BizError):
    """邮箱已注册"""

class UsernameAlreadyUsedError(BizError):
    """用户名占用"""
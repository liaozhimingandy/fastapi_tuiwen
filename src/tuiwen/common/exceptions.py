
class BizError(Exception):
    """业务异常，service层抛出"""
    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code
        super().__init__(message)


class EmailAlreadyRegisteredError(BizError):
    """邮箱已注册"""

class UsernameAlreadyUsedError(BizError):
    """用户名占用"""
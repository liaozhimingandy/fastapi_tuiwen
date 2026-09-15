from sqlmodel import select, or_, func

from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.account.models import Account


class AccountDAO(BaseDAO[Account]):


    async def get_account_by_email_or_username(self, mail: str | None, username: str) -> Account | None:
        """
        查询邮箱(忽略大小写) 或者 用户名(忽略大小写)是否已存在
        返回匹配到的ORM实例，无匹配返回None
        """
        stmt = select(Account).where(
            or_(
                func.lower(Account.mail) == func.lower(mail),
                func.lower(Account.username) == func.lower(username)
            )
        )
        # 使用读库会话
        result = await self._execute(self._get_read_session(), stmt, op="check_exist")
        return result.first()

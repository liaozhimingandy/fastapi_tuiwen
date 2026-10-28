"""
账号数据访问层(AccountDAO)

职责:
    通用 CRUD 由 BaseDAO 提供(读写分离、分页、字段校验), 本类只补充账号相关的专用查询。

分层位置:
    AccountService → AccountDAO → PostgreSQL

事务原则:
    只执行 SQL, 不主动 commit; 提交时机由上层(API/Service)控制。
"""
from sqlmodel import select, or_, func

from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.model.account import Account


class AccountDAO(BaseDAO[Account]):
    model = Account

    async def get_account_by_email_or_username(self, mail: str | None, username: str | None) -> Account | None:
        """
        查询邮箱(忽略大小写) 或者 用户名(忽略大小写)是否已存在
        返回匹配到的ORM实例，无匹配返回None

        Args:
            mail: 邮箱地址, 可为 None(仅按用户名查询)
            username: 用户名

        Returns:
            Account | None: 命中的账号实例, 无匹配返回 None
        """
        # 两侧都转小写比较, 避免大小写差异被绕过唯一性校验
        stmt = select(Account).where(
            or_(
                func.lower(Account.mail) == func.lower(mail),
                func.lower(Account.username) == func.lower(username)
            )
        )
        # 使用读库会话
        result = await self._execute(self._get_read_session(), stmt, op="check_exist")
        return result.first()


    async def search(self, keyword: str, offset: int = 0, limit: int = 10) -> list[Account]:
        cleaned = keyword.strip().lower()
        stmt = select(Account).where(
            or_(Account.username.contains(cleaned), Account.nickname.contains(cleaned))).offset(offset).limit(limit)

        # 使用读库会话
        result = await self._execute(self._get_read_session(), stmt, op="search")
        return result.all()

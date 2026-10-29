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
from src.tuiwen.model.account import Account, AccountTypeEnum


class AccountDAO(BaseDAO[Account]):
    model = Account

    async def get_by_ids(self, account_ids) -> list[Account]:
        """
        按 ID 集合批量查账号

        视频 feed 装配作者信息(昵称/头像)用; 一条 IN 查询, 不随条目数增长。

        Args:
            account_ids: 账号ID列表/集合; 空则直接返回空列表

        Returns:
            list[Account]: 匹配到的账号(可能少于入参, 已删除/不存在的 ID 不返回)

        """
        if not account_ids:
            return []
        statement = select(Account).where(Account.id.in_(list(account_ids)))
        return list((await self.exec_read(statement, "get_accounts_by_ids")).all())

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
        """按关键词模糊搜索账号(用户名/昵称包含关键词, 大小写不敏感)。

        内置/系统账号(user_type=SYSTEM)被排除, 不可被用户搜索到 ——
        官方号、机器人、运营占位账号不应出现在搜索结果里。

        Args:
            keyword: 搜索关键词, 内部去空格转小写
            offset: 分页偏移量
            limit: 每页数量

        Returns:
            list[Account]: 匹配到的普通账号列表
        """
        cleaned = keyword.strip().lower()
        stmt = select(Account).where(
            or_(Account.username.contains(cleaned), Account.nickname.contains(cleaned)),
            # 内置账号不可被搜索: 排除 user_type=SYSTEM(值为 2), NULL 与历史脏数据不误伤
            or_(Account.user_type != AccountTypeEnum.SYSTEM.value, Account.user_type.is_(None)),
        ).offset(offset).limit(limit)

        # 使用读库会话
        result = await self._execute(self._get_read_session(), stmt, op="search")
        return result.all()

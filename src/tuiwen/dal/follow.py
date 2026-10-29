"""
关注数据访问层(FollowDAO)

职责:
    1. 关注/取关/计数等通用 CRUD 复用 BaseDAO
    2. 关注列表 / 粉丝列表: Follow JOIN Account 反查账号资料

分层位置:
    FollowService → FollowDAO → PostgreSQL
"""
from sqlalchemy import select

from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.model.account import Account
from src.tuiwen.model.follow import Follow


class FollowDAO(BaseDAO[Follow]):
    model = Follow

    async def list_followees(self, account_id, offset: int = 0, limit: int = 10) -> list[Account]:
        """「我关注的人」: 该账户正在关注的账号(按关注时间倒序)

        Args:
            account_id: 关注者账户ID
            offset: 偏移量
            limit: 每页数量

        Returns:
            list[Account]: 账号实体列表(响应由 AccountInfo 过滤敏感字段)
        """
        stmt = (
            select(Account)
            .join(Follow, Follow.followee_id == Account.id)
            .where(Follow.follower_id == account_id)
            .order_by(Follow.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._execute(self._get_read_session(), stmt, op="list_followees")
        return list(result.all())

    async def list_followers(self, account_id, offset: int = 0, limit: int = 10) -> list[Account]:
        """「关注我的人」(粉丝): 按关注时间倒序

        Args:
            account_id: 被关注者账户ID
            offset: 偏移量
            limit: 每页数量

        Returns:
            list[Account]: 账号实体列表
        """
        stmt = (
            select(Account)
            .join(Follow, Follow.follower_id == Account.id)
            .where(Follow.followee_id == account_id)
            .order_by(Follow.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._execute(self._get_read_session(), stmt, op="list_followers")
        return list(result.all())

    async def followed_account_ids(self, follower_id, account_ids) -> set:
        """批量查询某用户关注了哪些账号(视频 feed 装配「已关注」态时用)

        Args:
            follower_id: 关注者账户ID; None 表示未登录
            account_ids: 待检查的账号ID集合

        Returns:
            set: 已关注的 account_id 集合
        """
        from sqlalchemy import select as _select

        if follower_id is None or not account_ids:
            return set()
        statement = _select(Follow.followee_id).where(
            Follow.follower_id == follower_id,
            Follow.followee_id.in_(account_ids),
        )
        result = await self.exec_read(statement, "followed_account_ids")
        return {row[0] for row in result.all()}

    async def counts_by_targets(self, account_ids) -> dict:
        """批量统计多个账号的粉丝数/关注数(搜索结果装配 follow 统计时用)

        Args:
            account_ids: 账号ID集合

        Returns:
            dict: {account_id: {"follower_count": int, "followee_count": int}}
        """
        from sqlalchemy import func as _func

        if not account_ids:
            return {}
        counts: dict = {aid: {"follower_count": 0, "followee_count": 0} for aid in account_ids}

        # 粉丝数: 按被关注者分组
        follower_stat = (
            _select(Follow.followee_id, _func.count())
            .where(Follow.followee_id.in_(account_ids))
            .group_by(Follow.followee_id)
        )
        result = await self.exec_read(follower_stat, "count_followers_by_targets")
        for row in result.all():
            counts[row[0]]["follower_count"] = int(row[1])

        # 关注数: 按关注者分组
        followee_stat = (
            _select(Follow.follower_id, _func.count())
            .where(Follow.follower_id.in_(account_ids))
            .group_by(Follow.follower_id)
        )
        result = await self.exec_read(followee_stat, "count_followees_by_targets")
        for row in result.all():
            counts[row[0]]["followee_count"] = int(row[1])

        return counts

"""
快照数据访问层(SnapDAO)

职责:
    1. 通用 CRUD 由 BaseDAO 提供
    2. 补充快照点赞数自增
    3. 补充「按创建时间区间分页」—— 基类 page()/get_list()/count() 只支持等值过滤,
       而「天亮即焚」需要 create_at 的区间条件, 只能在本层用显式 where 实现

分层位置:
    SnapService → SnapDAO → PostgreSQL

事务原则:
    只执行 SQL, 不主动 commit; 提交时机由上层(Service/API)控制。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import func, update
from sqlmodel import select

from src.tuiwen.dal.base import BaseDAO, PageResult
from src.tuiwen.model.snap import Snap


class SnapDAO(BaseDAO[Snap]):
    # 绑定 DAO 对应的 ORM 模型
    model = Snap

    # ---------------------------------------------------------
    # 读操作: 时间区间分页
    # ---------------------------------------------------------
    async def get_list_by_time_range(
            self,
            *,
            start: datetime,
            end: datetime,
            limit: int = 10,
            offset: int = 0,
            order_by: Any = None,
    ) -> list[Snap]:
        """
        按 create_at 左闭右开区间 [start, end) 查询快照列表

        Args:
            start: 区间起点(含)
            end: 区间终点(不含)
            limit: 返回条数, 会被 _safe_page 收敛到 [1, MAX_LIMIT]
            offset: 偏移量, 负数按 0 处理
            order_by: 排序表达式; 为 None 时不排序 —— 不排序时数据库返回顺序不确定,
                      分页会出现重复/漏记录, 分页场景务必显式传入

        Returns:
            list[Snap]: 快照列表, 无匹配返回空列表
        """
        limit, offset = self._safe_page(limit, offset)
        statement = select(Snap).where(Snap.create_at >= start, Snap.create_at < end)
        if order_by is not None:
            statement = statement.order_by(order_by)
        statement = statement.limit(limit).offset(offset)
        return list((await self.exec_read(statement, "get_list_by_time_range")).all())

    async def count_by_time_range(self, *, start: datetime, end: datetime) -> int:
        """
        统计 create_at 落在 [start, end) 内的快照数量(与列表条件必须完全一致)

        Args:
            start: 区间起点(含)
            end: 区间终点(不含)

        Returns:
            int: 记录数, 无匹配返回 0
        """
        statement = (select(func.count()).select_from(Snap)
                     .where(Snap.create_at >= start, Snap.create_at < end))
        # select(func.count()) 是 SelectOfScalar, ScalarResult 上只能用 first() 取标量
        value = await self._execute_scalar(self._get_read_session(), statement, "count_by_time_range")
        return int(value or 0)

    async def page_by_time_range(
            self,
            *,
            start: datetime,
            end: datetime,
            limit: int = 10,
            offset: int = 0,
            order_by: Any = None,
    ) -> PageResult[Snap]:
        """
        按 create_at 左闭右开区间 [start, end) 分页, 返回当前页数据 + 区间内总数

        与基类 page() 的差别仅在过滤条件: 这里用时间区间而不是等值条件,
        其余的 limit/offset 收敛、总数口径、事务行为都与基类保持一致。

        Args:
            start: 区间起点(含)
            end: 区间终点(不含)
            limit: 每页数量
            offset: 偏移量
            order_by: 排序表达式, 分页场景必须传, 否则顺序不确定

        Returns:
            PageResult[Snap]: items 当前页数据, total 区间内符合条件的总数
        """
        items = await self.get_list_by_time_range(
            start=start, end=end, limit=limit, offset=offset, order_by=order_by
        )
        total = await self.count_by_time_range(start=start, end=end)
        return PageResult(items=items, total=total)

    async def inc_snap_like_count(self, pk: int) -> int | None:
        """
        快照点赞数原子自增 1

        使用 SQL 层 like = like + 1 表达式, 依赖数据库行锁保证并发安全,
        避免「读-改-写」导致的更新丢失。

        Args:
            pk: 快照主键 id

        Returns:
            int | None: 自增后的点赞数; 快照不存在时返回 None

        实现说明:
            通过 RETURNING 让数据库把自增后的值直接回传, 不需要再发一条 SELECT;
            注意不能在 update 语句对象上取属性(那样拿到的是 SQL 表达式节点, 不是值)。
            事务上只执行不提交, 由上层统一 commit。
        """
        statement = (update(Snap).where(Snap.id == pk)
                     .values(like=Snap.like + 1)
                     .returning(Snap.like))
        # RETURNING 的结果是行集合, Row 的每一列对应 returning() 里的字段
        rows = (await self.exec_write(statement, "inc_snap_like_count")).all()
        return rows[0][0] if rows else None

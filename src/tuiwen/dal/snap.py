"""
快照数据访问层(SnapDAO)

职责:
    通用 CRUD 由 BaseDAO 提供, 本类补充快照点赞数自增。

分层位置:
    SnapService → SnapDAO → PostgreSQL

事务原则:
    只执行 SQL, 不主动 commit; 提交时机由上层(Service/API)控制。
"""
from sqlalchemy import update

from src.tuiwen.dal.base import BaseDAO
from model.snap import Snap


class SnapDAO(BaseDAO[Snap]):
    # 绑定 DAO 对应的 ORM 模型
    model = Snap

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

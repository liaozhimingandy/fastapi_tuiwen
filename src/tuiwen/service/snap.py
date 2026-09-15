"""
「天亮即焚」快照业务服务层(SnapService)

职责:
    1. 发布快照
    2. 首页最新快照 / 分页列表
    3. 快照点赞数自增

分层位置:
    API → SnapService → SnapDAO → PostgreSQL
"""
from dataclasses import dataclass

from src.tuiwen.dal.snap import SnapDAO
from src.tuiwen.more.models import Snap


@dataclass
class SnapService:
    """快照业务服务。使用 dataclass 便于依赖注入时直接以 dao 关键字构造。"""

    dao: SnapDAO

    async def create_snap(self, snap: Snap):
        """
        发布一条快照

        Args:
            snap: 已组装好的快照实体(含来源IP)

        Returns:
            Snap: 落库后的快照实体(未 commit)
        """
        return await self.dao.create(snap)

    async def get_snaps_latest(self):
        """
        获取最新的 10 条快照(按主键倒序)

        Returns:
            PageResult[Snap]: 快照列表与总数
        """
        return await self.dao.page(limit=10, order_by=Snap.id.desc())

    async def get_snaps(self, limit=10, offset=0):
        """
        分页获取快照列表

        Args:
            limit: 每页数量
            offset: 偏移量

        Returns:
            PageResult[Snap]: 快照列表与总数
        """
        return await self.dao.page(limit=limit, offset=offset)

    async def inc_snaps_like(self, pk: int):
        """
        快照点赞数 +1

        Args:
            pk: 快照主键 id

        Returns:
            int | None: 自增后的点赞数; 快照不存在时返回 None
        """
        return await self.dao.inc_snap_like_count(pk)

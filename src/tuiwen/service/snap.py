from dataclasses import dataclass

from src.tuiwen.dal.snap import SnapDAO
from src.tuiwen.more.models import Snap


@dataclass
class SnapService:
    dao: SnapDAO

    async def create_snap(self, snap: Snap):
        return await self.dao.create(snap)

    async def get_snaps_latest(self):
        return await self.dao.page(limit=10, order_by=-Snap.id)

    async def get_snaps(self, limit=10, offset=0):
        return await self.dao.page(limit=limit, offset=offset)


    async def inc_snaps_like(self, pk: int):
       return await self.dao.inc_snap_like_count(pk)



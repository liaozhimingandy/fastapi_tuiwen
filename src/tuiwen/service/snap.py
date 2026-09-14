from dataclasses import dataclass

from dal.snap import SnapDAO
from more.models import Snap


@dataclass
class SnapService:
    dao: SnapDAO

    async def create_snap(self, snap: Snap):
        return await self.dao.create(snap)

    async def get_snaps_latest(self):
        return await self.dao.page(limit=10, order_by=-Snap.id)

    async def get_snaps(self, limit=10, offset=0):
        return await self.dao.page(limit=limit, offset=offset)

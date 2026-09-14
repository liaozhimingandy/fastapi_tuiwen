from sqlalchemy import update

from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.more.models import Snap


class SnapDAO(BaseDAO[Snap]):
    model = Snap

    async def inc_snap_like_count(self, pk: int) -> int:
        stmt = update(Snap).where(Snap.id == pk).values(
            like=Snap.like + 1
        )
        with self.write_db() as session:

            instance = await session.execute(stmt)
            await session.commit()

            return  instance.like

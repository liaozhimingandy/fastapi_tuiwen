from dal.base import BaseDAO
from more.models import Snap


class SnapDAO(BaseDAO[Snap]):
    model = Snap

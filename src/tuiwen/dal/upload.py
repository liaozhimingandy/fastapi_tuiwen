from dal.base import BaseDAO
from post.models import Image


class UploadDAO(BaseDAO[Image]):
    model = Image

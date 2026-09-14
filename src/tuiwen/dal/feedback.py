from dal.base import BaseDAO
from more.models import Feedback


class FeedbackDAO(BaseDAO[Feedback]):
    model = Feedback

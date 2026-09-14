from src.tuiwen.dal.base import BaseDAO
from src.tuiwen.more.models import Feedback


class FeedbackDAO(BaseDAO[Feedback]):
    model = Feedback

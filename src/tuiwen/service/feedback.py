from dataclasses import dataclass

from src.tuiwen.dal.feedback import FeedbackDAO
from src.tuiwen.more.models import Feedback


@dataclass
class FeedbackService:
    dao: FeedbackDAO

    async def create_feedback(self, feedback: Feedback):
        return await self.dao.create(feedback)
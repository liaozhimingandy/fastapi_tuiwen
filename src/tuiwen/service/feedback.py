from dataclasses import dataclass

from dal.feedback import FeedbackDAO
from more.models import Feedback


@dataclass
class FeedbackService:
    dao: FeedbackDAO

    async def create_feedback(self, feedback: Feedback):
        return await self.dao.create(feedback)
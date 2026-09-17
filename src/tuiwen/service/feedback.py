"""
用户反馈业务服务层(FeedbackService)

职责:
    接收 API 层组装好的反馈实体并落库。

事务说明:
    create_feedback 在 DAO 之后自行 commit(与其它 Service 一致)。

分层位置:
    API → FeedbackService → FeedbackDAO → PostgreSQL
"""
from dataclasses import dataclass

from src.tuiwen.dal.feedback import FeedbackDAO
from src.tuiwen.model.feedback import Feedback


@dataclass
class FeedbackService:
    """反馈业务服务。使用 dataclass 便于依赖注入时直接以 dao 关键字构造。"""

    dao: FeedbackDAO

    async def create_feedback(self, feedback: Feedback):
        """
        新增一条用户反馈

        Args:
            feedback: 已补全服务端字段的反馈实体

        Returns:
            Feedback: 落库后的反馈实体
        """
        instance =  await self.dao.create(feedback)
        await self.dao.write_db.commit()
        await self.dao.write_db.refresh(instance)
        return instance

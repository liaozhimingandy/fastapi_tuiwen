from post.models import Comment
from src.tuiwen.dal.comment import CommentDAO


class CommentService:
    dao: CommentDAO


    async def create(self,comment: Comment):
        return await self.dao.create(comment)

    async def delete(self, comment_id, account_id):
       return await self.dao.delete_by_fields(comment_id=comment_id, account_id=account_id)

    async def get(self, obj_id, obj_type, limit, offset):
        return await self.dao.page(obj_id=obj_id, obj_type=obj_type, limit=limit, offset=offset)

from src.tuiwen.dal.follow import FollowDAO


class FollowService:
    dao: FollowDAO

    async def create(self, obj):
       return await self.dao.create(obj)

    async def delete(self, follower_id, followee_id,):
        return await self.dao.delete_by_fields(follower_id=follower_id, followee_id=followee_id)

    async def get_follow_info_by_id(self, account_id):
        # 粉丝数
        follower_count = await self.dao.count(followee_id=account_id)
        # 正在关注数
        followee_count = await self.dao.count(follower_id=account_id)
        # 是否正在关注
        is_following =  await self.dao.count(follower_id=account_id, followee_id=account_id)
        # 获赞数量
        like_count = 0

        return {"follower_count": follower_count, "followee_count": followee_count,
                "is_following": is_following, "like_count": like_count}
"""
关注业务服务层(FollowService)

职责:
    1. 建立/解除关注关系
    2. 聚合关注相关的统计口径(粉丝数/正在关注数/是否互关/获赞数)

分层位置:
    API → FollowService → FollowDAO → PostgreSQL
"""

from dataclasses import dataclass

from src.tuiwen.common.exceptions import BizError
from src.tuiwen.dal.follow import FollowDAO


@dataclass
class FollowService:
    """关注业务服务。

    使用 dataclass 便于依赖注入时直接以 dao 关键字构造
    (get_follow_service 里是 FollowService(dao=dao))。
    """

    dao: FollowDAO

    async def create(self, obj):
        """
        建立关注关系

        Args:
            obj: 关注关系实体(follower_id / followee_id)

        Returns:
            Follow: 落库后的实体(未 commit)

        NOTE: 没有校验 follower_id != followee_id —— 目前允许用户关注自己,
              自关注会直接污染 get_follow_info_by_id 的 is_following 口径
        NOTE: 用 `except Exception` 把 DAO/DB 异常一律转成 400 BizError, 会把唯一索引冲突
              和真正的数据库故障混为一谈(后者本该是 5xx), 排查时建议区分对待
        """
        try:
            instance = await self.dao.create(obj)
            await self.dao.write_db.commit()
            await self.dao.write_db.refresh(instance)
            return instance
        except Exception as e:
            raise BizError(code=400, message=str(e))

    async def delete(self, follower_id, followee_id, ):
        """
        解除关注关系(硬删除)

        Args:
            follower_id: 关注者账户ID
            followee_id: 被关注者账户ID

        Returns:
            bool: 是否删除到记录

        NOTE: 恒返回 True —— 丢弃了 DAO 的 rowcount, 没关注过也返回成功
        """
        await self.dao.delete_by_fields(follower_id=follower_id, followee_id=followee_id)
        await self.dao.write_db.commit()
        return True

    async def get_follow_info_by_id(self, account_id):
        """
        聚合指定账户的关注相关统计

        Args:
            account_id: 账户ID

        Returns:
            dict: 四个统计字段
                - follower_count: 粉丝数(谁关注了我)
                - followee_count: 正在关注数(我关注了谁)
                - is_following  : 我是否关注了我自己(当前实现为自关注判断)
                - like_count    : 获赞数(暂未实现, 恒为 0)

        NOTE: is_following 的统计条件为 follower_id==followee_id==account_id,
              实际只会命中「自己关注自己」的记录, 若要表达「我是否已关注对方」
              需要额外传入目标账户ID
        NOTE: 上面这个 count 是 int(0/1), 而 api/follow.py 用 FollowCountModel 的
              `is_following: bool` 承接, 靠 pydantic 隐式转换; 一旦自关注记录不止一条
              (count>=2)就会校验失败。改成 bool(...) 或直接 `exists()` 更稳
        NOTE: like_count 硬编码 0, 获赞数尚未实现 —— 若前端已展示该字段, 需补聚合查询
              (tw_post.like 的 sum, 或专门的计数表)
        """
        # 粉丝数
        follower_count = await self.dao.count(followee_id=account_id)
        # 正在关注数
        followee_count = await self.dao.count(follower_id=account_id)
        # 是否正在关注
        is_following = await self.dao.count(follower_id=account_id, followee_id=account_id)
        # 获赞数量
        like_count = 0

        return {"follower_count": follower_count, "followee_count": followee_count,
                "is_following": is_following, "like_count": like_count}

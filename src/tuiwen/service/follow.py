"""
关注业务服务层(FollowService)

职责:
    1. 建立/解除关注关系
    2. 聚合关注相关的统计口径(粉丝数/正在关注数/是否互关/获赞数)

分层位置:
    API → FollowService → FollowDAO → PostgreSQL
"""

from dataclasses import dataclass
import uuid

from sqlalchemy.exc import IntegrityError

from src.tuiwen.common.exceptions import BizError
from src.tuiwen.dal.follow import FollowDAO
from src.tuiwen.dal.like import LikeDAO
from src.tuiwen.dal.notice import NoticeDAO
from src.tuiwen.model.notice import Notice, NoticeType, NoticeTargetType


@dataclass
class FollowService:
    """关注业务服务。

    使用 dataclass 便于依赖注入时直接以 dao 关键字构造
    (get_follow_service 里是 FollowService(dao=dao, like_dao=like_dao))。

    like_dao 用于统计「获赞数」—— 点赞数据在 tw_like 表, 不归 FollowDAO 管;
    为 None 时不查库(仅单测里手动构造服务时会省略)。
    notice_dao 用于关注成功后给被关注者写一条 FOLLOW 通知;
    为 None 时跳过(保持向后兼容, 单测可不注入)。
    """

    dao: FollowDAO
    like_dao: LikeDAO | None = None
    notice_dao: NoticeDAO | None = None

    async def create(self, obj):
        """
        建立关注关系

        Args:
            obj: 关注关系实体(follower_id / followee_id)

        Returns:
            Follow: 落库后的实体(未 commit)

        Raises:
            BizError: 400 —— 关注自己; 409 —— 已经关注过(唯一索引冲突)

        说明: 只把唯一索引冲突转成业务异常, 其它数据库故障继续向上抛(保持 5xx 语义),
              原实现用 `except Exception` 会把真正的库故障也压成 400。
        """
        if obj.follower_id == obj.followee_id:
            raise BizError(code=400, message="不能关注自己")

        try:
            instance = await self.dao.create(obj)
            await self.dao.write_db.commit()
            await self.dao.write_db.refresh(instance)
        except IntegrityError:
            await self.dao.write_db.rollback()
            raise BizError(code=409, message="已经关注过了")

        # 关注成功后给被关注者写一条通知。通知写失败不影响关注本身,
        # 回滚只针对通知这条 INSERT, 不回滚已提交的关注记录。
        if self.notice_dao is not None:
            notice = Notice(
                account_id=obj.followee_id,
                trigger_account_id=obj.follower_id,
                notice_type=NoticeType.FOLLOW,
                target_type=NoticeTargetType.USER,
                target_id=obj.follower_id,
                content={"text": "关注了你"},
            )
            try:
                await self.notice_dao.create(notice)
                await self.notice_dao.write_db.commit()
            except Exception:
                await self.notice_dao.write_db.rollback()

        return instance

    async def list_followees(self, account_id: uuid.UUID, offset: int = 0, limit: int = 10):
        """
        「关注列表」: 该账户正在关注的账号(按关注时间倒序)

        Args:
            account_id: 账户ID
            offset: 偏移量
            limit: 每页数量

        Returns:
            tuple[list[Account], int]: 账号列表与总数
        """
        items = await self.dao.list_followees(account_id, offset=offset, limit=limit)
        total = await self.dao.count(follower_id=account_id)
        return items, total

    async def list_followers(self, account_id: uuid.UUID, offset: int = 0, limit: int = 10):
        """
        「粉丝列表」: 关注该账户的账号(按关注时间倒序)

        Args:
            account_id: 账户ID
            offset: 偏移量
            limit: 每页数量

        Returns:
            tuple[list[Account], int]: 账号列表与总数
        """
        items = await self.dao.list_followers(account_id, offset=offset, limit=limit)
        total = await self.dao.count(followee_id=account_id)
        return items, total

    async def delete(self, follower_id, followee_id, ):
        """
        解除关注关系(硬删除)

        Args:
            follower_id: 关注者账户ID
            followee_id: 被关注者账户ID

        Returns:
            bool: 是否删除到记录(没关注过时为 False)

        NOTE: 原实现丢弃了 DAO 的 rowcount, 恒返回 True。
        """
        affected = await self.dao.delete_by_fields(follower_id=follower_id, followee_id=followee_id)
        await self.dao.write_db.commit()
        return bool(affected)

    async def get_follow_info_by_id(self, account_id, viewer_id=None):
        """
        聚合指定账户的关注相关统计

        Args:
            account_id: 账户ID
            viewer_id: 当前浏览者账户ID; 传入时据此判断"我是否已关注该账户"

        Returns:
            dict: 四个统计字段
                - follower_count: 粉丝数(谁关注了我)
                - followee_count: 正在关注数(我关注了谁)
                - is_following  : 浏览者是否已关注该账户
                - like_count    : 获赞数(该账户的帖子 + 评论被点赞的合计)

        NOTE: 原实现的 is_following 统计条件是 follower_id==followee_id==account_id,
              只会命中「自己关注自己」的记录, 与本字段语义无关; 现在改为按
              (viewer_id → account_id) 判断, 未传 viewer_id 时恒为 False。
        NOTE: like_count 原先硬编码 0(前端拿到的是假值), 现改为由 LikeDAO 实时聚合;
              未注入 like_dao 时返回 0。
        """
        # 粉丝数
        follower_count = await self.dao.count(followee_id=account_id)
        # 正在关注数
        followee_count = await self.dao.count(follower_id=account_id)
        # 浏览者是否已关注该账户
        is_following = False
        if viewer_id is not None:
            is_following = await self.dao.exists(follower_id=viewer_id, followee_id=account_id)
        # 获赞数(帖子 + 评论)
        like_count = 0
        if self.like_dao is not None:
            like_count = await self.like_dao.count_likes_received(account_id)

        return {"follower_count": follower_count, "followee_count": followee_count,
                "is_following": bool(is_following), "like_count": like_count}

"""
「天亮即焚」快照业务服务层(SnapService)

职责:
    1. 发布快照
    2. 首页最新快照 / 分页列表 —— 均只返回「当前有效场次」内的数据
    3. 快照点赞数自增

「场次」口径(天亮即焚的核心业务规则):
    一场快照从当晚 23:00 开闸, 到次日 06:00 焚毁, 即时间窗为 [23:00, 次日 06:00)。
    因此读取接口必须带 created_at 区间条件, 否则会把往年(乃至已焚毁)的历史数据一起返回。
    时间带的划分见 current_snap_session()。

分层位置:
    API → SnapService → SnapDAO → PostgreSQL
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pytz
from sqlalchemy import text

from src.tuiwen import get_settings
from src.tuiwen.dal.base import PageResult
from src.tuiwen.dal.snap import SnapDAO
from src.tuiwen.model.snap import Snap
from src.tuiwen.utils.datetime_utils import business_now, to_business_tz

# =========================================================
# 「天亮即焚」场次窗口常量
# =========================================================
# 当晚开闸时刻(含)。改这里就能调整场次长短, 例如 22 表示 22:00 开闸
SNAP_SESSION_OPEN_HOUR = get_settings().SNAP_SESSION_OPEN_HOUR
# 次日焚毁时刻(不含)。内容在该时刻之后一律不再对外返回
# NOTE: 这里原先误写成 SNAP_SESSION_OPEN_HOUR(复制粘贴), 导致"开闸=焚毁",
#       窗口变成 24 小时, 白天本该返回空列表却仍能读到昨夜内容。
SNAP_SESSION_BURN_HOUR = get_settings().SNAP_SESSION_BURN_HOUR
# 首页最新快照的条数
SNAP_LATEST_LIMIT = 10


def current_snap_session(now: datetime | None = None) -> tuple[datetime, datetime] | None:
    """
    计算「当前时刻所处场次」的时间窗, 返回左闭右开区间 (start, end)。

    划分规则(把跨零点的一段连续夜晚视作同一场):
        1. now >= 23:00        → (今天 23:00, 明天 06:00)  当晚场次进行中
        2. now <  06:00        → (昨天 23:00, 今天 06:00)  仍是昨夜那一场
        3. 06:00 <= now < 23:00 → None                     白天, 无有效场次

    第 3 种情况返回 None 而不是"最近一场": 上一场已在 06:00 焚毁, 再返回就等于
    把已焚毁的内容重新展示出来。调用方拿到 None 应当返回空列表。

    Args:
        now: 用于计算窗口的基准时间; 默认取当前时刻。
             传入 naive 值会先按 UTC 补齐(与库里的口径一致), 再换算到业务时区。

    Returns:
        tuple[datetime, datetime] | None: (开闸时间, 焚毁时间); 白天非场次时间返回 None

    NOTE: 「23:00 / 06:00」是**业务时区**(settings.TIME_ZONE, 默认 Asia/Shanghai)的墙钟时间,
          不是 UTC —— 场次规则面向的是本地用户"晚上刷到天亮"这个行为。
          因此窗口按业务时区构造(tz-aware), 再与 UTC 存储的 created_at 比较;
          两个 aware 时间比较的是同一瞬间, 不需要手动换算。
    """
    tz = pytz.timezone(get_settings().TIME_ZONE)

    def at(day: date, hour: int) -> datetime:
        """把「业务时区的某天某点」变成 aware 时间(用 localize, 避免 DST 边界算错)。"""
        return tz.localize(datetime.combine(day, time(hour=hour)))

    now = to_business_tz(now) if now is not None else business_now()
    today = now.date()

    today_open = at(today, SNAP_SESSION_OPEN_HOUR)
    tomorrow_burn = at(today + timedelta(days=1), SNAP_SESSION_BURN_HOUR)
    yesterday_open = at(today - timedelta(days=1), SNAP_SESSION_OPEN_HOUR)
    today_burn = at(today, SNAP_SESSION_BURN_HOUR)

    if now >= today_open:
        # 已过今晚开闸时刻, 场次横跨到明天清晨
        return today_open, tomorrow_burn
    if now < today_burn:
        # 还没到今晨焚毁时刻, 属于昨夜那一场
        return yesterday_open, today_burn
    # 白天: 内容已焚毁, 下一场尚未开闸
    return None


def _empty_page() -> PageResult[Snap]:
    """构造一个空的分页结果(白天无场次时使用)。"""
    return PageResult(items=[], total=0)


@dataclass
class SnapService:
    """快照业务服务。使用 dataclass 便于依赖注入时直接以 dao 关键字构造。"""

    dao: SnapDAO

    async def create_snap(self, snap: Snap):
        """
        发布一条快照

        Args:
            snap: 已组装好的快照实体(含来源IP)

        Returns:
            Snap: 落库后的快照实体(已 commit)
        """
        instance = await self.dao.create(snap)
        await self.dao.write_db.commit()
        await self.dao.write_db.refresh(instance)
        return instance

    async def get_snaps_latest(self) -> PageResult[Snap]:
        """
        获取当前场次内最新的 10 条快照(按主键倒序)

        只返回 created_at 落在当前场次窗口(默认 23:00 ~ 次日 06:00)内的数据;
        非场次时间(白天)一律返回空列表。

        Returns:
            PageResult[Snap]: 快照列表与总数; 非场次时间为空
        """
        window = current_snap_session()
        if window is None:
            return _empty_page()

        start, end = window
        # 排序必须显式指定: 不排序时数据库返回顺序不确定, 分页会出现重复/漏记录
        return await self.dao.page_by_time_range(
            start=start, end=end, limit=SNAP_LATEST_LIMIT, order_by=Snap.id.desc()
        )

    async def get_snaps(self, limit: int = 10, offset: int = 0) -> PageResult[Snap]:
        """
        分页获取当前场次内的快照列表

        Args:
            limit: 每页数量
            offset: 偏移量

        Returns:
            PageResult[Snap]: 快照列表与总数; 非场次时间为空
        """
        window = current_snap_session()
        if window is None:
            return _empty_page()

        start, end = window
        # 与 get_snaps_latest 保持同一排序, 否则同一场次内两个接口的顺序会不一致
        return await self.dao.page_by_time_range(
            start=start, end=end, limit=limit, offset=offset, order_by=Snap.id.desc()
        )

    async def inc_snaps_like(self, pk: int):
        """
        快照点赞数 +1

        Args:
            pk: 快照主键 id

        Returns:
            int | None: 自增后的点赞数; 快照不存在时返回 None
                         (调用方需自行判断 None, 不要无条件回 success=True)
        """
        _count = await self.dao.inc_snap_like_count(pk)
        await self.dao.write_db.commit()
        return _count

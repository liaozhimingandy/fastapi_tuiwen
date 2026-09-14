#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DAO 基础层
职责:
    1. 数据库 CRUD 封装
    2. 读写分离
    3. 分页查询
    4. 字段合法性校验
    5. SQL 性能监控
    6. 批量操作
不负责:
    1. 业务逻辑
    2. 事务控制
    3. 权限判断
事务原则:
    DAO 只负责执行数据库操作，不主动 commit。
    事务边界由 Service 层控制。
典型调用链:
    API
      ↓
    Service
      ↓
    DAO
      ↓
    PostgreSQL
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Generic, Sequence, TypeVar, cast

from sqlalchemy.inspection import inspect
from sqlmodel import delete, func, select, update
from sqlmodel.ext.asyncio.session import AsyncSession

T = TypeVar("T")


# =========================================================
# 分页结果
# =========================================================
@dataclass(slots=True)
class PageResult(Generic[T]):
    """
    分页查询结果。
    items: 当前页数据
    total: 符合查询条件的总记录数
    """
    items: list[T]
    total: int


# =========================================================
# DAO 基类
# =========================================================
class BaseDAO(Generic[T]):
    """
    DAO 基类。
    子类只需要指定 model:
        class UserDAO(BaseDAO[User]):
            model = User
    """
    model: type[T]
    # 单次查询最大返回数量。防止错误参数导致超大结果集。
    MAX_LIMIT = 10
    # 慢 SQL 阈值，单位：秒。
    SLOW_QUERY_THRESHOLD = 0.5

    def __init__(self, write_db: AsyncSession, read_db: AsyncSession):
        """
        Args:
            write_db: 主库 Session。所有写操作使用主库。
            read_db: 从库 Session。普通查询默认使用从库。
        """
        self.write_db = write_db
        self.read_db = read_db
        # 当前 DAO 实例是否强制从主库查询。不使用类变量，避免不同请求之间相互影响。
        self.force_master = False
        self.logger = logging.getLogger(f"dao.{self.model.__tablename__}")
        # 缓存模型字段，避免每次查询都执行 inspect(self.model)
        self._model_columns = frozenset(col.key for col in inspect(self.model).mapper.column_attrs)

    # =========================================================
    # 基础能力
    # =========================================================
    @property
    def table_name(self) -> str:
        """获取当前 DAO 对应的数据表名。"""
        return self.model.__tablename__

    def _get_read_session(self) -> AsyncSession:
        """获取查询 Session。force_master=True 使用主库，默认走从库"""
        return self.write_db if self.force_master else self.read_db

    def _validate_fields(self, data: dict[str, Any]) -> None:
        """
        校验字段是否真实存在于 Model。
        用于 get_one / get_list / count / partial_update，防止不存在字段生成错误SQL
        """
        if not data:
            return
        invalid_fields = set(data) - self._model_columns
        if invalid_fields:
            raise ValueError(f"{self.table_name} invalid fields: {sorted(invalid_fields)}")

    def _safe_page(self, limit: int, offset: int) -> tuple[int, int]:
        """标准化分页参数 limit[1~MAX_LIMIT], offset>=0"""
        limit = min(max(int(limit), 1), self.MAX_LIMIT)
        offset = max(int(offset), 0)
        return limit, offset

    async def _execute(self, session: AsyncSession, stmt: Any, op: str):
        """
        执行SQL，统一性能监控。只埋点，不吞异常，数据库异常向上抛至Service层。
        """
        start = time.perf_counter()
        exc: Exception | None = None
        try:
            return await session.exec(stmt)
        except Exception as e:
            exc = e
            cost = time.perf_counter() - start
            self.logger.exception("[DAO] database error table=%s op=%s cost=%.3fs", self.table_name, op, cost)
            raise
        finally:
            cost = time.perf_counter() - start
            if exc:
                self.logger.exception(
                    "[DAO] database error table=%s op=%s cost=%.3fs",
                    self.table_name, op, cost
                )
            if cost >= self.SLOW_QUERY_THRESHOLD:
                self.logger.warning("[DAO] slow query table=%s op=%s cost=%.3fs", self.table_name, op, cost)

    # =========================================================
    # 查询
    # =========================================================
    async def get_by_id(self, pk: Any) -> T | None:
        """根据主键查询，force_master=True走主库，默认从库"""
        stmt = select(self.model).where(self.model.id == pk)
        result = await self._execute(self._get_read_session(), stmt, "get_by_id")
        return result.first()

    async def get_one(self, **filters: Any) -> T | None:
        """按条件查询单条，示例 await dao.get_one(user_id=100, status=1)"""
        self._validate_fields(filters)
        stmt = select(self.model).limit(1)
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        result = await self._execute(self._get_read_session(), stmt, "get_one")
        return result.first()

    async def get_list(self, *, limit: int = 20, offset: int = 0, order_by: Any = None, **filters: Any) -> list[T]:
        """条件列表查询，上限MAX_LIMIT"""
        self._validate_fields(filters)
        limit, offset = self._safe_page(limit, offset)
        stmt = select(self.model)
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        stmt = (stmt.limit(limit).offset(offset))
        result = await self._execute(self._get_read_session(), stmt, "get_list")
        return list(cast(list[T], result.all()))

    async def count(self, **filters: Any) -> int:
        """统计符合条件记录数量"""
        self._validate_fields(filters)
        stmt = select(func.count()).select_from(self.model)
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        result = await self._execute(self._get_read_session(), stmt, "count")
        return int(result.one()[0])

    async def page(self, *, limit: int = 20, offset: int = 0, order_by: Any = None, **filters: Any) -> PageResult[T]:
        """分页查询返回PageResult对象"""
        items = await self.get_list(limit=limit, offset=offset, order_by=order_by, **filters)
        total = await self.count(**filters)
        return PageResult(items=items, total=total)

    # =========================================================
    # 写操作，全部不commit，事务交给Service层
    # =========================================================
    async def create(self, obj: T) -> T:
        """新增实体，flush+refresh获取数据库生成字段，不commit"""
        self.write_db.add(obj)
        await self.write_db.flush()
        await self.write_db.refresh(obj)
        return obj

    async def update(self, obj: T) -> T:
        """完整对象更新，obj必须属于write_db会话托管，不commit"""
        self.write_db.add(obj)
        await self.write_db.flush()
        await self.write_db.refresh(obj)
        return obj

    async def partial_update(self, pk: Any, data: dict[str, Any]) -> T | None:
        """主键部分更新，传入字典，不commit；无数据直接返回原对象，不存在返回None"""
        self._validate_fields(data)
        if not data:
            return await self.write_db.get(self.model, pk)
        stmt = update(self.model).where(self.model.id == pk).values(**data).execution_options(synchronize_session="fetch")
        result = await self.write_db.exec(stmt)
        if result.rowcount == 0:
            return None
        return await self.write_db.get(self.model, pk)

    async def delete_by_id(self, pk: Any) -> bool:
        """按主键删除，返回是否删除成功，不commit"""
        stmt = delete(self.model).where(self.model.id == pk)
        result = await self.write_db.exec(stmt)
        return bool(result.rowcount)

    async def bulk_create(self, objs: Sequence[T]) -> Sequence[T]:
        """批量新增，空列表直接返回，不commit"""
        if not objs:
            return objs
        self.write_db.add_all(objs)
        await self.write_db.flush()
        return objs
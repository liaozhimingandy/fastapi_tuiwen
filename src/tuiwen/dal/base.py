#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DAO 基础层(抽象基类)

职责:
    1. 数据库 CRUD 封装
    2. 读写分离(写走主库 write_db, 读默认走从库 read_db, force_master 可切主库)
    3. 分页查询(limit/offset 标准化 + 总数统计)
    4. 字段合法性校验(防止字段名拼错生成错误 SQL)
    5. SQL 性能监控(慢 SQL 埋点 + 异常日志)
    6. 批量操作
不负责:
    1. 业务逻辑
    2. 事务控制
    3. 权限判断

事务原则:
    DAO 只负责执行数据库操作, 不主动 commit。
    写操作只 flush(拿回数据库生成的自增主键/默认值), 事务边界由上层控制。
    事务出口统一收敛在 commit() / rollback(), 且本类内部方法一律不调用。

典型调用链:
    API
      ↓
    Service
      ↓
    DAO
      ↓
    PostgreSQL

子类契约(类定义阶段强制校验):
    继承时必须能确定 ORM 模型, 二选一:
        class UserDAO(BaseDAO[User]):   # 推荐: 从泛型实参自动推导 model
            ...
        class UserDAO(BaseDAO[User]):
            model = User                # 也可以显式声明(可读性更好, 项目现用写法)
    两者都没有 → 类定义时直接抛 TypeError, 不等到运行期才暴露。

全局约定:
    1. 所有表模型的主键字段名统一为 id(基类 get_by_id / partial_update 依赖此约定)
    2. 所有表模型必须声明 __tablename__, 基类据此生成日志 logger 名

与子类相关的常用扩展点:
    _execute / _execute_scalar : 执行语句并统一埋点(需要返回值时用)
    exec_read / exec_write     : 直接执行自定义 SELECT / DML 语句(子类扩写专用)
    _get_read_session          : 取当前应使用的读会话
"""
from __future__ import annotations

import logging
import time
from abc import ABC
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generic, Iterator, Sequence, TypeVar, cast, get_args, get_origin

from sqlalchemy.inspection import inspect
from sqlmodel import delete, func, select, update, exists
from sqlmodel.ext.asyncio.session import AsyncSession

T = TypeVar("T")


# =========================================================
# 模型元信息缓存
# =========================================================
# model -> 该模型全部列名(属性名)集合
# 放在模块级而非实例级: DAO 每个请求都会新建实例, 缓存在实例上等于没缓存
_MODEL_COLUMNS_CACHE: dict[type, frozenset[str]] = {}


def _model_columns(model: type) -> frozenset[str]:
    """
    获取模型全部列名(带缓存)。

    取 column.key(ORM 属性名)而不是 column.name(数据库列名),
    保证与 **filters 传入的 Python 关键字参数一致。
    """
    cached = _MODEL_COLUMNS_CACHE.get(model)
    if cached is None:
        cached = frozenset(col.key for col in inspect(model).mapper.column_attrs)
        _MODEL_COLUMNS_CACHE[model] = cached
    return cached


def _infer_model_from_generic(cls: type) -> type | None:
    """
    从类定义的泛型实参中推导 ORM 模型。

    只解析「形如 BaseDAO[XxxModel]」的直接基类:
        class UserDAO(BaseDAO[User])  →  User
        class MiddleDAO(BaseDAO[T])   →  None(自身仍是泛型中间类, 交由最终子类绑定)

    Args:
        cls: 正在创建的 DAO 子类

    Returns:
        type | None: 推导出的模型类; 推导不出返回 None
    """
    for base in getattr(cls, "__orig_bases__", ()) or ():
        origin = get_origin(base)
        params = get_args(base)
        # 只处理「带一个具体实参」的泛型基类
        if origin is None or len(params) != 1:
            continue
        model = params[0]
        # 仍是 TypeVar 等未具体化的类型参数: 说明该类自身还是泛型, 跳过
        if not isinstance(model, type):
            continue
        if isinstance(origin, type) and issubclass(origin, BaseDAO):
            return model
    return None


# =========================================================
# 分页结果
# =========================================================
@dataclass(slots=True)
class PageResult(Generic[T]):
    """
    分页查询结果。

    items: 当前页数据
    total: 符合查询条件的总记录数(与分页无关, 用于前端计算总页数)
    """
    items: list[T]
    total: int


# =========================================================
# DAO 基类
# =========================================================
class BaseDAO(ABC, Generic[T]):
    """
    DAO 抽象基类。全项目数据访问层的统一基准。

    设计说明:
        1. 继承 ABC 表达「抽象基类」语义; 真正的契约校验由 __init_subclass__ 完成
           —— 因为 model 是类属性而非实例方法, 用 @abstractmethod 表达不了
        2. 只做「通用 CRUD + 读性能埋点」, 任何与具体表相关的 SQL 都放到子类

    子类示例:
        class UserDAO(BaseDAO[User]):
            model = User

            async def get_active_users(self, limit: int = 20) -> list[User]:
                stmt = select(User).where(User.is_active == True)
                return list((await self.exec_read(stmt, "get_active_users")).all())
    """

    # 子类必须绑定的 ORM 模型。类属性(非实例属性), 由 __init_subclass__ 校验/推导。
    model: type[T]

    # 单次查询最大返回数量。兜底防止错误参数(如 limit=10**9)拉爆内存。
    # 取值与对外 API 声明的分页上限(Query(le=100))保持一致; 子类可按需覆盖。
    MAX_LIMIT = 100

    # 慢 SQL 阈值，单位：秒。
    SLOW_QUERY_THRESHOLD = 0.5

    # bulk_create 单批 add/flush 的条数, 避免一次性把超大列表塞进会话。
    BULK_CHUNK_SIZE = 500

    # =========================================================
    # 契约校验 / 实例化
    # =========================================================
    def __init_subclass__(cls, **kwargs: Any) -> None:
        """
        子类创建时校验并补全契约, 让配置错误在 import 阶段就暴露。

        处理顺序:
            1. 未声明 model → 尝试从 BaseDAO[Xxx] 的泛型实参推导
            2. 自身仍是泛型(如 class CacheDAO(BaseDAO[T])) → 跳过, 交由最终子类绑定
            3. 既没声明也推导不出 → TypeError
            4. model 不是 SQLModel 表模型(缺 __tablename__) → TypeError
        """
        super().__init_subclass__(**kwargs)

        if getattr(cls, "model", None) is None:
            inferred = _infer_model_from_generic(cls)
            if inferred is not None:
                cls.model = inferred

        # 自身仍带未绑定的类型参数(如 class MiddleDAO(BaseDAO[T])):
        # 是泛型中间类, 交由最终子类绑定模型
        # 注意用 __dict__ 判断, 避免继承到父类的 __parameters__ 而误判
        if cls.__dict__.get("__parameters__", ()):
            return

        model = getattr(cls, "model", None)
        if model is None:
            raise TypeError(
                f"{cls.__name__} 必须绑定 ORM 模型: "
                f"继承时写成 class {cls.__name__}(BaseDAO[XxxModel]), 或声明 model = XxxModel"
            )
        if not hasattr(model, "__tablename__"):
            raise TypeError(
                f"{cls.__name__}.model 必须是 SQLModel 表模型(需带 __tablename__), 当前为 {model!r}"
            )

    def __init__(self, write_db: AsyncSession, read_db: AsyncSession):
        """
        Args:
            write_db: 主库 Session。所有写操作使用主库。
            read_db: 从库 Session。普通查询默认使用从库。
        """
        model = getattr(type(self), "model", None)
        if model is None:
            raise TypeError(f"{type(self).__name__} 未绑定 ORM 模型, 不能实例化")

        self.write_db = write_db
        self.read_db = read_db
        # 当前 DAO 实例是否强制从主库查询。不使用类变量，避免不同请求之间相互影响。
        self.force_master = False
        self.logger = logging.getLogger(f"dao.{model.__tablename__}")
        # 字段名集合(模块级缓存), 避免每次实例化都执行 inspect(model)
        self._model_columns = _model_columns(model)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} table={self.model.__tablename__} force_master={self.force_master}>"

    # =========================================================
    # 基础能力
    # =========================================================
    @property
    def table_name(self) -> str:
        """获取当前 DAO 对应的数据表名。"""
        return self.model.__tablename__

    def _get_read_session(self) -> AsyncSession:
        """
        获取查询 Session。

        force_master=True(或在 use_master() 上下文内)走主库, 默认走从库。
        「写后立即读」的场景必须切主库, 否则可能因主从复制延迟读到旧数据。
        """
        return self.write_db if self.force_master else self.read_db

    @contextmanager
    def use_master(self) -> Iterator["BaseDAO[T]"]:
        """
        临时强制查询走主库的上下文管理器, 退出时自动复位。

        比手工改 force_master 安全: 即使中间抛异常也能恢复, 不会污染同一请求内的后续查询。

        example:
            with dao.use_master():
                account = await dao.get_by_unique_field("id", account_id)
        """
        previous = self.force_master
        self.force_master = True
        try:
            yield self
        finally:
            self.force_master = previous

    def _validate_field_names(self, *field_names: str) -> None:
        """
        校验若干字段名是否真实存在于 Model。

        Raises:
            ValueError: 存在模型上不存在的字段
        """
        invalid = [name for name in field_names if name not in self._model_columns]
        if invalid:
            raise ValueError(f"{self.table_name} invalid fields: {sorted(invalid)}")

    def _validate_fields(self, data: dict[str, Any]) -> None:
        """
        校验字典的键是否都真实存在于 Model。
        用于 get_one / get_list / count / partial_update / delete_by_fields,
        防止不存在的字段被拼进 SQL。
        """
        if not data:
            return
        self._validate_field_names(*data)

    def _safe_page(self, limit: int, offset: int) -> tuple[int, int]:
        """
        标准化分页参数: limit 收敛到 [1, MAX_LIMIT], offset 收敛到 >= 0。

        limit 被截断时记 warning —— 静默截断会让调用方误以为已经拿到全部数据。
        """
        raw_limit = int(limit)
        limit = min(max(raw_limit, 1), self.MAX_LIMIT)
        if limit != raw_limit:
            self.logger.warning(
                "[DAO] limit clamped table=%s request=%s -> %s (MAX_LIMIT=%s)",
                self.table_name, raw_limit, limit, self.MAX_LIMIT,
            )
        offset = max(int(offset), 0)
        return limit, offset

    # =========================================================
    # SQL 执行 + 监控
    # =========================================================
    async def _execute(self, session: AsyncSession, stmt: Any, op: str):
        """
        执行 SQL, 统一性能监控。

        只埋点, 不吞异常: 数据库异常记日志后原样上抛, 由 Service / API 层决定如何响应。
        耗时无论成功失败都会与 SLOW_QUERY_THRESHOLD 比较。

        Args:
            session: 已选定的会话(读用 _get_read_session(), 写用 write_db)
            stmt: SQLAlchemy / SQLModel 语句
            op: 操作名, 仅用于日志定位

        Returns:
            session.exec() 的原始结果, 具体类型取决于 stmt:
                SelectOfScalar → ScalarResult  (select(Model) / select(func.count()))
                Select         → TupleResult
                UpdateBase     → CursorResult  (update() / delete(), 通过 .rowcount 取影响行数)
        """
        start = time.perf_counter()
        try:
            result = await session.exec(stmt)
        except Exception:
            cost = time.perf_counter() - start
            self.logger.exception(
                "[DAO] database error table=%s op=%s cost=%.3fs", self.table_name, op, cost
            )
            raise

        cost = time.perf_counter() - start
        if cost >= self.SLOW_QUERY_THRESHOLD:
            self.logger.warning(
                "[DAO] slow query table=%s op=%s cost=%.3fs", self.table_name, op, cost
            )
        return result

    async def _execute_scalar(self, session: AsyncSession, stmt: Any, op: str) -> Any:
        """
        执行 SQL 并返回第一行第一列(标量)。

        面向 count / exists 这类单值查询: 语句为 SelectOfScalar 时
        session.exec 直接返回 ScalarResult, 这里统一取首个值。

        Returns:
            标量值; 无结果时返回 None
        """
        result = await self._execute(session, stmt, op)
        return result.first()

    async def exec_read(self, stmt: Any, op: str = "read") -> Any:
        """
        直接执行一条自定义查询语句(子类扩写专用), 统一埋点。

        自动走 _get_read_session(): 默认从库, force_master 时走主库。

        example:
            stmt = select(User).where(User.is_active == True)
            rows = (await self.exec_read(stmt, "list_active")).all()
        """
        return await self._execute(self._get_read_session(), stmt, op)

    async def exec_write(self, stmt: Any, op: str = "write") -> Any:
        """
        直接执行一条自定义写语句(DELETE / UPDATE / INSERT), 统一埋点。

        只执行不提交, 与其它写方法保持一致。
        返回值对 DML 是 CursorResult, 可通过 .rowcount 取影响行数。

        example:
            stmt = delete(Like).where(Like.target_id == target_id, Like.account_id == account_id)
            affected = (await self.exec_write(stmt, "delete_like")).rowcount
        """
        return await self._execute(self.write_db, stmt, op)

    # =========================================================
    # 查询
    # =========================================================
    async def get_by_id(self, pk: Any) -> T | None:
        """
        根据主键查询。

        Args:
            pk: 主键值(本项目约定主键字段名为 id)

        Returns:
            T | None: 命中返回实体, 否则 None
        """
        stmt = select(self.model).where(self.model.id == pk)
        result = await self._execute(self._get_read_session(), stmt, "get_by_id")
        return result.first()

    async def get_by_unique_field(self, field_name: str, value: Any) -> T | None:
        """
        根据【单个唯一索引字段】查询单条记录，走读库。

        Args:
            field_name: 模型字段名，如 "id"、"account_id"、"file_md5"
            value: 字段值

        Returns:
            T | None: 命中返回实体, 否则 None

        Raises:
            ValueError: field_name 不是模型字段
            MultipleResultsFound: 该字段实际不唯一且匹配到多行

        注意: select(Model) 得到的是 SelectOfScalar, session.exec 返回 ScalarResult,
              标量结果集上只有 one_or_none(), 没有 scalar_one_or_none()。
        """
        self._validate_field_names(field_name)
        stmt = select(self.model).where(getattr(self.model, field_name) == value)
        result = await self._execute(self._get_read_session(), stmt, f"get_by_unique_field:{field_name}")
        return result.one_or_none()

    async def get_by_fields(self, **kwargs: Any) -> T | None:
        """
        多字段等值联合查询，用于【联合唯一索引】，最多返回一条，走读库。

        example: get_by_fields(target_id="xxx", account_id=123, target_type=1)

        Returns:
            T | None: 命中返回实体, 否则 None

        Raises:
            ValueError: 存在模型上不存在的字段
            MultipleResultsFound: 组合条件实际不唯一且匹配到多行
        """
        self._validate_fields(kwargs)
        stmt = select(self.model)
        for field_name, val in kwargs.items():
            stmt = stmt.where(getattr(self.model, field_name) == val)
        result = await self._execute(self._get_read_session(), stmt, "get_by_fields")
        return result.one_or_none()

    async def get_one(self, **filters: Any) -> T | None:
        """
        按条件查询单条(命中多条时只取无序的第一条)。

        example: await dao.get_one(user_id=100, status=1)

        Args:
            **filters: 等值过滤条件, 字段名必须真实存在于 Model

        Returns:
            T | None: 命中返回实体, 否则 None

        注意: 无 order_by, 命中多条时返回哪一条由数据库决定; 需要确定性顺序时
              请改用 get_list(order_by=...) 取第一条。
        """
        self._validate_fields(filters)
        stmt = select(self.model).limit(1)
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        result = await self._execute(self._get_read_session(), stmt, "get_one")
        return result.first()

    async def get_list(self, *, limit: int = 20, offset: int = 0, order_by: Any = None, **filters: Any) -> list[T]:
        """
        条件列表查询。

        Args:
            limit: 返回条数, 会被 _safe_page 收敛到 [1, MAX_LIMIT]
            offset: 偏移量, 负数按 0 处理
            order_by: 排序表达式, 如 desc(User.created_at) / User.id.desc(); 为 None 时不排序
                      (注意: 不要写 -User.id, SQLAlchemy 会把它编译成算术取负 `ORDER BY -id`,
                       而不是降序; 对字符/时间列是错误语义, 且用不上索引)
            **filters: 等值过滤条件

        Returns:
            list[T]: 实体列表, 无匹配返回空列表
        """
        self._validate_fields(filters)
        limit, offset = self._safe_page(limit, offset)
        stmt = select(self.model)
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        stmt = stmt.limit(limit).offset(offset)
        result = await self._execute(self._get_read_session(), stmt, "get_list")
        return list(cast(list[T], result.all()))

    async def count(self, **filters: Any) -> int:
        """
        统计符合条件记录数量。

        Args:
            **filters: 等值过滤条件; 不传表示统计全表

        Returns:
            int: 记录数, 表内无数据时返回 0
        """
        self._validate_fields(filters)
        stmt = select(func.count()).select_from(self.model)
        for field, value in filters.items():
            stmt = stmt.where(getattr(self.model, field) == value)
        result = await self._execute(self._get_read_session(), stmt, "count")
        return int(result.one())

    async def page(self, *, limit: int = 20, offset: int = 0, order_by: Any = None, **filters: Any) -> PageResult[T]:
        """
        分页查询: 返回当前页数据 + 符合条件的总数。

        内部是两条 SQL(get_list + count), 条件必须完全一致, 因此共用同一组 filters。

        Args:
            limit: 每页数量
            offset: 偏移量
            order_by: 排序表达式
            **filters: 等值过滤条件

        Returns:
            PageResult[T]: items 当前页数据, total 符合条件的总数
        """
        items = await self.get_list(limit=limit, offset=offset, order_by=order_by, **filters)
        total = await self.count(**filters)
        return PageResult(items=items, total=total)

    async def exists(self, **filters: Any) -> bool:
        """
        判断是否存在满足条件的记录(只查存在性, 比 count 更轻量)。

        生成 SQL 形如: SELECT EXISTS (SELECT t.id FROM t WHERE ...)

        Args:
            **filters: 等值过滤条件, 字段名必须真实存在于 Model;
                       不传表示「表内是否存在任意记录」

        Returns:
            bool: True 表示存在至少一条记录
        """
        self._validate_fields(filters)
        inner = select(self.model.id)
        for field, value in filters.items():
            inner = inner.where(getattr(self.model, field) == value)
        # SelectOfScalar → ScalarResult, 取首个标量即为 EXISTS 的布尔结果
        value = await self._execute_scalar(self._get_read_session(), select(exists(inner)), "exists")
        return bool(value)

    # =========================================================
    # 写操作: 一律只用 write_db(主库), 且只 flush 不 commit
    # =========================================================
    async def create(self, obj: T) -> T:
        """
        新增实体。

        flush + refresh 的目的是把数据库生成的值(自增 id、默认值、触发器结果)回填到对象上,
        但事务仍未提交, 需要上层在合适的时机 commit。

        Args:
            obj: 待新增的 ORM 实例

        Returns:
            T: 回填了数据库生成字段的同一实例
        """
        self.write_db.add(obj)
        await self.write_db.flush()
        await self.write_db.refresh(obj)
        return obj

    async def update(self, obj: T) -> T:
        """
        完整对象更新(按主键覆盖)。

        Args:
            obj: ORM 实例; 未处于当前会话托管状态时会由 add() 重新纳入会话

        Returns:
            T: 更新后的同一实例
        """
        obj = await self.write_db.merge(obj)
        await self.write_db.flush()
        await self.write_db.refresh(obj)
        return obj

    async def partial_update(self, pk: Any, data: dict[str, Any]) -> T | None:
        """
        按主键部分更新。

        Args:
            pk: 主键值
            data: 待更新字段字典 {字段名: 新值}, 字段名必须存在于 Model

        Returns:
            T | None: 更新后的实体; 主键不存在时返回 None;
                      data 为空时直接返回原实体(不做无意义 UPDATE)

        注意: data 必须是 dict。手上若是 ORM / Pydantic 实例, 需先 model_dump()
              转换后再传入, 否则字段校验会直接失败。
        """
        self._validate_fields(data)
        if not data:
            return await self.write_db.get(self.model, pk)
        stmt = update(self.model).where(self.model.id == pk).values(**data).execution_options(synchronize_session="fetch")
        result = await self.write_db.exec(stmt)
        if result.rowcount == 0:
            return None
        return await self.write_db.get(self.model, pk)

    async def delete_by_id(self, pk: Any) -> bool:
        """
        按主键删除(硬删除)。

        Args:
            pk: 主键值

        Returns:
            bool: True 有记录被删除; False 主键不存在
        """
        stmt = delete(self.model).where(self.model.id == pk)
        result = await self.write_db.exec(stmt)
        return bool(result.rowcount)

    async def delete_by_unique_field(self, field_name: str, value: Any) -> bool:
        """
        根据【业务唯一字段】删除一条记录（业务唯一键，不是主键 id）。

        Args:
            field_name: 模型字段名，例如 "id" / "mail"
            value: 字段对应值

        Returns:
            bool: True 有记录被删除；False 没有匹配记录

        Raises:
            ValueError: field_name 不是模型字段

        注意: 本函数不 commit, 上层需要自己调用 await self.commit()
        """
        self._validate_field_names(field_name)
        # 获取模型字段对象
        field_col = getattr(self.model, field_name)
        stmt = delete(self.model).where(field_col == value)
        result = await self.write_db.exec(stmt)
        return bool(result.rowcount)

    async def delete_by_fields(self, **kwargs: Any) -> bool:
        """
        多字段等值条件删除，适合联合唯一键。

        example: await dao.delete_by_fields(target_id="xxx", account_id=123, target_type=1)

        Args:
            **kwargs: 等值过滤条件, 至少一个

        Returns:
            bool: True 有记录被删除；False 没有匹配记录

        Raises:
            ValueError: 一个条件都没传(否则会退化成删除全表) / 字段在模型上不存在

        注意: 本函数不 commit, 上层需要自己调用 await self.commit()
        """
        # 安全阀: 无条件的 DELETE 会清空整张表, 直接拒绝执行
        if not kwargs:
            raise ValueError(
                f"{self.table_name} delete_by_fields 至少需要一个条件, 否则会删除全表"
            )
        self._validate_fields(kwargs)
        stmt = delete(self.model)
        for field_name, val in kwargs.items():
            col = getattr(self.model, field_name)
            stmt = stmt.where(col == val)
        result = await self.write_db.exec(stmt)
        return bool(result.rowcount)

    async def bulk_create(self, objs: Sequence[T]) -> Sequence[T]:
        """
        批量新增(按 BULK_CHUNK_SIZE 分块 flush, 避免超大列表一次性压进会话)。

        Args:
            objs: ORM 实例序列; 空序列直接返回, 不产生任何 SQL

        Returns:
            Sequence[T]: 原序列(未 commit, 不含数据库生成字段的回填)
        """
        if not objs:
            return objs
        for start in range(0, len(objs), self.BULK_CHUNK_SIZE):
            chunk = objs[start:start + self.BULK_CHUNK_SIZE]
            self.write_db.add_all(list(chunk))
            await self.write_db.flush()
        return objs

    # =========================================================
    # 事务出口(仅供上层在事务边界调用)
    # =========================================================
    async def commit(self) -> None:
        """
        提交当前写事务。

        使用约束: 只允许 Service / API 层在一次业务操作全部完成后调用一次;
        本类内部的任何方法都不得调用它 —— 这样事务边界始终清晰、可整体回滚,
        也避免子类绕过基类去直接操作 write_db.commit()。
        """
        await self.write_db.commit()

    async def rollback(self) -> None:
        """回滚当前写事务。业务异常时应由上层调用, 保证不留半成品数据。"""
        await self.write_db.rollback()

    async def flush(self) -> None:
        """把待执行的 SQL 刷到数据库但不提交(需要提前触发约束校验时使用)。"""
        await self.write_db.flush()

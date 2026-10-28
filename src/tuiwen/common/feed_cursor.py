#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： feed_cursor.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/10/1 08:09
    @Desc: 推荐流分页游标 —— 把 (feed_id, create_at, id) 编码成 Base64URL 字符串下发给客户端,
           下一页原样带回即可续读。用 create_at + id 双键而非 offset, 避免新视频插入导致翻页重复/跳过。
           注意: 游标只做 Base64 编码、未签名, 客户端可解码但被篡改只会得到无效游标(400), 不涉及越权。
=================================================
"""
import base64
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class VideoFeedCursor:
    """解码后的游标内容, 字段与编码前的 payload 一一对应。"""
    version: int          # 游标格式版本, 升级编码方式时用于拒绝旧游标
    feed_id: UUID         # 本次推荐流会话 ID, 用于串联同一轮上下滑
    create_at: datetime   # 上一页最后一条的创建时间(分页主键)
    id: UUID              # 上一页最后一条的主键 id(uuid7, 同时间戳时的兜底排序键)


class FeedCursor:
    """游标编解码器(Base64URL + JSON, 去掉尾部 padding 以适配 URL)。"""
    VERSION = 1

    @classmethod
    def encode(
        cls,
        feed_id: UUID,
        create_at: datetime,
        id: UUID,
    ) -> str:
        """把分页位置编码成对 URL 安全的字符串(opaque, 客户端不应解析)。"""
        payload = {
            "v": cls.VERSION,
            "feed_id": str(feed_id),
            "create_at": create_at.isoformat(),
            "id": str(id),
        }
        raw = json.dumps(
            payload,
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @classmethod
    def decode(cls, cursor: str) -> VideoFeedCursor:
        """还原分页位置。

        Raises:
            ValueError: Base64/JSON 解析失败、版本不匹配或字段缺失 —— 统一收敛成
                        "invalid cursor", 由 Service 转成 400, 不向客户端泄露内部结构
        """
        try:
            padding = "=" * (-len(cursor) % 4)
            raw = base64.urlsafe_b64decode(
                cursor + padding
            )
            payload = json.loads(raw.decode("utf-8"))
            if payload.get("v") != cls.VERSION:
                raise ValueError("unsupported cursor version")
            return VideoFeedCursor(
                version=payload["v"],
                feed_id=UUID(payload["feed_id"]),
                create_at=datetime.fromisoformat(
                    payload["create_at"]
                ),
                id=UUID(payload["id"]),
            )
        except Exception as exc:
            raise ValueError("invalid cursor") from exc

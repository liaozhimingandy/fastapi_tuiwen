#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
=================================================
    @Project: fastapi_tuiwen
    @File： feed_cursor.py
    @Author：liaozhimingandy
    @Email: liaozhimingandy@gmail.com
    @Date：2026/10/1 08:09
    @Desc: 
=================================================
"""
import base64
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class VideoFeedCursor:
    version: int
    feed_id: UUID
    create_at: datetime
    id: int

class FeedCursor:
    VERSION = 1
    @classmethod
    def encode(
        cls,
        feed_id: UUID,
        create_at: datetime,
        id: int,
    ) -> str:
        payload = {
            "v": cls.VERSION,
            "feed_id": str(feed_id),
            "create_at": create_at.isoformat(),
            "id": id,
        }
        raw = json.dumps(
            payload,
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @classmethod
    def decode(cls, cursor: str) -> VideoFeedCursor:
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
                id=int(payload["id"]),
            )
        except Exception as exc:
            raise ValueError("invalid cursor") from exc

# -*- coding: utf-8 -*-
"""Redis Streams consumer — mirrors the backend's RedisQueue but runs standalone."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

log = logging.getLogger(__name__)

_STREAM_JOBS = "library:jobs"
_STREAM_STATUS_PREFIX = "library:status:"
_CANCEL_PREFIX = "library:cancel:"
_GROUP = "workers"


OUTPUT_FORMATS = ("default", "essay", "graphical", "contrast", "correlate")


@dataclass
class ResearchJob:
    job_id: str
    user_id: str
    prompt: str
    max_sources: int = 10
    focus_keywords: list[str] = field(default_factory=list)
    created_at: str = ""
    target_tokens: int = 1500
    output_format: str = "default"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchJob:
        kw = data.get("focus_keywords", "[]")
        if isinstance(kw, str):
            kw = json.loads(kw)
        fmt = (data.get("output_format") or "default").strip().lower()
        if fmt not in OUTPUT_FORMATS:
            fmt = "default"
        return cls(
            job_id=data["job_id"],
            user_id=data["user_id"],
            prompt=data["prompt"],
            max_sources=int(data.get("max_sources", 10)),
            focus_keywords=kw,
            created_at=data.get("created_at", ""),
            target_tokens=int(data.get("target_tokens", 1500)),
            output_format=fmt,
        )


class QueueConsumer:
    """Standalone Redis consumer for the worker process."""

    def __init__(self, redis_url: str, worker_id: str):
        self._url = redis_url
        self._worker_id = worker_id
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._redis = aioredis.from_url(self._url, decode_responses=True)
        try:
            await self._redis.xgroup_create(_STREAM_JOBS, _GROUP, id="0", mkstream=True)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        log.info("queue consumer connected (%s)", self._worker_id)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    async def dequeue(self, timeout_ms: int = 5000) -> tuple[str, ResearchJob] | None:
        assert self._redis
        results = await self._redis.xreadgroup(
            _GROUP, self._worker_id, {_STREAM_JOBS: ">"}, count=1, block=timeout_ms,
        )
        if not results:
            return None
        stream_id, fields = results[0][1][0]
        return stream_id, ResearchJob.from_dict(fields)

    async def ack(self, stream_id: str) -> None:
        assert self._redis
        await self._redis.xack(_STREAM_JOBS, _GROUP, stream_id)

    async def publish_status(
        self, job_id: str, status: str, message: str = "",
        progress: float = 0.0, sources_found: int = 0,
    ) -> None:
        assert self._redis
        key = f"{_STREAM_STATUS_PREFIX}{job_id}"
        payload = {
            "job_id": job_id,
            "status": status,
            "message": message,
            "progress": str(progress),
            "sources_found": str(sources_found),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self._redis.xadd(key, payload, maxlen=50)
        await self._redis.expire(key, 86400)

    async def set_key(self, key: str, value: str, ttl_sec: int) -> None:
        """Store an arbitrary key with TTL — used by the stats publisher."""
        assert self._redis
        await self._redis.set(key, value, ex=ttl_sec)

    async def is_cancel_requested(self, job_id: str) -> bool:
        """True if the API set a cooperative-cancel flag for this job (see backend library queue)."""
        assert self._redis
        val = await self._redis.get(f"{_CANCEL_PREFIX}{job_id}")
        return bool(val)

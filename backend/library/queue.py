# -*- coding: utf-8 -*-
"""Swappable queue abstraction backed by Redis Streams.

Design: the abstract base lets us swap Redis for RabbitMQ (or any other
transport) by implementing a new subclass — no call-site changes required.

The redis import is deferred so that importing this module never crashes the
backend when the redis package isn't installed or available — the feature
simply degrades at runtime.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator, TYPE_CHECKING

from backend.library.models import ResearchJob, StatusUpdate

if TYPE_CHECKING:
    import redis.asyncio as aioredis

_STREAM_JOBS = "library:jobs"
_STREAM_STATUS_PREFIX = "library:status:"
_GROUP = "workers"

log = logging.getLogger(__name__)


def _import_redis():
    """Lazy import — keeps the module loadable even when redis isn't installed."""
    import redis.asyncio as _aioredis
    return _aioredis


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class QueueBackend(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def enqueue(self, job: ResearchJob) -> str:
        """Push a research job onto the work queue.  Returns the stream ID."""
        ...

    @abstractmethod
    async def dequeue(self, consumer: str, timeout_ms: int = 5000) -> ResearchJob | None:
        """Block-read a single job from the queue.  Returns None on timeout."""
        ...

    @abstractmethod
    async def ack(self, stream_id: str) -> None:
        """Acknowledge that a job has been processed."""
        ...

    @abstractmethod
    async def publish_status(self, update: StatusUpdate) -> None:
        """Broadcast a progress update for a job."""
        ...

    @abstractmethod
    async def get_latest_status(self, job_id: str) -> StatusUpdate | None:
        """Return the most recent status update for a job."""
        ...

    @abstractmethod
    def subscribe_status(self, job_id: str) -> AsyncIterator[StatusUpdate]:
        """Yield status updates as they arrive (for SSE)."""
        ...


# ---------------------------------------------------------------------------
# Redis Streams implementation
# ---------------------------------------------------------------------------

class RedisQueue(QueueBackend):
    """Redis Streams for the job queue + per-job status streams."""

    def __init__(self, redis_url: str):
        self._url = redis_url
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        _aioredis = _import_redis()
        self._redis = _aioredis.from_url(self._url, decode_responses=True)
        try:
            await self._redis.xgroup_create(_STREAM_JOBS, _GROUP, id="0", mkstream=True)
        except _aioredis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise
        log.info("redis queue connected to %s", self._url)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    @property
    def _r(self) -> aioredis.Redis:
        assert self._redis is not None, "call connect() first"
        return self._redis

    # -- Job queue -----------------------------------------------------------

    async def enqueue(self, job: ResearchJob) -> str:
        payload = {k: json.dumps(v) if isinstance(v, (list, dict)) else str(v)
                   for k, v in job.to_dict().items()}
        stream_id: str = await self._r.xadd(_STREAM_JOBS, payload)
        log.info("enqueued job %s -> stream id %s", job.job_id, stream_id)
        return stream_id

    async def dequeue(self, consumer: str, timeout_ms: int = 5000) -> tuple[str, ResearchJob] | None:
        results = await self._r.xreadgroup(
            _GROUP, consumer, {_STREAM_JOBS: ">"}, count=1, block=timeout_ms,
        )
        if not results:
            return None
        # results = [[stream_name, [(stream_id, field_dict)]]]
        stream_id, fields = results[0][1][0]
        for k in ("focus_keywords",):
            if k in fields:
                fields[k] = json.loads(fields[k])
        return stream_id, ResearchJob.from_dict(fields)

    async def ack(self, stream_id: str) -> None:
        await self._r.xack(_STREAM_JOBS, _GROUP, stream_id)

    # -- Status updates ------------------------------------------------------

    def _status_key(self, job_id: str) -> str:
        return f"{_STREAM_STATUS_PREFIX}{job_id}"

    async def publish_status(self, update: StatusUpdate) -> None:
        key = self._status_key(update.job_id)
        payload = {k: str(v) for k, v in update.to_dict().items()}
        await self._r.xadd(key, payload, maxlen=50)
        await self._r.expire(key, 86400)

    async def get_latest_status(self, job_id: str) -> StatusUpdate | None:
        key = self._status_key(job_id)
        entries = await self._r.xrevrange(key, count=1)
        if not entries:
            return None
        _, fields = entries[0]
        fields["progress"] = float(fields.get("progress", 0))
        fields["sources_found"] = int(fields.get("sources_found", 0))
        return StatusUpdate.from_dict(fields)

    async def subscribe_status(self, job_id: str) -> AsyncIterator[StatusUpdate]:
        """Yield status updates as they appear.  Caller should wrap in a try/finally."""
        key = self._status_key(job_id)
        last_id = "0-0"
        while True:
            entries = await self._r.xread({key: last_id}, count=5, block=2000)
            if not entries:
                yield None  # heartbeat — lets SSE send a keep-alive comment
                continue
            for _, messages in entries:
                for msg_id, fields in messages:
                    last_id = msg_id
                    fields["progress"] = float(fields.get("progress", 0))
                    fields["sources_found"] = int(fields.get("sources_found", 0))
                    update = StatusUpdate.from_dict(fields)
                    yield update
                    if update.status in ("review", "failed", "cancelled"):
                        return


# ---------------------------------------------------------------------------
# Singleton accessor (initialised during app lifespan)
# ---------------------------------------------------------------------------

_queue: QueueBackend | None = None


async def init_queue(redis_url: str) -> QueueBackend:
    global _queue
    q = RedisQueue(redis_url)
    await q.connect()
    _queue = q
    return q


async def close_queue() -> None:
    global _queue
    if _queue:
        await _queue.close()
        _queue = None


def get_queue() -> QueueBackend:
    if _queue is None:
        raise RuntimeError(
            "Redis queue is not connected. "
            "Ensure Redis is running and REDIS_URL is set correctly."
        )
    return _queue

# -*- coding: utf-8 -*-
"""Runtime overrides for the Library nanobot worker (Redis)."""
from __future__ import annotations

import json
import logging

from backend.config import get_settings
from backend.library.queue import RedisQueue

log = logging.getLogger(__name__)


async def publish_worker_ollama_from_settings() -> None:
    """Push ``model`` / ``num_ctx`` to Redis so workers pick them up without restart."""
    from backend.library.queue import get_queue

    try:
        q = get_queue()
    except RuntimeError:
        return
    if not isinstance(q, RedisQueue):
        return
    settings = get_settings()
    try:
        await q.publish_worker_ollama_runtime(
            settings.WORKER_OLLAMA_MODEL,
            settings.WORKER_OLLAMA_NUM_CTX,
        )
    except Exception as exc:
        log.warning("publish_worker_ollama_from_settings failed: %s", exc)

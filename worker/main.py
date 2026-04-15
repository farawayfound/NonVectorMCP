# -*- coding: utf-8 -*-
"""Nanobot worker entry point — consumer loop that processes research jobs."""
from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys

import httpx

import config
import sysstats
from queue_consumer import QueueConsumer

_STATS_KEY_PREFIX = "worker:stats:"
_STATS_TTL_SEC = 60
_STATS_INTERVAL_SEC = 10

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("worker")

_shutdown = asyncio.Event()


def _handle_signal(*_):
    log.info("shutdown signal received")
    _shutdown.set()


async def _process_job(consumer: QueueConsumer, stream_id: str, job) -> None:
    """Run the full research pipeline for a single job."""
    from synthesizer.pipeline import JobCancelledError, run_pipeline

    job_id = job.job_id
    log.info("processing job %s — %r", job_id, job.prompt[:80])

    async def cancel_check() -> bool:
        return await consumer.is_cancel_requested(job_id)

    try:
        if await cancel_check():
            log.info("job %s skipped — cancel flag set before pipeline", job_id)
            await consumer.publish_status(
                job_id, "cancelled", "Cancelled by user", progress=0.0, sources_found=0,
            )
            await consumer.ack(stream_id)
            return

        result = await run_pipeline(
            job=job,
            status_cb=lambda status, msg, progress=0.0, sources=0: (
                consumer.publish_status(job_id, status, msg, progress, sources)
            ),
            cancel_check=cancel_check,
            redis_consumer=consumer,
        )

        if await cancel_check():
            log.info("job %s stopped after pipeline — cancel flag (race)", job_id)
            await consumer.publish_status(
                job_id, "cancelled", "Cancelled by user", progress=0.0, sources_found=0,
            )
            await consumer.ack(stream_id)
            return

        await _deliver_result(job_id, result)
        await consumer.publish_status(
            job_id, "review", "Research complete — awaiting review",
            progress=1.0, sources_found=len(result.get("sources", [])),
        )
        await consumer.ack(stream_id)
        log.info("job %s complete — %d sources", job_id, len(result.get("sources", [])))

    except JobCancelledError:
        log.info("job %s stopped (cooperative cancel)", job_id)
        await consumer.publish_status(
            job_id, "cancelled", "Cancelled by user", progress=0.0, sources_found=0,
        )
        await consumer.ack(stream_id)

    except Exception as exc:
        log.exception("job %s failed: %s", job_id, exc)
        await consumer.publish_status(job_id, "failed", str(exc))
        await consumer.ack(stream_id)


async def _deliver_result(job_id: str, result: dict) -> None:
    """POST the completed artifact back to the M1 backend."""
    url = f"{config.M1_BASE_URL}/api/library/ingest"
    payload = {
        "job_id": job_id,
        "markdown": result["markdown"],
        "sources": result.get("sources", []),
        "summary": result.get("summary", ""),
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            json=payload,
            headers={"X-Nanobot-Key": config.NANOBOT_API_KEY},
        )
        resp.raise_for_status()
        log.info("delivered result for %s — %s", job_id, resp.json())


async def _publish_stats_loop(consumer: QueueConsumer) -> None:
    """Push a system resource snapshot to Redis every few seconds.

    Backend reads these under `worker:stats:<worker_id>` with a short TTL
    so the admin UI can show "offline" automatically when the worker dies.
    """
    key = f"{_STATS_KEY_PREFIX}{config.WORKER_ID}"
    while not _shutdown.is_set():
        try:
            snap = sysstats.snapshot()
            snap["worker_id"] = config.WORKER_ID
            await consumer.set_key(key, json.dumps(snap), _STATS_TTL_SEC)
        except Exception as exc:
            log.warning("stats publish failed: %s", exc)
        try:
            await asyncio.wait_for(_shutdown.wait(), timeout=_STATS_INTERVAL_SEC)
        except asyncio.TimeoutError:
            pass


async def main() -> None:
    consumer = QueueConsumer(config.REDIS_URL, config.WORKER_ID)
    await consumer.connect()
    log.info("worker %s listening for jobs...", config.WORKER_ID)

    stats_task = asyncio.create_task(_publish_stats_loop(consumer))

    try:
        while not _shutdown.is_set():
            pair = await consumer.dequeue(timeout_ms=3000)
            if pair is None:
                continue
            stream_id, job = pair
            await _process_job(consumer, stream_id, job)
    except asyncio.CancelledError:
        pass
    finally:
        stats_task.cancel()
        try:
            await stats_task
        except (asyncio.CancelledError, Exception):
            pass
        await consumer.close()
        log.info("worker shut down cleanly")


if __name__ == "__main__":
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _handle_signal)
    asyncio.run(main())

# -*- coding: utf-8 -*-
"""Nanobot worker entry point — consumer loop that processes research jobs."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys

import httpx

import config
import sysstats
from queue_consumer import QueueConsumer
from synthesizer.llm_client import verify_ollama_model_tag

_STATS_KEY_PREFIX = "worker:stats:"
_STATS_TTL_SEC = 60
_STATS_INTERVAL_SEC = 10

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("worker")

_shutdown = asyncio.Event()


def _fail_fast_if_docker_redis_points_at_loopback() -> None:
    """Redis on localhost inside Docker is almost always wrong — avoids a tight restart loop with no obvious log."""
    if not os.path.isfile("/.dockerenv"):
        return
    ru = (config.REDIS_URL or "").lower()
    if "localhost" not in ru and "127.0.0.1" not in ru:
        return
    log.critical(
        "REDIS_URL uses localhost/127.0.0.1 but this process runs inside Docker. "
        "That address is the worker container itself, not your Mac — Redis will never connect and Docker will "
        "restart this container forever. Edit .env.nanobot: set REDIS_URL to the LAN host:port where Redis actually "
        "runs (same value the ChunkyLink backend can use, reachable from nanobot), e.g. redis://192.168.0.10:6379/0 "
        "then: sudo docker compose -f docker/docker-compose.nanobot.yml up -d --force-recreate worker"
    )
    sys.exit(2)


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
        detail = str(exc).strip() or repr(exc) or type(exc).__name__
        await _report_failure_to_m1(job_id, detail)
        await consumer.publish_status(job_id, "failed", detail)
        await consumer.ack(stream_id)


async def _report_failure_to_m1(job_id: str, detail: str) -> None:
    """Persist failure on the M1 backend so Library detail always has error text (not only Redis/SSE)."""
    if not config.NANOBOT_API_KEY:
        return
    url = f"{config.M1_BASE_URL}/api/library/worker-failure"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url,
                json={"job_id": job_id, "message": detail},
                headers={"X-Nanobot-Key": config.NANOBOT_API_KEY},
            )
            resp.raise_for_status()
    except Exception:
        log.warning("could not POST worker-failure to M1 for job %s", job_id, exc_info=True)


async def _deliver_result(job_id: str, result: dict) -> None:
    """POST the completed artifact back to the M1 backend."""
    url = f"{config.M1_BASE_URL}/api/library/ingest"
    markdown = result.get("markdown", "")
    payload = {
        "job_id": job_id,
        "markdown": markdown,
        "sources": result.get("sources", []),
        "summary": result.get("summary", ""),
    }
    log.info("delivering result for %s → %s (%d chars)", job_id, url, len(markdown))
    # Use explicit per-phase timeouts — large markdown payloads can take a while to upload
    # over LAN; 180 s write budget is generous but safe for multi-MB JSON bodies.
    timeout = httpx.Timeout(connect=30.0, read=180.0, write=180.0, pool=30.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"X-Nanobot-Key": config.NANOBOT_API_KEY},
            )
            resp.raise_for_status()
            log.info("delivered result for %s — %s", job_id, resp.json())
    except Exception as exc:
        log.error(
            "DELIVERY FAILED for job %s → %s: %s. "
            "Check M1_BASE_URL in .env.nanobot — it must be the backend's LAN IP address "
            "(e.g. http://192.168.1.x:8000). mDNS names such as 'macmini.local' do NOT "
            "resolve inside a Linux Docker container. Also verify NANOBOT_API_KEY matches "
            "the backend's .env.",
            job_id, url, exc,
        )
        raise


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
    _fail_fast_if_docker_redis_points_at_loopback()
    consumer = QueueConsumer(config.REDIS_URL, config.WORKER_ID)
    try:
        await consumer.connect()
    except Exception as exc:
        log.critical(
            "could not connect to Redis (REDIS_URL in .env.nanobot) — use the Mac mini LAN IP:port "
            "where Redis listens, same DB index as the backend.",
            exc_info=True,
        )
        seen: set[int] = set()
        err: BaseException | None = exc
        while err is not None and id(err) not in seen:
            seen.add(id(err))
            if isinstance(err, OSError) and getattr(err, "errno", None) == 113:
                log.critical(
                    "errno 113 (EHOSTUNREACH): no network route to that host:port. "
                    "Often: wrong IP (confirm on Mac: ifconfig / Wi‑Fi details), Mac firewall, "
                    "different VLANs, or Redis on Mac bound only to 127.0.0.1 — Redis must listen on "
                    "0.0.0.0 (or the LAN interface) for nanobot to connect."
                )
                break
            nxt = getattr(err, "__cause__", None) or getattr(err, "__context__", None)
            err = nxt if nxt is not err else None
        raise
    log.info(
        "worker %s listening (Ollama base=%s model=%s num_ctx=%d)",
        config.WORKER_ID,
        config.OLLAMA_BASE_URL,
        config.OLLAMA_MODEL,
        config.OLLAMA_NUM_CTX,
    )
    await verify_ollama_model_tag()

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

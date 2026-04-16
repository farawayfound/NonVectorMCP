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
from agent_debug_log import agent_log
from queue_consumer import QueueConsumer, WORKER_OLLAMA_REDIS_KEY

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


async def _sync_worker_config(consumer: QueueConsumer) -> None:
    """Sync model config from Redis (backend Settings is the source of truth).

    Updates ``config.OLLAMA_MODEL`` and ``config.OLLAMA_NUM_CTX`` in-place so
    every downstream consumer (pipeline, llm_client) picks up the latest value
    without needing direct Redis access.
    """
    try:
        raw = await consumer.get_key(WORKER_OLLAMA_REDIS_KEY)
        if not raw:
            return
        data = json.loads(raw)
        if data.get("model"):
            config.OLLAMA_MODEL = str(data["model"]).strip()
        if data.get("num_ctx") is not None:
            config.OLLAMA_NUM_CTX = int(data["num_ctx"])
        # #region agent log
        agent_log(
            hypothesis_id="H4",
            location="main.py:_sync_worker_config",
            message="redis_ollama_sync",
            data={
                "raw_len": len(raw),
                "model": config.OLLAMA_MODEL,
                "num_ctx": config.OLLAMA_NUM_CTX,
            },
        )
        # #endregion
    except Exception as exc:
        log.debug("config sync from redis skipped: %s", exc)


async def _preload_model() -> None:
    """Ensure the configured model is loaded on the local Ollama before jobs run.

    Lists loaded models via ``/api/ps``, evicts any that don't match, then
    warms the target with ``keep_alive=-1`` so it stays pinned.  600s read
    timeout accommodates cold-loading large (26B+) models.
    """
    base = config.OLLAMA_BASE_URL.rstrip("/")
    model = config.OLLAMA_MODEL
    num_ctx = config.OLLAMA_NUM_CTX
    log.info("preload: target model=%s num_ctx=%d at %s", model, num_ctx, base)

    timeout = httpx.Timeout(connect=10.0, read=600.0, write=10.0, pool=10.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # List loaded models
            ps_resp = await client.get(f"{base}/api/ps")
            ps_resp.raise_for_status()
            loaded = ps_resp.json().get("models") or []

            # Normalise loaded names (Ollama reports "name" or "model")
            def _name(m: dict) -> str:
                return str(m.get("name") or m.get("model") or "").strip()

            # Evict any model that isn't our target
            for m in loaded:
                other = _name(m)
                if other and other != model:
                    log.info("preload: evicting stale model '%s'", other)
                    await client.post(
                        f"{base}/api/generate",
                        json={"model": other, "keep_alive": 0, "stream": False},
                    )

            # Warm the target (empty prompt = load-only, no generation)
            log.info("preload: loading %s (num_ctx=%d)...", model, num_ctx)
            resp = await client.post(
                f"{base}/api/generate",
                json={
                    "model": model,
                    "prompt": "",
                    "stream": False,
                    "think": False,
                    "keep_alive": -1,
                    "options": {"num_ctx": num_ctx},
                },
            )
            resp.raise_for_status()
            log.info("preload: %s ready", model)
    except Exception as exc:
        log.error("preload failed — first job will cold-load: %s", exc)


async def _process_job(consumer: QueueConsumer, stream_id: str, job) -> None:
    """Run the full research pipeline for a single job."""
    from synthesizer.pipeline import JobCancelledError, run_pipeline

    job_id = job.job_id
    log.info("processing job %s — %r", job_id, job.prompt[:80])
    # #region agent log
    agent_log(
        hypothesis_id="H4",
        location="main.py:_process_job:start",
        message="job_start_after_sync",
        data={
            "job_id": job_id,
            "model": config.OLLAMA_MODEL,
            "num_ctx": config.OLLAMA_NUM_CTX,
        },
    )
    # #endregion

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
    await _sync_worker_config(consumer)
    log.info("worker %s starting (model=%s, num_ctx=%d)",
             config.WORKER_ID, config.OLLAMA_MODEL, config.OLLAMA_NUM_CTX)
    await _preload_model()
    log.info("worker %s listening for jobs...", config.WORKER_ID)

    stats_task = asyncio.create_task(_publish_stats_loop(consumer))

    try:
        while not _shutdown.is_set():
            pair = await consumer.dequeue(timeout_ms=3000)
            if pair is None:
                continue
            stream_id, job = pair
            await _sync_worker_config(consumer)
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

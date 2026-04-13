#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulate the Ryzen "nanobot" worker on your dev machine (no Crawl4AI / Ollama).

Prerequisites
-------------
1. Redis running and reachable (same stream as the backend), e.g.:
     docker run -d --name chunky-redis -p 6379:6379 redis:7-alpine

2. Backend running with matching env, e.g.:
     set REDIS_URL=redis://127.0.0.1:6379/0
     set NANOBOT_API_KEY=your-shared-secret
     uvicorn backend.main:app --host 127.0.0.1 --port 8000

3. A queued job in Redis — e.g. submit a prompt from the Library UI while logged in.

Then run (from repo root, with deps installed):
     python scripts/simulate_library_worker_local.py --once

Environment (optional overrides)
--------------------------------
  REDIS_URL          default redis://127.0.0.1:6379/0
  M1_BASE_URL        default http://127.0.0.1:8000
  NANOBOT_API_KEY    must match backend .env
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx
import redis

_STREAM_JOBS = "library:jobs"
_GROUP = "workers"
_CONSUMER = "simulate-local"


def _parse_job_fields(fields: dict) -> dict:
    out = dict(fields)
    for k in ("focus_keywords",):
        if k in out and isinstance(out[k], str):
            try:
                out[k] = json.loads(out[k])
            except json.JSONDecodeError:
                out[k] = []
    return out


def _fake_markdown(prompt: str) -> str:
    """Enough text to pass LearnEngine gate_quality (>= 15 words, sane ratios)."""
    body = (
        f"# Simulated research report\n\n"
        f"This is a **local simulation** of the nanobot worker for job topic:\n\n"
        f"> {prompt}\n\n"
        f"In production the Ryzen node would crawl the web and synthesize real sources. "
        f"This paragraph exists only to validate the queue, ingest API, and review flow "
        f"before deployment. Graph RAG combines retrieval with graph structure for "
        f"better multi-hop reasoning over knowledge bases.\n\n"
        f"## Sources\n\n"
        f"- [Example](https://example.com) — placeholder citation for local testing.\n"
    )
    return body


def run_once(
    r: redis.Redis,
    base_url: str,
    api_key: str,
    block_ms: int,
) -> bool:
    """Read one pending job from the consumer group, POST ingest, XACK. Returns True if a job ran."""
    try:
        r.xgroup_create(_STREAM_JOBS, _GROUP, id="0", mkstream=True)
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise

    results = r.xreadgroup(_GROUP, _CONSUMER, {_STREAM_JOBS: ">"}, count=1, block=block_ms)
    if not results:
        print("No job available (timeout). Submit a task from Library or increase --block-ms.")
        return False

    _stream_name, messages = results[0]
    stream_id, fields = messages[0]
    data = _parse_job_fields(fields)
    job_id = data.get("job_id")
    prompt = data.get("prompt", "")
    if not job_id:
        print("Malformed job (missing job_id); acking to clear poison message.")
        r.xack(_STREAM_JOBS, _GROUP, stream_id)
        return False

    md = _fake_markdown(prompt)
    url = f"{base_url.rstrip('/')}/api/library/ingest"
    headers = {"X-Nanobot-Key": api_key, "Content-Type": "application/json"}
    payload = {
        "job_id": job_id,
        "markdown": md,
        "sources": [
            {"url": "https://example.com", "title": "Example (simulated)"},
        ],
        "summary": "Simulated worker output for local integration testing.",
    }

    print(f"Picked up job {job_id!r} — posting ingest to {url}")
    resp = httpx.post(url, json=payload, headers=headers, timeout=60.0)
    if resp.status_code >= 400:
        print(f"Ingest failed HTTP {resp.status_code}: {resp.text[:500]}")
        # Do not ack — message can be retried after fixing backend
        return False

    r.xack(_STREAM_JOBS, _GROUP, stream_id)
    print(f"OK — {resp.json()}")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description="Simulate nanobot Library worker locally (ingest only).")
    p.add_argument("--once", action="store_true", help="Process at most one job then exit.")
    p.add_argument(
        "--loop",
        action="store_true",
        help="Keep polling for jobs (5s between idle timeouts). Ctrl+C to stop.",
    )
    p.add_argument("--block-ms", type=int, default=5000, help="XREADGROUP block timeout (ms).")
    args = p.parse_args()

    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    base_url = os.getenv("M1_BASE_URL", "http://127.0.0.1:8000")
    api_key = os.getenv("NANOBOT_API_KEY", "")
    if not api_key.strip():
        print("NANOBOT_API_KEY is not set (must match backend).", file=sys.stderr)
        return 2

    r = redis.from_url(redis_url, decode_responses=True)

    if args.loop:
        print(f"Listening on {redis_url} → ingest {base_url} (consumer {_CONSUMER})")
        try:
            while True:
                if run_once(r, base_url, api_key, args.block_ms):
                    continue
                time.sleep(5)
        except KeyboardInterrupt:
            print("Stopped.")
            return 0

    if args.once or not args.loop:
        ok = run_once(r, base_url, api_key, args.block_ms)
        return 0 if ok else 1

    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

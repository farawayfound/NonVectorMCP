# -*- coding: utf-8 -*-
"""Async Ollama REST API client with streaming support."""
import json
import logging
import time
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx

from backend.config import get_settings

# ── Shared HTTP client (initialized in app lifespan) ───────────────────────
_http_client: httpx.AsyncClient | None = None

# ── Last-inference performance snapshot (updated after every generate/chat) ───
_last_inference_stats: dict = {
    "tokens_per_sec": None,
    "prompt_tokens": None,
    "completion_tokens": None,
}

# ── Readiness / warm-state telemetry (for admin + debugging TTFT) ───────────
_readiness_metrics: dict = {
    "last_ensure_ms": None,
    "last_ensure_ok": None,
    "last_ensure_error": None,
    "last_preload_ms": None,
    "last_preload_at_utc": None,
    "configured_model_in_memory": None,
}


def _default_stream_timeout() -> httpx.Timeout:
    return httpx.Timeout(connect=10.0, read=600.0, write=10.0, pool=10.0)


async def init_ollama_http() -> None:
    """Create a long-lived AsyncClient for Ollama (connection reuse, lower TTFT)."""
    global _http_client
    if _http_client is not None:
        return
    _http_client = httpx.AsyncClient(
        timeout=_default_stream_timeout(),
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
    )
    logging.info("ollama_client: shared HTTP client initialized")


async def close_ollama_http() -> None:
    """Close the shared client (app shutdown)."""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
        logging.info("ollama_client: shared HTTP client closed")


def _ephemeral_client(**kwargs) -> httpx.AsyncClient:
    """Short-lived client when shared client is unavailable (e.g. unit tests)."""
    return httpx.AsyncClient(**kwargs)


def _capture_inference_stats(chunk: dict) -> None:
    """Store tokens/sec and token counts from an Ollama 'done' chunk."""
    eval_count = chunk.get("eval_count", 0) or 0
    eval_ns = chunk.get("eval_duration", 0) or 0
    if eval_count and eval_ns:
        _last_inference_stats["tokens_per_sec"] = round(eval_count / (eval_ns / 1e9), 1)
    _last_inference_stats["prompt_tokens"] = chunk.get("prompt_eval_count", 0) or 0
    _last_inference_stats["completion_tokens"] = eval_count


def get_inference_stats() -> dict:
    """Return the most recent inference performance snapshot."""
    return dict(_last_inference_stats)


def get_readiness_metrics() -> dict:
    """Snapshot of last preload/ensure_single_model_loaded outcomes (admin / ops)."""
    return dict(_readiness_metrics)


async def health_check() -> dict:
    """Check if Ollama is reachable and return version info."""
    settings = get_settings()
    url = settings.OLLAMA_BASE_URL.rstrip("/")
    try:
        if _http_client is not None:
            await _http_client.get(url, timeout=5.0)
        else:
            async with _ephemeral_client(timeout=5.0) as c:
                await c.get(url)
        return {"status": "ok", "base_url": settings.OLLAMA_BASE_URL}
    except Exception as e:
        return {"status": "unreachable", "error": str(e), "base_url": settings.OLLAMA_BASE_URL}


async def list_models() -> list[dict]:
    """List locally available Ollama models."""
    settings = get_settings()
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags"
    try:
        if _http_client is not None:
            resp = await _http_client.get(url, timeout=10.0)
        else:
            async with _ephemeral_client(timeout=10.0) as c:
                resp = await c.get(url)
        resp.raise_for_status()
        return resp.json().get("models", [])
    except Exception as e:
        logging.warning(f"ollama_client: failed to list models: {e}")
        return []


async def list_loaded_models() -> list[dict]:
    """List models currently loaded in Ollama memory via /api/ps."""
    settings = get_settings()
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/ps"
    try:
        if _http_client is not None:
            resp = await _http_client.get(url, timeout=5.0)
        else:
            async with _ephemeral_client(timeout=5.0) as c:
                resp = await c.get(url)
        resp.raise_for_status()
        return resp.json().get("models", [])
    except Exception as e:
        logging.warning(f"ollama_client: failed to list loaded models: {e}")
        return []


async def get_model_context_window(name: str) -> int | None:
    """Return the context window (num_ctx) for a model via /api/show."""
    settings = get_settings()
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/show"
    try:
        if _http_client is not None:
            resp = await _http_client.post(url, json={"name": name}, timeout=10.0)
        else:
            async with _ephemeral_client(timeout=10.0) as c:
                resp = await c.post(url, json={"name": name})
        resp.raise_for_status()
        data = resp.json()
        for key, val in data.get("model_info", {}).items():
            if "context_length" in key.lower():
                return int(val)
        for line in data.get("parameters", "").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0].lower() == "num_ctx":
                return int(parts[1])
    except Exception as e:
        logging.warning(f"ollama_client: get_model_context_window failed for '{name}': {e}")
    return None


async def pull_model(name: str) -> AsyncIterator[dict]:
    """Pull a model from the Ollama registry, streaming progress updates."""
    settings = get_settings()
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/pull"
    client = _http_client
    if client is None:
        async with httpx.AsyncClient(timeout=_default_stream_timeout()) as c:
            async with c.stream("POST", url, json={"name": name}) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except Exception:
                        continue
        return
    async with client.stream("POST", url, json={"name": name}) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


async def delete_model(name: str) -> dict:
    """Delete a model from Ollama."""
    settings = get_settings()
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/delete"
    if _http_client is not None:
        resp = await _http_client.request("DELETE", url, json={"name": name}, timeout=10.0)
    else:
        async with _ephemeral_client(timeout=10.0) as c:
            resp = await c.request("DELETE", url, json={"name": name})
    resp.raise_for_status()
    return {"status": "deleted", "name": name}


async def unload_model(name: str) -> None:
    """Immediately evict a model from Ollama memory (keep_alive=0)."""
    settings = get_settings()
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    try:
        if _http_client is not None:
            await _http_client.post(
                url,
                json={"model": name, "keep_alive": 0, "stream": False},
                timeout=10.0,
            )
        else:
            async with _ephemeral_client(timeout=10.0) as c:
                await c.post(url, json={"model": name, "keep_alive": 0, "stream": False})
        logging.info(f"ollama_client: unloaded '{name}'")
    except Exception as e:
        logging.warning(f"ollama_client: unload failed for '{name}': {e}")


def _ollama_same_base_model(loaded_name: str, want: str) -> bool:
    """True if Ollama model names refer to the same base (tag-agnostic)."""
    if not loaded_name or not want:
        return False
    a = loaded_name.split(":", 1)[0]
    b = want.split(":", 1)[0]
    return a == b


async def preload_model(name: str, num_ctx: int | None = None) -> None:
    """Load a model into memory with keep_alive=-1 (never auto-evict).

    Pass ``num_ctx`` to force Ollama to allocate the KV cache for a specific
    context window size on load.  If omitted, the current settings value is used.
    """
    settings = get_settings()
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    t0 = time.monotonic()
    ctx = num_ctx if num_ctx is not None else settings.OLLAMA_NUM_CTX
    payload: dict = {"model": name, "keep_alive": -1, "stream": False, "options": {"num_ctx": ctx}}
    try:
        if _http_client is not None:
            resp = await _http_client.post(
                url,
                json=payload,
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
            )
        else:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
            ) as c:
                resp = await c.post(url, json=payload)
        resp.raise_for_status()
        logging.info(f"ollama_client: preloaded '{name}' with num_ctx={ctx}")
        _readiness_metrics["last_preload_ms"] = round((time.monotonic() - t0) * 1000)
        _readiness_metrics["last_preload_at_utc"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except Exception as e:
        _readiness_metrics["last_preload_ms"] = round((time.monotonic() - t0) * 1000)
        logging.warning(f"ollama_client: preload failed for '{name}': {e}")


async def ensure_single_model_loaded(name: str) -> None:
    """Enforce one-model-in-memory policy: unload non-target models; preload only if needed."""
    t0 = time.monotonic()
    _readiness_metrics["last_ensure_error"] = None
    if not str(name).strip():
        _readiness_metrics["last_ensure_ok"] = None
        _readiness_metrics["last_ensure_ms"] = round((time.monotonic() - t0) * 1000)
        return
    ok = False
    try:
        loaded = await list_loaded_models()
        for m in loaded:
            other = m.get("name", "")
            if other and not _ollama_same_base_model(other, name):
                logging.info(f"ollama_client: evicting '{other}' to enforce single-model policy")
                await unload_model(other)
        loaded = await list_loaded_models()
        for m in loaded:
            n = m.get("name", "")
            if n and _ollama_same_base_model(n, name):
                ok = True
                break
        if not ok:
            await preload_model(name)
            loaded = await list_loaded_models()
            ok = any(
                m.get("name") and _ollama_same_base_model(m.get("name", ""), name)
                for m in loaded
            )
        _readiness_metrics["configured_model_in_memory"] = ok
        _readiness_metrics["last_ensure_ok"] = ok
        if not ok:
            _readiness_metrics["last_ensure_error"] = "model not reported in /api/ps after preload"
    except Exception as e:
        _readiness_metrics["last_ensure_ok"] = False
        _readiness_metrics["last_ensure_error"] = str(e)
        _readiness_metrics["configured_model_in_memory"] = False
        logging.warning("ollama_client: ensure_single_model_loaded failed: %s", e)
    finally:
        _readiness_metrics["last_ensure_ms"] = round((time.monotonic() - t0) * 1000)


async def generate_stream(
    prompt: str,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    latency: dict | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """Stream a completion from Ollama, yielding ``(kind, text)`` tuples.

    *kind* is ``"thinking"`` for reasoning-trace tokens or ``"text"`` for
    visible answer tokens.  Ollama's ``think`` parameter is always enabled so
    models that support structured thinking return the trace in a dedicated
    ``thinking`` field.  Models without thinking support simply return
    everything via the ``response`` field — the ``thinking`` field will be
    absent / empty and all tuples will be ``("text", ...)``.

    If *latency* is a dict it is filled with:
    - ollama_connect_ms: time until HTTP stream is ready (response headers OK)
    - ttft_ms: time until first non-empty model token (thinking or text)
    - stream_total_ms: time until stream completes
    """
    settings = get_settings()
    model = model or settings.OLLAMA_MODEL
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "think": True,
        "keep_alive": -1,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": settings.OLLAMA_NUM_CTX,
        },
    }
    if system:
        payload["system"] = system

    t_req = time.monotonic()
    if latency is not None:
        latency.setdefault("ollama_connect_ms", None)
        latency.setdefault("ttft_ms", None)
        latency.setdefault("stream_total_ms", None)

    stream_timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)

    async def _run_stream(client: httpx.AsyncClient) -> AsyncIterator[tuple[str, str]]:
        ttft_recorded = False
        async with client.stream("POST", url, json=payload, timeout=stream_timeout) as resp:
            resp.raise_for_status()
            if latency is not None:
                latency["ollama_connect_ms"] = round((time.monotonic() - t_req) * 1000)
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    thinking = chunk.get("thinking", "")
                    text = chunk.get("response", "")
                    if (thinking or text) and latency is not None and not ttft_recorded:
                        latency["ttft_ms"] = round((time.monotonic() - t_req) * 1000)
                        ttft_recorded = True
                    if thinking:
                        yield ("thinking", thinking)
                    if text:
                        yield ("text", text)
                    if chunk.get("done", False):
                        _capture_inference_stats(chunk)
                        if latency is not None:
                            latency["stream_total_ms"] = round((time.monotonic() - t_req) * 1000)
                        return
                except Exception:
                    continue
        if latency is not None and latency.get("stream_total_ms") is None:
            latency["stream_total_ms"] = round((time.monotonic() - t_req) * 1000)

    if _http_client is not None:
        async for item in _run_stream(_http_client):
            yield item
    else:
        async with httpx.AsyncClient(timeout=stream_timeout) as c:
            async for item in _run_stream(c):
                yield item


async def generate(
    prompt: str,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> str:
    """Non-streaming completion — collects full response (text only, thinking discarded)."""
    parts = []
    async for kind, text in generate_stream(prompt, system, model, temperature, max_tokens):
        if kind == "text":
            parts.append(text)
    return "".join(parts)


async def chat_stream(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    latency: dict | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """Stream a chat completion from Ollama /api/chat, yielding ``(kind, text)`` tuples.

    See :func:`generate_stream` for the semantics of *kind* and *latency*.
    """
    settings = get_settings()
    model = model or settings.OLLAMA_MODEL
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat"

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": True,
        "keep_alive": -1,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": settings.OLLAMA_NUM_CTX,
        },
    }

    t_req = time.monotonic()
    if latency is not None:
        latency.setdefault("ollama_connect_ms", None)
        latency.setdefault("ttft_ms", None)
        latency.setdefault("stream_total_ms", None)

    stream_timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)

    async def _run_chat_stream(client: httpx.AsyncClient) -> AsyncIterator[tuple[str, str]]:
        ttft_recorded = False
        async with client.stream("POST", url, json=payload, timeout=stream_timeout) as resp:
            resp.raise_for_status()
            if latency is not None:
                latency["ollama_connect_ms"] = round((time.monotonic() - t_req) * 1000)
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    msg = chunk.get("message", {})
                    thinking = msg.get("thinking", "")
                    text = msg.get("content", "")
                    if (thinking or text) and latency is not None and not ttft_recorded:
                        latency["ttft_ms"] = round((time.monotonic() - t_req) * 1000)
                        ttft_recorded = True
                    if thinking:
                        yield ("thinking", thinking)
                    if text:
                        yield ("text", text)
                    if chunk.get("done", False):
                        _capture_inference_stats(chunk)
                        if latency is not None:
                            latency["stream_total_ms"] = round((time.monotonic() - t_req) * 1000)
                        return
                except Exception:
                    continue
        if latency is not None and latency.get("stream_total_ms") is None:
            latency["stream_total_ms"] = round((time.monotonic() - t_req) * 1000)

    if _http_client is not None:
        async for item in _run_chat_stream(_http_client):
            yield item
    else:
        async with httpx.AsyncClient(timeout=stream_timeout) as c:
            async for item in _run_chat_stream(c):
                yield item

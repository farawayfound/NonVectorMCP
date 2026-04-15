# -*- coding: utf-8 -*-
"""Async Ollama REST API client with streaming support."""
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx

from backend.config import get_settings


def _ollama_think_request_value() -> bool | str:
    """JSON value for Ollama's ``think`` field: bool, or low/medium/high (GPT-OSS)."""
    level = os.getenv("CHAT_THINK_LEVEL", "").strip().lower()
    if level in ("low", "medium", "high"):
        return level
    return bool(get_settings().CHAT_ENABLE_THINKING)


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


def _ollama_root(base_url: str) -> str:
    return base_url.strip().rstrip("/")


def _ollama_ps_name(m: dict) -> str:
    """Running-model row from ``/api/ps`` — prefer ``name``, fall back to ``model``."""
    return str(m.get("name") or m.get("model") or "").strip()


# ── Targeted Ollama HTTP (explicit base URL — Library worker / admin nanobot section) ──


async def health_check_at_base(base_url: str) -> dict:
    """Check if Ollama is reachable at *base_url* (host root, no /api path)."""
    root = _ollama_root(base_url)
    if not root:
        return {"status": "unconfigured", "error": "No Ollama base URL configured", "base_url": ""}
    try:
        if _http_client is not None:
            await _http_client.get(root, timeout=5.0)
        else:
            async with _ephemeral_client(timeout=5.0) as c:
                await c.get(root)
        return {"status": "ok", "base_url": root}
    except Exception as e:
        return {"status": "unreachable", "error": str(e), "base_url": root}


async def health_check() -> dict:
    """Check if Ollama is reachable and return version info."""
    settings = get_settings()
    return await health_check_at_base(settings.OLLAMA_BASE_URL)


async def list_models_at_base(base_url: str) -> list[dict]:
    root = _ollama_root(base_url)
    if not root:
        return []
    url = f"{root}/api/tags"
    try:
        if _http_client is not None:
            resp = await _http_client.get(url, timeout=10.0)
        else:
            async with _ephemeral_client(timeout=10.0) as c:
                resp = await c.get(url)
        resp.raise_for_status()
        return resp.json().get("models", [])
    except Exception as e:
        logging.warning("ollama_client: failed to list models at %s: %s", root, e)
        return []


async def list_models() -> list[dict]:
    """List locally available Ollama models."""
    settings = get_settings()
    return await list_models_at_base(settings.OLLAMA_BASE_URL)


async def list_loaded_models_at_base(base_url: str) -> list[dict]:
    root = _ollama_root(base_url)
    if not root:
        return []
    url = f"{root}/api/ps"
    try:
        if _http_client is not None:
            resp = await _http_client.get(url, timeout=5.0)
        else:
            async with _ephemeral_client(timeout=5.0) as c:
                resp = await c.get(url)
        resp.raise_for_status()
        return resp.json().get("models", [])
    except Exception as e:
        logging.warning("ollama_client: failed to list loaded models at %s: %s", root, e)
        return []


async def list_loaded_models() -> list[dict]:
    """List models currently loaded in Ollama memory via /api/ps."""
    settings = get_settings()
    return await list_loaded_models_at_base(settings.OLLAMA_BASE_URL)


async def get_model_context_window_at_base(base_url: str, name: str) -> int | None:
    root = _ollama_root(base_url)
    if not root:
        return None
    url = f"{root}/api/show"
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
        logging.warning("ollama_client: get_model_context_window failed for '%s' at %s: %s", name, root, e)
    return None


async def get_model_context_window(name: str) -> int | None:
    """Return the context window (num_ctx) for a model via /api/show."""
    settings = get_settings()
    return await get_model_context_window_at_base(settings.OLLAMA_BASE_URL, name)


async def pull_model_at_base(base_url: str, name: str) -> AsyncIterator[dict]:
    root = _ollama_root(base_url)
    if not root:
        raise ValueError("No Ollama base URL configured")
    url = f"{root}/api/pull"
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


async def pull_model(name: str) -> AsyncIterator[dict]:
    """Pull a model from the Ollama registry, streaming progress updates."""
    settings = get_settings()
    async for chunk in pull_model_at_base(settings.OLLAMA_BASE_URL, name):
        yield chunk


async def delete_model_at_base(base_url: str, name: str) -> dict:
    root = _ollama_root(base_url)
    if not root:
        raise ValueError("No Ollama base URL configured")
    url = f"{root}/api/delete"
    if _http_client is not None:
        resp = await _http_client.request("DELETE", url, json={"name": name}, timeout=10.0)
    else:
        async with _ephemeral_client(timeout=10.0) as c:
            resp = await c.request("DELETE", url, json={"name": name})
    resp.raise_for_status()
    return {"status": "deleted", "name": name}


async def delete_model(name: str) -> dict:
    """Delete a model from Ollama."""
    settings = get_settings()
    return await delete_model_at_base(settings.OLLAMA_BASE_URL, name)


async def unload_model_at_base(base_url: str, name: str) -> None:
    root = _ollama_root(base_url)
    if not root:
        raise ValueError("No Ollama base URL configured")
    url = f"{root}/api/generate"
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
        logging.info("ollama_client: unloaded '%s' (base=%s)", name, root)
    except Exception as e:
        logging.warning("ollama_client: unload failed for '%s' at %s: %s", name, root, e)


async def unload_model(name: str) -> None:
    """Immediately evict a model from Ollama memory (keep_alive=0)."""
    settings = get_settings()
    await unload_model_at_base(settings.OLLAMA_BASE_URL, name)


def _ollama_same_base_model(loaded_name: str, want: str) -> bool:
    """True if Ollama model names refer to the same base (tag-agnostic)."""
    if not loaded_name or not want:
        return False
    a = loaded_name.split(":", 1)[0]
    b = want.split(":", 1)[0]
    return a == b


async def preload_model_at_base(base_url: str, name: str, num_ctx: int) -> bool:
    """Load a model at *base_url* with keep_alive=-1. Returns True on HTTP success."""
    root = _ollama_root(base_url)
    if not root:
        return False
    url = f"{root}/api/generate"
    payload: dict = {"model": name, "keep_alive": -1, "stream": False, "options": {"num_ctx": int(num_ctx)}}
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
        logging.info("ollama_client: preloaded '%s' with num_ctx=%s at %s", name, num_ctx, root)
        return True
    except Exception as e:
        logging.warning("ollama_client: preload failed for '%s' at %s: %s", name, root, e)
        return False


async def preload_model(name: str, num_ctx: int | None = None) -> None:
    """Load a model into memory with keep_alive=-1 (never auto-evict).

    Pass ``num_ctx`` to force Ollama to allocate the KV cache for a specific
    context window size on load.  If omitted, the current settings value is used.
    """
    settings = get_settings()
    ctx = num_ctx if num_ctx is not None else settings.OLLAMA_NUM_CTX
    t0 = time.monotonic()
    ok = await preload_model_at_base(settings.OLLAMA_BASE_URL, name, ctx)
    _readiness_metrics["last_preload_ms"] = round((time.monotonic() - t0) * 1000)
    if ok:
        _readiness_metrics["last_preload_at_utc"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )


async def ensure_single_model_loaded_at_base(base_url: str, name: str, num_ctx: int) -> None:
    """Single-model policy at an arbitrary Ollama base (no chat readiness telemetry)."""
    if not str(name).strip():
        return
    try:
        loaded = await list_loaded_models_at_base(base_url)
        for m in loaded:
            other = _ollama_ps_name(m)
            if other and not _ollama_same_base_model(other, name):
                logging.info("ollama_client: evicting '%s' (remote worker policy)", other)
                await unload_model_at_base(base_url, other)
        loaded = await list_loaded_models_at_base(base_url)
        ok = any(
            _ollama_ps_name(m) and _ollama_same_base_model(_ollama_ps_name(m), name)
            for m in loaded
        )
        if not ok:
            await preload_model_at_base(base_url, name, num_ctx)
    except Exception as e:
        logging.warning("ollama_client: ensure_single_model_loaded_at_base failed: %s", e)


async def ensure_single_model_loaded(name: str) -> None:
    """Enforce one-model-in-memory policy: unload non-target models; preload only if needed."""
    t0 = time.monotonic()
    _readiness_metrics["last_ensure_error"] = None
    if not str(name).strip():
        _readiness_metrics["last_ensure_ok"] = None
        _readiness_metrics["last_ensure_ms"] = round((time.monotonic() - t0) * 1000)
        return
    settings = get_settings()
    ok = False
    try:
        loaded = await list_loaded_models_at_base(settings.OLLAMA_BASE_URL)
        for m in loaded:
            other = _ollama_ps_name(m)
            if other and not _ollama_same_base_model(other, name):
                logging.info("ollama_client: evicting '%s' to enforce single-model policy", other)
                await unload_model_at_base(settings.OLLAMA_BASE_URL, other)
        loaded = await list_loaded_models_at_base(settings.OLLAMA_BASE_URL)
        for m in loaded:
            n = _ollama_ps_name(m)
            if n and _ollama_same_base_model(n, name):
                ok = True
                break
        if not ok:
            await preload_model_at_base(settings.OLLAMA_BASE_URL, name, settings.OLLAMA_NUM_CTX)
            loaded = await list_loaded_models_at_base(settings.OLLAMA_BASE_URL)
            ok = any(
                _ollama_ps_name(m) and _ollama_same_base_model(_ollama_ps_name(m), name)
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


class _ThinkTagParser:
    """Parse ``<think>...</think>`` tags from raw response text.

    Defaults to **text mode** — content is treated as visible answer text
    unless an explicit ``<think>`` tag is encountered.  This means
    non-reasoning models pass through cleanly while reasoning models that
    embed ``<think>`` tags (older Ollama versions, or models Ollama does not
    natively separate) are handled correctly.

    Handles tags split across streaming chunks via an internal buffer.
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._in_think = False
        self._buf = ""

    def feed(self, chunk: str):
        """Feed a chunk and yield ``(kind, text)`` pairs."""
        self._buf += chunk
        while self._buf:
            if self._in_think:
                end = self._buf.find(self._CLOSE)
                if end == -1:
                    # Might have a partial closing tag at buffer tail
                    for i in range(1, min(len(self._CLOSE), len(self._buf) + 1)):
                        if self._buf.endswith(self._CLOSE[:i]):
                            emit = self._buf[:-i]
                            if emit:
                                yield ("thinking", emit)
                            self._buf = self._buf[-i:]
                            return
                    yield ("thinking", self._buf)
                    self._buf = ""
                else:
                    if end > 0:
                        yield ("thinking", self._buf[:end])
                    self._buf = self._buf[end + len(self._CLOSE):]
                    if self._buf.startswith("\n"):
                        self._buf = self._buf[1:]
                    self._in_think = False
            else:
                start = self._buf.find(self._OPEN)
                if start == -1:
                    # Might have a partial opening tag at buffer tail
                    for i in range(1, min(len(self._OPEN), len(self._buf) + 1)):
                        if self._buf.endswith(self._OPEN[:i]):
                            emit = self._buf[:-i]
                            if emit:
                                yield ("text", emit)
                            self._buf = self._buf[-i:]
                            return
                    yield ("text", self._buf)
                    self._buf = ""
                else:
                    if start > 0:
                        yield ("text", self._buf[:start])
                    self._buf = self._buf[start + len(self._OPEN):]
                    if self._buf.startswith("\n"):
                        self._buf = self._buf[1:]
                    self._in_think = True

    def flush(self):
        """Emit any remaining buffered content."""
        if self._buf:
            yield ("thinking" if self._in_think else "text", self._buf)
            self._buf = ""


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
    visible answer tokens.

    ``think`` is set from ``CHAT_THINK_LEVEL`` (low/medium/high for GPT-OSS) or
    ``settings.CHAT_ENABLE_THINKING`` as a boolean.  Three complementary strategies still ensure
    every model works regardless of Ollama version when thinking is on:

    1. **Native separation** — the ``thinking`` field from Ollama is yielded
       directly as ``("thinking", ...)``.
    2. **Tag fallback** — the ``response`` field is fed through
       ``_ThinkTagParser`` which detects ``<think>...</think>`` tags
       (older Ollama or unrecognised models).
    3. **Promotion safety net** — the caller (``chat_service``) re-emits
       thinking as text if the model produced no visible response (e.g. a
       model that spent its entire token budget on reasoning).

    If *latency* is a dict it is filled with:
    - ollama_connect_ms: time until HTTP stream is ready
    - ttft_ms: time until first non-empty model token (thinking or text)
    - stream_total_ms: time until stream completes
    """
    settings = get_settings()
    model = model or settings.OLLAMA_MODEL
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/generate"

    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "think": _ollama_think_request_value(),
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
        parser = _ThinkTagParser()
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
                    # Native thinking field (populated by Ollama for recognised
                    # thinking models).  Use `or ""` to normalise None→"".
                    native_thinking = chunk.get("thinking") or ""
                    raw_text = chunk.get("response") or ""

                    if (native_thinking or raw_text) and latency is not None and not ttft_recorded:
                        latency["ttft_ms"] = round((time.monotonic() - t_req) * 1000)
                        ttft_recorded = True

                    if native_thinking:
                        yield ("thinking", native_thinking)
                    if raw_text:
                        for pair in parser.feed(raw_text):
                            yield pair

                    if chunk.get("done", False):
                        for pair in parser.flush():
                            yield pair
                        _capture_inference_stats(chunk)
                        if latency is not None:
                            latency["stream_total_ms"] = round((time.monotonic() - t_req) * 1000)
                        return
                except Exception:
                    continue
        for pair in parser.flush():
            yield pair
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

    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": _ollama_think_request_value(),
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
        parser = _ThinkTagParser()
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
                    msg = chunk.get("message") or {}
                    native_thinking = msg.get("thinking") or ""
                    raw_text = msg.get("content") or ""

                    if (native_thinking or raw_text) and latency is not None and not ttft_recorded:
                        latency["ttft_ms"] = round((time.monotonic() - t_req) * 1000)
                        ttft_recorded = True

                    if native_thinking:
                        yield ("thinking", native_thinking)
                    if raw_text:
                        for pair in parser.feed(raw_text):
                            yield pair

                    if chunk.get("done", False):
                        for pair in parser.flush():
                            yield pair
                        _capture_inference_stats(chunk)
                        if latency is not None:
                            latency["stream_total_ms"] = round((time.monotonic() - t_req) * 1000)
                        return
                except Exception:
                    continue
        for pair in parser.flush():
            yield pair
        if latency is not None and latency.get("stream_total_ms") is None:
            latency["stream_total_ms"] = round((time.monotonic() - t_req) * 1000)

    if _http_client is not None:
        async for item in _run_chat_stream(_http_client):
            yield item
    else:
        async with httpx.AsyncClient(timeout=stream_timeout) as c:
            async for item in _run_chat_stream(c):
                yield item

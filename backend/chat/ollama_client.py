# -*- coding: utf-8 -*-
"""Async Ollama REST API client with streaming support."""
import json
import logging
import time
from typing import AsyncIterator

import httpx

from backend.agent_debug_log import agent_debug_log
from backend.config import get_settings

# ── Last-inference performance snapshot (updated after every generate/chat) ───
_last_inference_stats: dict = {
    "tokens_per_sec": None,
    "prompt_tokens": None,
    "completion_tokens": None,
}


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


async def health_check() -> dict:
    """Check if Ollama is reachable and return version info."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.get(settings.OLLAMA_BASE_URL)
            return {"status": "ok", "base_url": settings.OLLAMA_BASE_URL}
    except Exception as e:
        return {"status": "unreachable", "error": str(e), "base_url": settings.OLLAMA_BASE_URL}


async def list_models() -> list[dict]:
    """List locally available Ollama models."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            return resp.json().get("models", [])
    except Exception as e:
        logging.warning(f"ollama_client: failed to list models: {e}")
        return []


async def list_loaded_models() -> list[dict]:
    """List models currently loaded in Ollama memory via /api/ps."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.OLLAMA_BASE_URL}/api/ps")
            resp.raise_for_status()
            return resp.json().get("models", [])
    except Exception as e:
        logging.warning(f"ollama_client: failed to list loaded models: {e}")
        return []


async def get_model_context_window(name: str) -> int | None:
    """Return the context window (num_ctx) for a model via /api/show."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/show",
                json={"name": name},
            )
            resp.raise_for_status()
            data = resp.json()
            # Ollama ≥ 0.3 — architecture-specific keys in model_info
            for key, val in data.get("model_info", {}).items():
                if "context_length" in key.lower():
                    return int(val)
            # Fallback: parse the parameters string for num_ctx
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
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=600.0, write=10.0, pool=10.0)
    ) as client:
        async with client.stream(
            "POST",
            f"{settings.OLLAMA_BASE_URL}/api/pull",
            json={"name": name},
        ) as resp:
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
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.request(
            "DELETE",
            f"{settings.OLLAMA_BASE_URL}/api/delete",
            json={"name": name},
        )
        resp.raise_for_status()
        return {"status": "deleted", "name": name}


async def unload_model(name: str) -> None:
    """Immediately evict a model from Ollama memory (keep_alive=0)."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={"model": name, "keep_alive": 0, "stream": False},
            )
        logging.info(f"ollama_client: unloaded '{name}'")
    except Exception as e:
        logging.warning(f"ollama_client: unload failed for '{name}': {e}")


async def preload_model(name: str) -> None:
    """Load a model into memory with keep_alive=-1 (never auto-evict)."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
        ) as client:
            resp = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/generate",
                json={"model": name, "keep_alive": -1, "stream": False},
            )
            resp.raise_for_status()
        logging.info(f"ollama_client: preloaded '{name}'")
    except Exception as e:
        logging.warning(f"ollama_client: preload failed for '{name}': {e}")


async def ensure_single_model_loaded(name: str) -> None:
    """Enforce one-model-in-memory policy: unload all others, then preload target."""
    loaded = await list_loaded_models()
    for m in loaded:
        other = m.get("name", "")
        if other and other != name:
            logging.info(f"ollama_client: evicting '{other}' to enforce single-model policy")
            await unload_model(other)
    await preload_model(name)


async def generate_stream(
    prompt: str,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> AsyncIterator[str]:
    """Stream a completion from Ollama, yielding text chunks."""
    settings = get_settings()
    model = model or settings.OLLAMA_MODEL

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": -1,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": settings.OLLAMA_NUM_CTX,
        },
    }
    if system:
        payload["system"] = system

    # region agent log
    _t_os = time.monotonic()
    _first_os = True
    _host = settings.OLLAMA_BASE_URL.split("://", 1)[-1].split("/")[0][:120]
    agent_debug_log("H3", "ollama_client.py:generate_stream", "stream_start", {
        "model": model,
        "ollama_host": _host,
    })
    # endregion

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
    ) as client:
        async with client.stream(
            "POST",
            f"{settings.OLLAMA_BASE_URL}/api/generate",
            json=payload,
        ) as resp:
            resp.raise_for_status()
            # region agent log
            agent_debug_log("H3", "ollama_client.py:generate_stream", "http_stream_ready", {
                "ms_after_stream_start": round((time.monotonic() - _t_os) * 1000),
            })
            # endregion
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    text = chunk.get("response", "")
                    if text:
                        # region agent log
                        if _first_os:
                            _first_os = False
                            agent_debug_log("H2", "ollama_client.py:generate_stream", "first_token", {
                                "ms_since_stream_start": round((time.monotonic() - _t_os) * 1000),
                            })
                        # endregion
                        yield text
                    if chunk.get("done", False):
                        _capture_inference_stats(chunk)
                        return
                except Exception:
                    continue


async def generate(
    prompt: str,
    system: str = "",
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> str:
    """Non-streaming completion — collects full response."""
    parts = []
    async for chunk in generate_stream(prompt, system, model, temperature, max_tokens):
        parts.append(chunk)
    return "".join(parts)


async def chat_stream(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> AsyncIterator[str]:
    """Stream a chat completion from Ollama /api/chat, yielding text chunks."""
    settings = get_settings()
    model = model or settings.OLLAMA_MODEL

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "keep_alive": -1,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": settings.OLLAMA_NUM_CTX,
        },
    }

    # region agent log
    _t_cs = time.monotonic()
    _first_cs = True
    _chost = settings.OLLAMA_BASE_URL.split("://", 1)[-1].split("/")[0][:120]
    agent_debug_log("H3", "ollama_client.py:chat_stream", "stream_start", {
        "model": model,
        "ollama_host": _chost,
    })
    # endregion

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
    ) as client:
        async with client.stream(
            "POST",
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json=payload,
        ) as resp:
            resp.raise_for_status()
            # region agent log
            agent_debug_log("H3", "ollama_client.py:chat_stream", "http_stream_ready", {
                "ms_after_stream_start": round((time.monotonic() - _t_cs) * 1000),
            })
            # endregion
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    text = chunk.get("message", {}).get("content", "")
                    if text:
                        # region agent log
                        if _first_cs:
                            _first_cs = False
                            agent_debug_log("H2", "ollama_client.py:chat_stream", "first_token", {
                                "ms_since_stream_start": round((time.monotonic() - _t_cs) * 1000),
                            })
                        # endregion
                        yield text
                    if chunk.get("done", False):
                        _capture_inference_stats(chunk)
                        return
                except Exception:
                    continue

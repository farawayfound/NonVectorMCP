# -*- coding: utf-8 -*-
"""Async Ollama REST API client with streaming support."""
import json
import logging
from typing import AsyncIterator

import httpx

from backend.config import get_settings


async def health_check() -> dict:
    """Check if Ollama is reachable and return version info."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(settings.OLLAMA_BASE_URL)
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
            data = resp.json()
            return data.get("models", [])
    except Exception as e:
        logging.warning(f"ollama_client: failed to list models: {e}")
        return []


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
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    if system:
        payload["system"] = system

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)) as client:
        async with client.stream(
            "POST",
            f"{settings.OLLAMA_BASE_URL}/api/generate",
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    import json
                    chunk = json.loads(line)
                    text = chunk.get("response", "")
                    if text:
                        yield text
                    if chunk.get("done", False):
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
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)) as client:
        async with client.stream(
            "POST",
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    import json
                    chunk = json.loads(line)
                    text = chunk.get("message", {}).get("content", "")
                    if text:
                        yield text
                    if chunk.get("done", False):
                        return
                except Exception:
                    continue

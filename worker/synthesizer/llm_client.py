# -*- coding: utf-8 -*-
"""Ollama HTTP client for the worker — mirrors the backend's pattern."""
from __future__ import annotations

import logging

import httpx

import config

log = logging.getLogger(__name__)


async def generate(prompt: str, system: str = "", temperature: float = 0.3) -> str:
    """Call Ollama /api/generate and return the full response text."""
    payload: dict = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_ctx": config.OLLAMA_NUM_CTX,
        },
    }
    if system:
        payload["system"] = system

    async with httpx.AsyncClient(timeout=config.OLLAMA_TIMEOUT) as client:
        resp = await client.post(f"{config.OLLAMA_BASE_URL}/api/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()

    text = data.get("response", "")
    log.info("ollama generate: %d chars, model=%s", len(text), config.OLLAMA_MODEL)
    return text


async def quick_generate(prompt: str) -> str:
    """Lightweight wrapper for search-query generation."""
    return await generate(prompt, temperature=0.5)

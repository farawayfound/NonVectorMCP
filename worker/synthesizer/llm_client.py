# -*- coding: utf-8 -*-
"""Ollama HTTP client for the worker — mirrors the backend's pattern."""
from __future__ import annotations

import logging

import httpx

import config
from agent_debug_log import agent_log

log = logging.getLogger(__name__)


async def generate(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    num_predict: int | None = None,
    *,
    model: str | None = None,
    num_ctx: int | None = None,
) -> str:
    """Call Ollama and return the assistant text.

    Uses ``POST /api/chat`` with ``stream: false`` (not ``/api/generate``).  For
    Gemma 4 and other thinking models, Ollama's generate endpoint can still leave
    the visible field empty while filling ``thinking``; chat + top-level
    ``think: false`` matches the known-good path from upstream issue discussion.
    """
    use_model = model or config.OLLAMA_MODEL
    use_ctx = int(num_ctx) if num_ctx is not None else config.OLLAMA_NUM_CTX
    options: dict = {
        "temperature": temperature,
        "num_ctx": use_ctx,
    }
    if num_predict is not None:
        options["num_predict"] = int(num_predict)
    elif len(prompt or "") + len(system or "") > 12000:
        # Long synthesis prompts need enough output budget for a full report.
        options["num_predict"] = 12288

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict = {
        "model": use_model,
        "messages": messages,
        "stream": False,
        "think": False,
        "keep_alive": -1,
        "options": options,
    }

    base = config.OLLAMA_BASE_URL.rstrip("/")
    url = f"{base}/api/chat"
    read_sec = float(max(int(config.OLLAMA_TIMEOUT), 900))
    timeout = httpx.Timeout(connect=30.0, read=read_sec, write=30.0, pool=30.0)
    # #region agent log
    agent_log(
        hypothesis_id="H3",
        location="llm_client.py:generate:pre_http",
        message="ollama_chat_start",
        data={
            "model": use_model,
            "num_ctx": use_ctx,
            "base_host": base.split("://")[-1][:80],
            "prompt_len": len(prompt or ""),
            "has_system": bool(system),
            "read_timeout_sec": int(read_sec),
            "endpoint": "/api/chat",
        },
    )
    # #endregion
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("error"):
                raise RuntimeError(str(data["error"]).strip())
    except Exception as exc:
        # #region agent log
        agent_log(
            hypothesis_id="H3",
            location="llm_client.py:generate:error",
            message="ollama_chat_failed",
            data={"model": use_model, "err_type": type(exc).__name__, "err": str(exc)[:500]},
        )
        # #endregion
        raise

    msg = data.get("message") or {}
    text = str(msg.get("content") or "")
    think_raw = str(msg.get("thinking") or "")
    # #region agent log
    agent_log(
        hypothesis_id="H3",
        location="llm_client.py:generate:success",
        message="ollama_chat_done",
        data={
            "model": use_model,
            "response_len": len(text),
            "thinking_len": len(think_raw),
        },
    )
    # #endregion
    log.info("ollama chat: %d chars, model=%s", len(text), use_model)
    return text


async def quick_generate(
    prompt: str,
    *,
    model: str | None = None,
    num_ctx: int | None = None,
) -> str:
    """Lightweight wrapper for search-query generation."""
    return await generate(prompt, temperature=0.5, model=model, num_ctx=num_ctx)

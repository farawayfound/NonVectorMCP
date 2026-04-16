# -*- coding: utf-8 -*-
"""Ollama HTTP client for the worker — mirrors the backend's pattern."""
from __future__ import annotations

import logging
from typing import Any

import httpx

import config

log = logging.getLogger(__name__)


def _ollama_generate_url() -> str:
    return f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/generate"


def _format_ollama_http_error(resp: httpx.Response, *, model: str) -> str:
    """Ollama uses 404 for unknown model tags on POST /api/generate (not 'route missing')."""
    detail = ""
    try:
        body: Any = resp.json()
        if isinstance(body, dict) and body.get("error"):
            detail = f" — {body['error']}"
    except Exception:
        t = (resp.text or "").strip()
        if t:
            detail = f" — {t[:500]}"
    if resp.status_code == 404:
        return (
            f"Ollama HTTP 404 at {resp.request.url}{detail}. "
            f"This almost always means the model tag {model!r} is not installed locally "
            f"(run `ollama pull {model}` and check `ollama list`), or OLLAMA_BASE_URL points at a "
            f"server that is not Ollama (wrong port/proxy)."
        )
    return f"Ollama HTTP {resp.status_code} for {resp.request.url}{detail}"


async def verify_ollama_model_tag() -> None:
    """Best-effort: warn at startup if /api/tags does not list the configured model."""
    base = config.OLLAMA_BASE_URL.rstrip("/")
    model = config.OLLAMA_MODEL
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            r = await client.get(f"{base}/api/tags")
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        log.warning("ollama: could not GET /api/tags (%s); skipping model check", exc)
        return
    names = [str(m.get("name", "")).strip() for m in data.get("models", []) if m.get("name")]
    if model in names:
        log.info("ollama: model tag %r is present (%d local models)", model, len(names))
        return
    sample = ", ".join(names[:15]) if names else "(none)"
    log.error(
        "ollama: model tag %r is NOT in `ollama list` / GET /api/tags. "
        "POST /api/generate will return HTTP 404 until you install it, e.g. `ollama pull %s`. "
        "Or set OLLAMA_MODEL to an exact name from: %s",
        model,
        model,
        sample,
    )


async def generate(
    prompt: str,
    system: str = "",
    temperature: float = 0.3,
    num_predict: int | None = None,
    *,
    model: str | None = None,
    num_ctx: int | None = None,
) -> str:
    """Call Ollama ``/api/generate`` (non-streaming) and return the response text.

    Same shape as pre–Force-26B / Carousel-era worker code.  For ``gemma4:26b``,
    ``think: false`` must be top-level so the model fills ``response`` instead of
    only ``thinking``.  Surfaces JSON ``error`` and falls back to ``thinking`` if
    ``response`` is empty.
    """
    use_model = model or config.OLLAMA_MODEL
    use_ctx = int(num_ctx) if num_ctx is not None else config.OLLAMA_NUM_CTX
    options: dict = {
        "temperature": temperature,
        "num_ctx": use_ctx,
    }
    if num_predict is not None:
        options["num_predict"] = int(num_predict)

    payload: dict = {
        "model": use_model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": options,
    }
    if system:
        payload["system"] = system

    read_sec = float(max(int(config.OLLAMA_TIMEOUT), 600))
    timeout = httpx.Timeout(connect=30.0, read=read_sec, write=30.0, pool=30.0)
    url = _ollama_generate_url()
    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
        resp = await client.post(url, json=payload)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(_format_ollama_http_error(exc.response, model=use_model)) from exc
        data = resp.json()
        if data.get("error"):
            raise RuntimeError(str(data["error"]).strip())

    text = str(data.get("response") or "").strip()
    thinking = str(data.get("thinking") or "").strip()
    if not text and thinking:
        log.warning(
            "ollama generate: empty response, using thinking (%d chars), model=%s",
            len(thinking),
            use_model,
        )
        text = thinking

    log.info("ollama generate: %d chars, model=%s", len(text), use_model)
    return text


async def quick_generate(
    prompt: str,
    *,
    model: str | None = None,
    num_ctx: int | None = None,
) -> str:
    """Lightweight wrapper for search-query generation."""
    return await generate(prompt, temperature=0.5, model=model, num_ctx=num_ctx)

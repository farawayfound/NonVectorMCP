# -*- coding: utf-8 -*-
"""Full research pipeline: search -> scrape -> synthesize."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Coroutine, Optional

import config
from crawler.search import run_search
from crawler.scraper import scrape_urls
from synthesizer.llm_client import generate, quick_generate
from synthesizer.prompts import build_synthesis_prompt, system_for_format

log = logging.getLogger(__name__)

StatusCallback = Callable[..., Coroutine[Any, Any, None]]
CancelCheck = Optional[Callable[[], Awaitable[bool]]]


class JobCancelledError(Exception):
    """Raised when the API sets a cooperative-cancel flag (Redis) mid-run."""


async def run_pipeline(
    job,
    status_cb: StatusCallback | None = None,
    cancel_check: CancelCheck = None,
) -> dict:
    """Execute the full research pipeline and return the artifact.

    Returns dict with keys: markdown, sources, summary.
    """

    async def _status(status: str, msg: str, progress: float = 0.0, sources: int = 0):
        if status_cb:
            await status_cb(status, msg, progress, sources)

    async def _abort_if_cancelled() -> None:
        if cancel_check is None:
            return
        try:
            if await cancel_check():
                raise JobCancelledError()
        except JobCancelledError:
            raise
        except Exception as exc:
            log.debug("cancel_check failed (ignored): %s", exc)

    # -- Phase 1: Search ---------------------------------------------------
    await _abort_if_cancelled()
    await _status("crawling", "Searching the web...", 0.1)

    search_results = await run_search(
        prompt=job.prompt,
        max_results=job.max_sources,
        llm_fn=quick_generate,
    )

    await _abort_if_cancelled()

    if not search_results:
        raise RuntimeError("No search results found for the given prompt.")

    urls = [r.url for r in search_results]
    await _status("crawling", f"Found {len(urls)} URLs — scraping pages...", 0.3, len(urls))

    # -- Phase 2: Scrape ---------------------------------------------------
    pages = await scrape_urls(
        urls,
        max_concurrent=config.MAX_CONCURRENT_SCRAPES,
        timeout=config.SCRAPE_TIMEOUT,
    )

    await _abort_if_cancelled()

    good_pages = [p for p in pages if p.success and len(p.content) > 100]
    if not good_pages:
        raise RuntimeError("All page scrapes failed or returned empty content.")

    await _status(
        "synthesizing",
        f"Scraped {len(good_pages)}/{len(pages)} pages — synthesizing report...",
        0.6, len(good_pages),
    )

    # -- Phase 3: Synthesize -----------------------------------------------
    sources_for_llm = []
    for i, page in enumerate(good_pages):
        sr = next((r for r in search_results if r.url == page.url), None)
        sources_for_llm.append({
            "url": page.url,
            "title": page.title or (sr.title if sr else f"Source {i+1}"),
            "content": page.content,
        })

    await _abort_if_cancelled()
    target_tokens = int(getattr(job, "target_tokens", 1500) or 1500)
    output_format = getattr(job, "output_format", "default") or "default"
    user_prompt = build_synthesis_prompt(
        job.prompt, sources_for_llm, target_tokens=target_tokens,
    )
    # Give the model ~15% headroom over the target so it can close the report
    # cleanly without being cut off mid-sentence by num_predict.
    num_predict = int(target_tokens * 1.15) + 64
    markdown = await generate(
        user_prompt,
        system=system_for_format(output_format),
        temperature=0.3,
        num_predict=num_predict,
    )

    await _abort_if_cancelled()

    if not markdown or len(markdown.strip()) < 100:
        raise RuntimeError("LLM synthesis returned empty or too-short output.")

    await _status("synthesizing", "Generating summary...", 0.9, len(good_pages))

    await _abort_if_cancelled()
    summary = await generate(
        f"Summarize in 2-3 sentences:\n\n{markdown[:3000]}",
        temperature=0.2,
    )

    source_list = [
        {"url": s["url"], "title": s["title"]}
        for s in sources_for_llm
    ]

    log.info(
        "pipeline complete: %d chars markdown, %d sources",
        len(markdown), len(source_list),
    )

    return {
        "markdown": markdown,
        "sources": source_list,
        "summary": summary.strip(),
    }

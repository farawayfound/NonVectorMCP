# -*- coding: utf-8 -*-
"""Web search via DuckDuckGo — returns ranked URLs for a research prompt."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from duckduckgo_search import DDGS

log = logging.getLogger(__name__)


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str


async def generate_search_queries(prompt: str, llm_fn=None) -> list[str]:
    """Break a research prompt into 3-5 targeted search queries.

    If *llm_fn* is provided it should be an async callable(prompt)->str that
    calls the local Ollama instance.  Falls back to simple heuristic splitting.
    """
    if llm_fn:
        try:
            system = (
                "You are a search-query generator. Given a research topic, "
                "output 3-5 concise DuckDuckGo search queries (one per line, "
                "no numbering, no explanation)."
            )
            raw = await llm_fn(f"{system}\n\nTopic: {prompt}")
            queries = [q.strip().strip('"').strip("'") for q in raw.strip().splitlines() if q.strip()]
            if queries:
                return queries[:5]
        except Exception as exc:
            log.warning("LLM query generation failed, using fallback: %s", exc)

    queries = [prompt]
    words = prompt.split()
    if len(words) > 6:
        queries.append(" ".join(words[:6]))
    queries.append(f"{prompt} 2025 2026")
    return queries[:5]


def search_ddg(query: str, max_results: int = 10) -> list[SearchResult]:
    """Run a single DuckDuckGo text search."""
    results: list[SearchResult] = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(SearchResult(
                    url=r.get("href", r.get("link", "")),
                    title=r.get("title", ""),
                    snippet=r.get("body", r.get("snippet", "")),
                ))
    except Exception as exc:
        log.warning("DuckDuckGo search failed for %r: %s", query, exc)
    return results


async def run_search(
    prompt: str,
    max_results: int = 10,
    llm_fn=None,
) -> list[SearchResult]:
    """Generate queries and aggregate deduplicated search results."""
    queries = await generate_search_queries(prompt, llm_fn=llm_fn)
    seen_urls: set[str] = set()
    all_results: list[SearchResult] = []

    for q in queries:
        hits = search_ddg(q, max_results=max_results)
        for r in hits:
            if r.url and r.url not in seen_urls:
                seen_urls.add(r.url)
                all_results.append(r)
            if len(all_results) >= max_results:
                break
        if len(all_results) >= max_results:
            break

    log.info("search returned %d unique URLs from %d queries", len(all_results), len(queries))
    return all_results[:max_results]

# -*- coding: utf-8 -*-
"""Page scraper using Crawl4AI for clean content extraction."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class ScrapedPage:
    url: str
    title: str
    content: str
    success: bool
    error: str = ""


async def scrape_url(url: str, timeout: int = 30) -> ScrapedPage:
    """Scrape a single URL and return its cleaned text content."""
    try:
        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

        config = CrawlerRunConfig(
            word_count_threshold=50,
            page_timeout=timeout * 1000,
        )
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)

        if result.success:
            content = result.markdown_v2.raw_markdown if hasattr(result, "markdown_v2") else result.markdown
            return ScrapedPage(
                url=url,
                title=result.metadata.get("title", "") if result.metadata else "",
                content=content or "",
                success=True,
            )
        return ScrapedPage(url=url, title="", content="", success=False, error="crawl failed")

    except ImportError:
        return await _fallback_scrape(url, timeout)
    except Exception as exc:
        log.warning("crawl4ai failed for %s: %s — trying fallback", url, exc)
        return await _fallback_scrape(url, timeout)


async def _fallback_scrape(url: str, timeout: int = 30) -> ScrapedPage:
    """Lightweight fallback using httpx + basic HTML stripping."""
    try:
        import httpx
        import re

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; ChunkyPotato-Research/1.0)"
            })
            resp.raise_for_status()
            html = resp.text

        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""

        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        return ScrapedPage(url=url, title=title, content=text[:50000], success=bool(text))
    except Exception as exc:
        log.warning("fallback scrape failed for %s: %s", url, exc)
        return ScrapedPage(url=url, title="", content="", success=False, error=str(exc))


async def scrape_urls(
    urls: list[str],
    max_concurrent: int = 4,
    timeout: int = 30,
) -> list[ScrapedPage]:
    """Scrape multiple URLs with bounded concurrency."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _bounded(url: str) -> ScrapedPage:
        async with semaphore:
            return await scrape_url(url, timeout=timeout)

    tasks = [_bounded(u) for u in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    pages: list[ScrapedPage] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            log.warning("scrape exception for %s: %s", urls[i], r)
            pages.append(ScrapedPage(url=urls[i], title="", content="", success=False, error=str(r)))
        else:
            pages.append(r)

    succeeded = sum(1 for p in pages if p.success)
    log.info("scraped %d/%d URLs successfully", succeeded, len(urls))
    return pages

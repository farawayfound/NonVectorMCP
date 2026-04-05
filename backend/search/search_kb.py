# -*- coding: utf-8 -*-
"""ChunkyLink knowledge base search engine — multi-phase ranked retrieval."""
import re
import json
import logging
import threading
import time
import hashlib
import asyncio
from pathlib import Path
from typing import Any

from backend.agent_debug_log import agent_debug_log
from backend.config import get_settings
from backend.logger import log_event

_QUERY_SYNTAX_RE = None  # Removed: no longer needed for general-purpose classification

_LEVELS: dict[str, dict[str, int]] = {
    "Quick":      {"Phase1": 12,  "Phase3": 5,                                   "Phase6": 3,   "Total": 20},
    "Standard":   {"Phase1": 45,  "Phase3": 55,  "Phase4": 25,                  "Phase6": 40,  "Total": 165},
    "Deep":       {"Phase1": 90,  "Phase3": 110, "Phase4": 50,                  "Phase6": 80,  "Phase7": 20, "Phase8": 70,  "Total": 420},
    "Exhaustive": {"Phase1": 180, "Phase3": 220, "Phase4": 100,                 "Phase6": 160, "Phase7": 40, "Phase8": 140, "Total": 840},
}

_DOMAIN_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("experience", re.compile(r'\b(work|job|role|company|position|career|employ)\b', re.I)),
    ("skills",     re.compile(r'\b(skill|technology|framework|language|tool|proficien|stack)\b', re.I)),
    ("education",  re.compile(r'\b(education|degree|university|college|certif|school|gpa)\b', re.I)),
    ("glossary",   re.compile(r'\b(what does|mean|definition|acronym|stands for)\b', re.I)),
]

_RESULT_CACHE: dict[str, dict] = {}
_CACHE_MAX = 50
# Full index list keyed only by on-disk KB files (not query-derived domains).
# Domains vary per query; filtering domain_chunks in memory is cheap vs disk I/O.
_ALL_CHUNKS_CACHE: dict[str, list] = {}
_ALL_CHUNKS_CACHE_MAX = 3
_all_chunks_cache_lock = threading.Lock()


def _kb_data_signature(kb_dir: Path) -> str:
    """Hash KB path + chunk file mtimes/sizes; invalidates when index is rebuilt."""
    parts: list[str] = [str(kb_dir.resolve())]
    detail = kb_dir / "detail"
    if detail.exists():
        for f in sorted(detail.glob("chunks*.jsonl")):
            try:
                st = f.stat()
                parts.append(f"{f.name}:{st.st_mtime_ns}:{st.st_size}")
            except OSError:
                continue
    raw = "|".join(parts)
    return hashlib.md5(raw.encode()).hexdigest()


def _get_cached_all_chunks(sig: str) -> list | None:
    with _all_chunks_cache_lock:
        return _ALL_CHUNKS_CACHE.get(sig)


def _set_cached_all_chunks(sig: str, all_chunks: list) -> None:
    with _all_chunks_cache_lock:
        if len(_ALL_CHUNKS_CACHE) >= _ALL_CHUNKS_CACHE_MAX:
            _ALL_CHUNKS_CACHE.pop(next(iter(_ALL_CHUNKS_CACHE)))
        _ALL_CHUNKS_CACHE[sig] = all_chunks


def _get_tag_stoplist() -> frozenset:
    return frozenset(get_settings().TAG_STOPLIST)


def _get_default_domains() -> list[str]:
    return list(get_settings().DEFAULT_SEARCH_DOMAINS)


def _get_domains_from_query(query: str) -> list[str]:
    domains = list(_get_default_domains())
    for domain, pattern in _DOMAIN_PATTERNS:
        if pattern.search(query):
            domains.append(domain)
    return list(dict.fromkeys(domains))


def _safe_load_jsonl(path: Path) -> list[dict]:
    chunks = []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            s = line.strip()
            if not s:
                continue
            try:
                c = json.loads(s)
                c["_sl"] = ((c.get("text") or "") + " " + (c.get("search_text") or "")[:500]).lower()
                chunks.append(c)
            except json.JSONDecodeError:
                pass
    return chunks


def _load_all_category_chunks(kb_dir: Path) -> list[dict]:
    chunks = []
    detail = kb_dir / "detail"
    if not detail.exists():
        return chunks
    for f in sorted(detail.glob("chunks.*.jsonl")):
        if f.name == "chunks.jsonl":
            continue
        chunks.extend(_safe_load_jsonl(f))
    return chunks


def _filter_domain_chunks(all_chunks: list, domains: list[str]) -> list[dict]:
    domain_set = set(domains)
    return [c for c in all_chunks if domain_set & set(c.get("tags", []))]


def _matches_terms(chunk: dict, terms: list[str], min_hits: int = 2) -> bool:
    combined = chunk.get("_sl", "")
    return sum(1 for t in terms if t.lower() in combined) >= min_hits


def _score_chunk(chunk: dict, terms: list[str], top_tags: list[str],
                 discovered_keywords: list[str], match_type: str) -> float:
    tag_stoplist = _get_tag_stoplist()
    sl = chunk.get("_sl", "")
    term_score = sum(min(10, sl.count(t.lower()) * 2) for t in terms)
    score = min(40, term_score)
    if top_tags:
        score += min(20, sum(4 for tag in chunk.get("tags", [])
                             if tag in top_tags and tag not in tag_stoplist))
    if discovered_keywords and chunk.get("search_keywords"):
        score += min(15, sum(3 for kw in chunk.get("search_keywords", [])
                             if kw in discovered_keywords))
    phase_bonus = {"Initial": 10, "Related": 7, "Query": 5, "DeepDive": 3}
    score += phase_bonus.get(match_type, 2)
    return round(score, 2)


async def search(
    terms: list[str],
    query: str = "",
    level: str = "Standard",
    kb_dir: str | Path | None = None,
    domains: list[str] | None = None,
    max_results: int = 0,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Search the JSONL knowledge base across all phases."""
    if not terms:
        return {"error": "terms is required", "results": [], "total": 0}

    settings = get_settings()
    if kb_dir is None:
        kb_dir = settings.INDEXES_DIR / "demo"
    kb_dir = Path(kb_dir)

    if not domains and query:
        domains = _get_domains_from_query(query)
    active_domains = domains or _get_default_domains()

    limits = _LEVELS.get(level, _LEVELS["Standard"])
    page = max(1, int(page))
    if max_results == 0:
        max_results = limits["Total"]

    return await asyncio.to_thread(
        _search_sync, terms, query, level, active_domains, max_results, page,
        page_size, limits, kb_dir
    )


def _search_sync(
    terms: list[str], query: str, level: str, active_domains: list[str],
    max_results: int, page: int, page_size: int, limits: dict, kb_dir: Path,
) -> dict:
    t0 = time.monotonic()
    tag_stoplist = _get_tag_stoplist()
    quick_search = level == "Quick"
    deep_search = level in ("Deep", "Exhaustive")

    sig = _kb_data_signature(kb_dir)
    cached_all = _get_cached_all_chunks(sig)
    if cached_all is not None:
        all_chunks = cached_all
        load_ms = 0
        cache_hit = True
    else:
        # region agent log
        _tl0 = time.monotonic()
        # endregion
        all_chunks = _load_all_category_chunks(kb_dir)
        if not all_chunks:
            fallback = kb_dir / "detail" / "chunks.jsonl"
            if fallback.exists():
                all_chunks = _safe_load_jsonl(fallback)
        _set_cached_all_chunks(sig, all_chunks)
        # region agent log
        load_ms = round((time.monotonic() - _tl0) * 1000)
        # endregion
        cache_hit = False

    domain_chunks = _filter_domain_chunks(all_chunks, active_domains)
    if not domain_chunks:
        domain_chunks = all_chunks

    # region agent log
    agent_debug_log("H1", "search_kb.py:_search_sync", "chunks_loaded", {
        "count": len(all_chunks),
        "load_ms": load_ms,
        "kb_dir": kb_dir.name,
        "level": level,
        "cache_hit": cache_hit,
    })
    # endregion
    all_by_id = {c["id"]: c for c in all_chunks}

    # Phase 1: Initial domain search
    phase1 = [c for c in domain_chunks if _matches_terms(c, terms, min_hits=2)]
    if not phase1:
        phase1 = [c for c in domain_chunks if _matches_terms(c, terms, min_hits=1)]
    if not phase1:
        return {"results": [], "total": 0, "level": level, "phases": {}, "page": 1, "total_pages": 0}

    # Phase 2: Discover tags/keywords
    tag_freq: dict[str, int] = {}
    for c in phase1:
        for tag in c.get("tags", []):
            if tag not in tag_stoplist:
                tag_freq[tag] = tag_freq.get(tag, 0) + 1
    min_freq = max(2, int(len(phase1) * 0.2))
    top_tags = [t for t, n in sorted(tag_freq.items(), key=lambda x: -x[1]) if n >= min_freq][:15]

    kw_freq: dict[str, int] = {}
    for c in phase1:
        for kw in c.get("search_keywords", []):
            if kw and len(kw) >= 3:
                kw_freq[kw] = kw_freq.get(kw, 0) + 1
    discovered_keywords = [k for k, n in sorted(kw_freq.items(), key=lambda x: -x[1]) if n >= 2][:20]

    # Phase 3: Related chunks
    ref_freq: dict[str, int] = {}
    for c in phase1:
        for ref in c.get("related_chunks", []):
            ref_freq[ref] = ref_freq.get(ref, 0) + 1
    related_ids = sorted(ref_freq, key=lambda x: -ref_freq[x])[:limits["Phase3"] * 3]
    phase3 = sorted(
        [all_by_id[rid] for rid in related_ids if rid in all_by_id],
        key=lambda c: -ref_freq.get(c["id"], 0)
    )[:limits["Phase3"]]

    phase4 = phase6 = phase7 = phase8 = []

    if quick_search:
        exclude_ids = {c["id"] for c in phase1 + phase3}
        query_chunks = [c for c in all_chunks
                        if any(t in c.get("tags", []) for t in ("experience", "skills", "technical", "procedures"))]
        phase6 = sorted(
            [c for c in query_chunks if c["id"] not in exclude_ids
             and any(t.lower() in c.get("_sl", "") for t in terms)],
            key=lambda c: -sum(1 for t in terms if t.lower() in c.get("_sl", ""))
        )[:limits["Phase6"]]
    else:
        deep_terms = list(dict.fromkeys(top_tags + discovered_keywords))
        exclude_ids = {c["id"] for c in phase1 + phase3}
        _deep_set = set(deep_terms)
        terms_lower_set = {t.lower() for t in terms}

        phase4 = sorted(
            [c for c in domain_chunks
             if c["id"] not in exclude_ids
             and any(t in c.get("_sl", "") for t in terms_lower_set | _deep_set)],
            key=lambda c: -sum(1 for t in c.get("tags", []) + c.get("search_keywords", []) if t in _deep_set)
        )[:limits.get("Phase4", 25)]

        exclude_ids |= {c["id"] for c in phase4}
        priority_tag_set = {"experience", "skills", "technical", "procedures", "achievements"}
        query_chunks = [c for c in all_chunks if priority_tag_set & set(c.get("tags", []))]
        all_terms_lower = [t.lower() for t in terms + deep_terms[:5]]
        phase6 = sorted(
            [c for c in query_chunks
             if c["id"] not in exclude_ids
             and any(t in c.get("_sl", "") for t in all_terms_lower)],
            key=lambda c: -sum(1 for t in all_terms_lower if t in c.get("_sl", ""))
        )[:limits["Phase6"]]

        if deep_search:
            long_terms = [t for t in terms if len(t) >= 5]
            exclude_ids |= {c["id"] for c in phase6}
            if long_terms:
                prefixes = [t[:5] for t in long_terms]
                phase7 = sorted(
                    [c for c in domain_chunks
                     if c["id"] not in exclude_ids
                     and sum(1 for p in prefixes if p in c.get("_sl", "")) >= 2],
                    key=lambda c: -sum(1 for p in prefixes if p in c.get("_sl", ""))
                )[:limits.get("Phase7", 20)]

            exclude_ids |= {c["id"] for c in phase7}
            entity_freq: dict[str, int] = {}
            for c in phase1:
                for k, v in (c.get("metadata", {}).get("nlp_entities") or {}).items():
                    vals = v if isinstance(v, list) else [v]
                    for val in vals:
                        entity_freq[f"{k}::{val}"] = entity_freq.get(f"{k}::{val}", 0) + 1
            top_entities = [e for e, _ in sorted(entity_freq.items(), key=lambda x: -x[1])][:10]
            if top_entities:
                phase8 = []
                for c in all_chunks:
                    if c["id"] in exclude_ids:
                        continue
                    entities = (c.get("metadata") or {}).get("nlp_entities") or {}
                    for key in top_entities:
                        etype, eval_val = key.split("::", 1)
                        vals = entities.get(etype, [])
                        if (isinstance(vals, list) and eval_val in vals) or vals == eval_val:
                            phase8.append(c)
                            break
                phase8 = phase8[:limits.get("Phase8", 70)]

    all_results = phase1 + phase3 + phase4 + phase6 + phase7 + phase8
    phase1_ids = {c["id"] for c in phase1}
    phase3_ids = {c["id"] for c in phase3}
    phase4_ids = {c["id"] for c in phase4}
    phase6_ids = {c["id"] for c in phase6}

    scored = []
    seen_ids: set[str] = set()
    for chunk in all_results:
        cid = chunk["id"]
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        if cid in phase1_ids:
            match_type = "Initial"
        elif cid in phase3_ids:
            match_type = "Related"
        elif cid in phase4_ids:
            match_type = "DeepDive"
        elif cid in phase6_ids:
            match_type = "Query"
        else:
            match_type = "Entity"

        result = dict(chunk)
        result["MatchType"] = match_type
        result["RelevanceScore"] = _score_chunk(chunk, terms, top_tags, discovered_keywords, match_type)
        scored.append(result)

    # Clean output
    strip_fields = {"search_text", "search_keywords", "related_chunks", "raw_markdown",
                    "topic_cluster_id", "cluster_size", "text_raw", "element_type", "_sl"}

    def _slim(chunk: dict) -> dict:
        return {k: v for k, v in chunk.items() if k not in strip_fields}

    final = sorted(scored, key=lambda c: (-c["RelevanceScore"], c["id"]))[:max_results]
    final = [_slim(c) for c in final]

    total_ranked = len(final)
    total_pages = max(1, -(-total_ranked // page_size))
    page = min(page, total_pages)
    offset = (page - 1) * page_size
    page_results = final[offset:offset + page_size]

    phase_counts = {}
    for c in page_results:
        mt = c["MatchType"]
        phase_counts[mt] = phase_counts.get(mt, 0) + 1

    duration_ms = round((time.monotonic() - t0) * 1000)
    log_event("search_kb", terms=terms, query=query, level=level,
              chunks_returned=len(page_results), duration_ms=duration_ms)

    return {
        "results": page_results,
        "total": total_ranked,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_more": page < total_pages,
        "level": level,
        "domains": active_domains,
        "phases": phase_counts,
        "top_tags": top_tags[:5],
        "discovered": discovered_keywords[:10],
    }

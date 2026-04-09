# -*- coding: utf-8 -*-
"""search_kb tool — Python port of Search-DomainAware.ps1."""
import re, json, logging, time, hashlib, copy, threading
from collections import OrderedDict
from pathlib import Path
from typing import Any
import asyncio, sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from logger import log_event

# Tag stoplist — NLP noise tags excluded from Phase 2 discovery and Phase 4 scoring.
# Loaded from config if defined, otherwise use the default set.
_TAG_STOPLIST: frozenset = frozenset(getattr(config, "TAG_STOPLIST", {
    "vpo", "post", "address", "report", "communications", "client",
    "lob", "functiona", "functiona-client", "clos", "issue", "spectrum",
    "action-provide", "action-select", "action-enter", "action-configure",
    "action-check", "action-verify", "action-review", "action-update",
    "select", "select-research", "your", "home", "experience", "usage",
    "task", "escalations-usage-task", "role", "mso", "pid",
}))

# Regex to detect actual query syntax in a chunk (SPL / DQL / Kibana).
# Requires trailing space on pipe commands and \w after index= to avoid
# matching markdown table pipes (| Status |) or bare index= in prose.
_QUERY_SYNTAX_RE = re.compile(
    r'index=\w|sourcetype=\w'
    r'|\| stats |\| eval |\| rex |\| dedup |\| timechart |\| transaction |\| spath '
    r'|\b\w+\.\w+\s*:[^/]'   # DQL dot-notation: word.word: value (exclude URLs)
    r'|OV-TUNE-FAIL|ov-tune-fail',
    re.I
)

# Mirrors $EXPANSION_LEVELS in Search-DomainAware.ps1
# Quick level is tuned to stay under Amazon Q's 100K char MCP output limit.
# Measured output sizes (3 representative queries, 15 chunks):
#   worst-case total = 66,609 chars (auth/entitlement, p90 chunk = 6,030)
#   best-case total  = 51,525 chars (tune/fail, p90 chunk = 3,988)
# At 20 chunks worst-case ≈ 66,609 + 5*6,030 = 96,759 chars — within limit.
# Page size is fixed at 20 chunks — safe at p90 worst-case (~72K chars per page).
# MaxPages is the recommended ceiling for Amazon Q to fetch per level.
_PAGE_SIZE = 20
_LEVEL_MAX_PAGES: dict[str, int] = {
    "Quick":      1,   # 1 page  = 20 chunks
    "Standard":   2,   # 2 pages = 40 chunks
    "Deep":       3,   # 3 pages = 60 chunks
    "Exhaustive": 4,   # 4 pages = 80 chunks
}

# Result cache for pagination — keyed by (terms, query, level, domains) fingerprint.
# Stores the full ranked list so all pages come from the same search run.
# LRU + optional TTL (config.SEARCH_RESULT_CACHE_TTL_SEC).
_RESULT_CACHE: OrderedDict[str, tuple[float, dict]] = OrderedDict()
_CACHE_MAX = 50  # max concurrent cached searches (one per active triage session)
_result_cache_lock = threading.Lock()
_RESULT_CACHE_TTL_SEC = float(getattr(config, "SEARCH_RESULT_CACHE_TTL_SEC", 300.0))

# Module-level chunk cache — keyed by frozenset of (path, mtime, size) tuples.
# Invalidated automatically when any category file changes (e.g. after a rebuild).
_CHUNK_CACHE: OrderedDict[str, tuple[list, list]] = OrderedDict()
_CHUNK_CACHE_MAX = 3
_chunk_cache_lock = threading.Lock()


def _chunk_cache_key(kb_dir: Path, domains: list[str]) -> str:
    detail = kb_dir / "detail"
    sig = []
    for f in sorted(detail.glob("chunks.*.jsonl")):
        if f.name == "chunks.jsonl":
            continue
        st = f.stat()
        sig.append(f"{f.name}:{st.st_mtime_ns}:{st.st_size}")
    sig.append("domains:" + ",".join(sorted(domains)))
    return hashlib.md5("|".join(sig).encode()).hexdigest()


def _get_cached_chunks(kb_dir: Path, domains: list[str]) -> tuple[list, list] | None:
    key = _chunk_cache_key(kb_dir, domains)
    with _chunk_cache_lock:
        if key not in _CHUNK_CACHE:
            return None
        _CHUNK_CACHE.move_to_end(key)
        return _CHUNK_CACHE[key]


def _set_cached_chunks(kb_dir: Path, domains: list[str],
                       domain_chunks: list, all_chunks: list) -> None:
    key = _chunk_cache_key(kb_dir, domains)
    with _chunk_cache_lock:
        _CHUNK_CACHE[key] = (domain_chunks, all_chunks)
        _CHUNK_CACHE.move_to_end(key)
        while len(_CHUNK_CACHE) > _CHUNK_CACHE_MAX:
            _CHUNK_CACHE.popitem(last=False)


def _cache_key(terms: list[str], query: str, level: str, domains: list[str]) -> str:
    raw = json.dumps([sorted(terms), query.lower().strip(), level, sorted(domains)],
                     ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode()).hexdigest()


_LEVELS: dict[str, dict[str, int]] = {
    "Quick":      {"Phase1": 12,  "Phase3": 5,                                           "Phase6": 3,   "Total": 20},
    "Standard":   {"Phase1": 45,  "Phase3": 55,  "Phase35": 15, "Phase4": 25,           "Phase6": 40,  "Total": 165},
    "Deep":       {"Phase1": 90,  "Phase3": 110, "Phase35": 30, "Phase4": 50,           "Phase6": 80,  "Phase7": 20, "Phase8": 70,  "Total": 420},
    "Exhaustive": {"Phase1": 180, "Phase3": 220, "Phase35": 60, "Phase4": 100,          "Phase6": 160, "Phase7": 40, "Phase8": 140, "Total": 840},
}

# Mirrors Get-DomainFromQuery
_DOMAIN_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("manual",    re.compile(r'\b(documentation|manual|guide|feature|specification|what is)\b', re.I)),
    ("reference", re.compile(r'\b(contact|team|escalate|who|phone|email|org|department)\b', re.I)),
    ("glossary",  re.compile(r'\b(what does|mean|definition|acronym|stands for)\b', re.I)),
]
_DEFAULT_DOMAINS = ["troubleshooting", "queries", "sop"]


def _get_domains_from_query(query: str) -> list[str]:
    domains = list(_DEFAULT_DOMAINS)
    for domain, pattern in _DOMAIN_PATTERNS:
        if pattern.search(query):
            domains.append(domain)
    return list(dict.fromkeys(domains))  # dedupe, preserve order


def _safe_load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file, skipping blank lines and logging any unparseable lines."""
    chunks: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            s = line.strip()
            if not s:
                continue
            try:
                c = json.loads(s)
                c["_sl"] = ((c.get("text") or "") + " " + (c.get("search_text") or "")[:500]).lower()
                chunks.append(c)
            except json.JSONDecodeError as e:
                logging.warning(f"search_kb: skipping bad line {i} in {path.name}: {e}")
    return chunks


def _load_all_category_chunks(kb_dir: Path) -> list[dict]:
    """Load all category JSONL files (used for cross-domain phases)."""
    chunks: list[dict] = []
    for f in sorted((kb_dir / "detail").glob("chunks.*.jsonl")):
        if f.name == "chunks.jsonl":
            continue
        chunks.extend(_safe_load_jsonl(f))
    return chunks


def _filter_domain_chunks(all_chunks: list[dict], domains: list[str]) -> tuple[list[dict], bool]:
    """Filter domain chunks from already-loaded all_chunks — avoids double I/O."""
    domain_set = set(domains)
    result = [c for c in all_chunks if domain_set & set(c.get("tags", []))]
    return result, bool(result)


def _text_of(chunk: dict) -> str:
    return chunk.get("_sl") or ((chunk.get("text") or "") + " " + (chunk.get("search_text") or "")).lower()


def _matches_terms(chunk: dict, terms: list[str], min_hits: int = 2) -> bool:
    combined = chunk.get("_sl") or _text_of(chunk)
    return sum(1 for t in terms if t.lower() in combined) >= min_hits


def _score_chunk(chunk: dict, terms: list[str], top_tags: list[str],
                 discovered_keywords: list[str], match_type: str) -> float:
    sl = chunk.get("_sl") or ((chunk.get("text") or "") + " " + (chunk.get("search_text") or "")).lower()
    term_score = sum(min(10, sl.count(t.lower()) * 2) for t in terms)
    score = min(40, term_score)

    if top_tags:
        score += min(20, sum(4 for tag in chunk.get("tags", [])
                             if tag in top_tags and tag not in _TAG_STOPLIST))
    if discovered_keywords and chunk.get("search_keywords"):
        score += min(15, sum(3 for kw in chunk.get("search_keywords", [])
                             if kw in discovered_keywords))
    # Smaller phase bonus so term frequency drives ranking, not just phase membership
    phase_bonus = {"Initial": 10, "Related": 7, "Learned": 8, "Query": 5, "DeepDive": 3}
    score += phase_bonus.get(match_type, 2)
    return round(score, 2)


async def run(
    terms: list[str],
    query: str = "",
    level: str = "Standard",
    domains: list[str] = [],
    max_results: int = 0,
    page: int = 1,
) -> dict:
    """Search the JSONL knowledge base across all phases.

    Args:
        terms: Search terms (required).
        query: Natural language query for domain auto-detection.
        level: Search depth — Quick | Standard | Deep | Exhaustive.
        domains: Explicit domain list; auto-detected from query if empty.
        max_results: Cap on returned chunks; 0 = level default.
        page: Page number (1-based). Each page returns up to 20 chunks (~72K chars).
              Fetch page=2,3,... until has_more=false or max_pages is reached.
              Standard=2 pages, Deep=3 pages, Exhaustive=4 pages recommended.
    """
    if not terms:
        return {"error": "terms is required"}

    t0 = time.monotonic()
    try:
        return await _run(terms, query, level, domains, max_results, page)
    except Exception as ex:
        duration_ms = round((time.monotonic() - t0) * 1000)
        log_event("tool_error", tool="search_kb", error_type=type(ex).__name__,
                  error=str(ex), terms=terms, level=level, duration_ms=duration_ms)
        logging.exception(f"search_kb unhandled error: {ex}")
        return {"error": str(ex)}


async def _run(
    terms: list[str],
    query: str = "",
    level: str = "Standard",
    domains: list[str] = [],
    max_results: int = 0,
    page: int = 1,
) -> dict:
    t0 = time.monotonic()
    limits = _LEVELS.get(level, _LEVELS["Standard"])
    page = max(1, int(page))
    page_size = _PAGE_SIZE
    if max_results == 0:
        max_results = limits["Total"]

    # ── Cache lookup: pages 2+ reuse the ranked list from page 1 ────────────
    ckey = _cache_key(terms, query, level, list(domains))
    cached = None
    with _result_cache_lock:
        if page > 1 and ckey in _RESULT_CACHE:
            ts, payload = _RESULT_CACHE[ckey]
            if _RESULT_CACHE_TTL_SEC <= 0 or (time.monotonic() - ts) <= _RESULT_CACHE_TTL_SEC:
                _RESULT_CACHE.move_to_end(ckey)
                cached = copy.deepcopy(payload)
            else:
                _RESULT_CACHE.pop(ckey, None)
    if cached is not None and page > 1:
        total_ranked = len(cached["final"])
        total_pages  = max(1, -(-total_ranked // page_size))
        max_pages    = _LEVEL_MAX_PAGES.get(level, 1)
        page         = min(page, total_pages)
        offset       = (page - 1) * page_size
        page_results = cached["final"][offset: offset + page_size]
        has_more     = page < total_pages and page < max_pages
        phase_counts: dict[str, int] = {}
        for c in page_results:
            mt = c["MatchType"]
            phase_counts[mt] = phase_counts.get(mt, 0) + 1
        duration_ms = round((time.monotonic() - t0) * 1000)
        log_event("search_kb",
                  terms=terms, query=query, level=level, domains=list(domains),
                  chunks_returned=len(page_results), phase_counts=phase_counts,
                  top_tags=cached["top_tags"], duration_ms=duration_ms,
                  page=page, total_pages=total_pages, cache_hit=True)
        return {
            "results":     page_results,
            "total":       total_ranked,
            "page":        page,
            "page_size":   page_size,
            "total_pages": total_pages,
            "max_pages":   max_pages,
            "has_more":    has_more,
            "level":       level,
            "domains":     list(domains),
            "phases":      phase_counts,
            "top_tags":    cached["top_tags"],
            "discovered":  cached["discovered"],
        }

    quick_search = level == "Quick"
    deep_search  = level in ("Deep", "Exhaustive")

    kb_dir = Path(config.JSON_KB_DIR)

    if not domains and query:
        domains = _get_domains_from_query(query)
        logging.info(f"search_kb: auto-detected domains: {domains}")

    _active_domains = domains or _DEFAULT_DOMAINS
    return await asyncio.to_thread(
        _search_sync, terms, query, level, _active_domains, max_results, page,
        ckey, page_size, limits, quick_search, deep_search, kb_dir, t0
    )


def _search_sync(
    terms: list[str], query: str, level: str, active_domains: list[str],
    max_results: int, page: int, ckey: str, page_size: int,
    limits: dict, quick_search: bool, deep_search: bool, kb_dir: Path, t0: float
) -> dict:
    """CPU-bound search body — runs in a thread pool to avoid blocking the event loop."""
    cached_chunks = _get_cached_chunks(kb_dir, active_domains)
    if cached_chunks:
        domain_chunks, all_chunks = cached_chunks
        logging.info(f"search_kb: chunk cache hit ({len(all_chunks)} chunks)")
    else:
        all_chunks = _load_all_category_chunks(kb_dir)
        domain_chunks, _ = _filter_domain_chunks(all_chunks, active_domains)
        if not domain_chunks:
            fallback = kb_dir / "detail" / "chunks.jsonl"
            if fallback.exists():
                all_chunks = _safe_load_jsonl(fallback)
                domain_chunks = all_chunks
                logging.warning("search_kb: using unified chunks.jsonl fallback")
        _set_cached_chunks(kb_dir, active_domains, domain_chunks, all_chunks)
        logging.info(f"search_kb: chunk cache miss — loaded {len(all_chunks)} chunks")
    all_by_id = {c["id"]: c for c in all_chunks}

    # ── PHASE 1: Initial domain search ───────────────────────────────────────
    phase1 = [c for c in domain_chunks if _matches_terms(c, terms, min_hits=2)]
    logging.info(f"Phase1 (Initial): {len(phase1)}")
    if not phase1:
        # Fallback: retry with min_hits=1 before giving up
        phase1 = [c for c in domain_chunks if _matches_terms(c, terms, min_hits=1)]
        logging.info(f"Phase1 fallback (min_hits=1): {len(phase1)}")
    if not phase1:
        return {"results": [], "total": 0, "level": level, "phases": {}}

    # ── PHASE 2: Discover tags / keywords / entities ──────────────────────────
    tag_freq: dict[str, int] = {}
    for c in phase1:
        for tag in c.get("tags", []):
            if tag not in _TAG_STOPLIST:
                tag_freq[tag] = tag_freq.get(tag, 0) + 1
    min_freq = max(2, int(len(phase1) * 0.2))
    top_tags = [t for t, n in sorted(tag_freq.items(), key=lambda x: -x[1])
                if n >= min_freq][:15]

    kw_freq: dict[str, int] = {}
    for c in phase1:
        for kw in c.get("search_keywords", []):
            if kw and len(kw) >= 3:
                kw_freq[kw] = kw_freq.get(kw, 0) + 1
    discovered_keywords = [k for k, n in sorted(kw_freq.items(), key=lambda x: -x[1])
                           if n >= 2][:20]

    entity_freq: dict[str, int] = {}
    for c in phase1:
        for k, v in (c.get("metadata", {}).get("nlp_entities") or {}).items():
            vals = v if isinstance(v, list) else [v]
            for val in vals:
                key = f"{k}::{val}"
                entity_freq[key] = entity_freq.get(key, 0) + 1
    top_entities = [e for e, _ in sorted(entity_freq.items(), key=lambda x: -x[1])][:10]

    # ── PHASE 3: Related chunks (cross-domain) ────────────────────────────────
    ref_freq: dict[str, int] = {}
    for c in phase1:
        for ref in c.get("related_chunks", []):
            ref_freq[ref] = ref_freq.get(ref, 0) + 1
    related_ids = sorted(ref_freq, key=lambda x: -ref_freq[x])[: limits["Phase3"] * 3]


    phase3 = sorted(
        [all_by_id[rid] for rid in related_ids if rid in all_by_id],
        key=lambda c: -ref_freq.get(c["id"], 0)
    )[: limits["Phase3"]]
    logging.info(f"Phase3 (Related): {len(phase3)}")

    # ── PHASE 3.5: Learned KB (Standard / Deep / Exhaustive only) ────────────
    phase35: list[dict] = []
    learned_cap = limits.get("Phase35", 0)
    if learned_cap:
        learned_file = kb_dir / "detail" / "chunks.learned.jsonl"
        if learned_file.exists():
            exclude_35 = {c["id"] for c in phase1 + phase3}
            learned_raw: list[dict] = []
            with open(learned_file, encoding="utf-8") as _lf:
                for _line in _lf:
                    if _line.strip():
                        try:
                            learned_raw.append(json.loads(_line))
                        except Exception:
                            pass
            phase35 = sorted(
                [c for c in learned_raw
                 if c["id"] not in exclude_35 and _matches_terms(c, terms, min_hits=1)],
                key=lambda c: -sum(1 for t in terms
                                   if t.lower() in (c.get("text") or "").lower())
            )[:learned_cap]
            logging.info(f"Phase3.5 (Learned): {len(phase35)}")

    if quick_search:
        # Quick: skip phases 4-8, only add queries/troubleshooting/sop
        exclude_ids = {c["id"] for c in phase1 + phase3}
        phase6_chunks = [c for c in all_chunks
                         if any(t in c.get("tags", []) for t in ("queries", "troubleshooting", "sop"))]
        def _phase6_score_quick(c: dict) -> int:
            sl = c["_sl"]
            term_hits = sum(1 for t in terms if t.lower() in sl)
            syntax_bonus = 3 if _QUERY_SYNTAX_RE.search(sl) else 0
            return term_hits + syntax_bonus
        phase6 = sorted(
            [c for c in phase6_chunks
             if c["id"] not in exclude_ids and
             any(t.lower() in c["_sl"] for t in terms)],
            key=lambda c: -_phase6_score_quick(c)
        )[: limits["Phase6"]]
        logging.info(f"Phase6 (Query/Quick): {len(phase6)}")
        all_results = phase1 + phase3 + phase35 + phase6
        phase4 = phase7 = phase8 = []
    else:
        # ── PHASE 4: Deep dive with discovered terms ──────────────────────────
        deep_terms = list(dict.fromkeys(top_tags + discovered_keywords))
        exclude_ids = {c["id"] for c in phase1} | {c["id"] for c in phase3}
        _deep_set = set(deep_terms)
        terms_lower_set = {t.lower() for t in terms}

        def _deep_hits(c: dict) -> int:
            tags = c.get("tags", []); kws = c.get("search_keywords", [])
            sl = c["_sl"]
            return sum(1 for t in _deep_set if t in tags or t in kws or t in sl)

        phase4 = sorted(
            [c for c in domain_chunks
             if c["id"] not in exclude_ids
             and any(t in c["_sl"] for t in terms_lower_set | _deep_set)
             and _deep_hits(c) >= 2],
            key=lambda c: -sum(1 for t in c.get("tags", []) + c.get("search_keywords", []) if t in _deep_set)
        )[: limits["Phase4"]]
        logging.info(f"Phase4 (DeepDive): {len(phase4)}")


        # ── PHASE 6: Queries/procedures (cross-domain) ────────────────────────
        all_terms = list(dict.fromkeys(terms + deep_terms))
        exclude_ids |= {c["id"] for c in phase4}
        _QUERY_TAG_SET = {"queries", "troubleshooting", "sop"}
        query_chunks = [c for c in all_chunks if _QUERY_TAG_SET & set(c.get("tags", []))]
        all_terms_lower = [t.lower() for t in all_terms]
        # Pre-filter: original terms + top 5 discovered keywords (ranked by corpus frequency).
        # Catches synonym-only matches without the cost of scanning all 20+ expanded terms.
        _p6_filter_terms = [t.lower() for t in terms] + [t.lower() for t in discovered_keywords[:5]]
        # Two-pass: cheap pre-filter, then full score on survivors
        def _phase6_score(c: dict) -> int:
            sl = c["_sl"]
            term_hits = sum(1 for t in all_terms_lower if t in sl)
            syntax_bonus = 3 if _QUERY_SYNTAX_RE.search(sl) else 0
            return term_hits + syntax_bonus
        phase6 = sorted(
            [c for c in query_chunks
             if c["id"] not in exclude_ids and
             any(t in c["_sl"] for t in _p6_filter_terms)],
            key=lambda c: -_phase6_score(c)
        )[: limits["Phase6"]]
        phase7 = phase8 = []

        if deep_search:
            # ── PHASE 7: Fuzzy matching ───────────────────────────────────────
            long_terms = [t for t in terms if len(t) >= 5]
            exclude_ids |= {c["id"] for c in phase6}
            if long_terms:
                prefixes = [t[:5] for t in long_terms]

                def _fuzzy_hits(c: dict) -> int:
                    sl = c["_sl"]
                    return sum(1 for p in prefixes if p in sl)

                phase7 = sorted(
                    [c for c in domain_chunks if c["id"] not in exclude_ids and _fuzzy_hits(c) >= 2],
                    key=lambda c: -_fuzzy_hits(c)
                )[: limits["Phase7"]]
            logging.info(f"Phase7 (Fuzzy): {len(phase7)}")

            # ── PHASE 8: Entity expansion (cross-domain) ──────────────────────
            exclude_ids |= {c["id"] for c in phase7}
            if top_entities:
                def _entity_match(c: dict) -> bool:
                    entities = (c.get("metadata") or {}).get("nlp_entities") or {}
                    for key in top_entities:
                        etype, eval = key.split("::", 1)
                        vals = entities.get(etype, [])
                        if isinstance(vals, list) and eval in vals:
                            return True
                        if vals == eval:
                            return True
                    return False

                seen: set[str] = set()
                phase8 = []
                for c in all_chunks:
                    if c["id"] not in exclude_ids and c["id"] not in seen and _entity_match(c):
                        phase8.append(c)
                        seen.add(c["id"])
                phase8 = phase8[: limits["Phase8"]]
            logging.info(f"Phase8 (Entity): {len(phase8)}")

        all_results = phase1 + phase3 + phase35 + phase4 + phase6 + phase7 + phase8

    # ── SCORE & LABEL ─────────────────────────────────────────────────────────
    phase1_ids  = {c["id"] for c in phase1}
    phase3_ids  = {c["id"] for c in phase3}
    phase35_ids = {c["id"] for c in phase35}
    phase4_ids  = {c["id"] for c in (phase4 if not quick_search else [])}
    phase6_ids  = {c["id"] for c in phase6}
    phase7_ids  = {c["id"] for c in (phase7 if deep_search and not quick_search else [])}

    scored: list[dict[str, Any]] = []
    _seen_ids: set[str] = set()
    for chunk in all_results:
        cid = chunk["id"]
        if cid in _seen_ids:
            continue  # deduplicate — same chunk can appear in multiple phases
        _seen_ids.add(cid)
        if   cid in phase1_ids:  match_type = "Initial"
        elif cid in phase3_ids:  match_type = "Related"
        elif cid in phase35_ids: match_type = "Learned"
        elif cid in phase4_ids:  match_type = "DeepDive"
        elif cid in phase6_ids:  match_type = "Query"
        elif cid in phase7_ids:  match_type = "Fuzzy"
        else:                    match_type = "Entity"

        result = dict(chunk)
        result["MatchType"]      = match_type
        result["RelevanceScore"] = _score_chunk(chunk, terms, top_tags, discovered_keywords, match_type)
        scored.append(result)

    _STRIP_FIELDS = {"search_text", "search_keywords", "related_chunks", "raw_markdown",
                     "topic_cluster_id", "cluster_size", "text_raw", "element_type", "_sl"}
    _STRIP_META   = {"key_phrases", "nlp_entities", "file_path",
                     "chapter_id", "page_start", "page_end", "topic", "nlp_category"}
    _TEXT_LIMIT   = 3800  # chars — p99 chunk ~6K; 20 chunks × 3800 ≈ 86K, safely under 100K limit

    def _slim(chunk: dict) -> dict:
        out = {k: v for k, v in chunk.items() if k not in _STRIP_FIELDS}
        if "text" in out and len(out["text"]) > _TEXT_LIMIT:
            out["text"] = out["text"][:_TEXT_LIMIT] + "…"
        if "metadata" in out:
            out["metadata"] = {k: v for k, v in out["metadata"].items() if k not in _STRIP_META}
            if not out["metadata"]:
                del out["metadata"]
        return out

    # Build one canonical ordered list: query floor first, then remaining by score.
    # All pages slice from this same list so there is never any overlap.
    _QUERY_FLOOR = 4
    query_chunks_scored  = [c for c in scored if c["id"] in phase6_ids]
    other_chunks_scored  = [c for c in scored if c["id"] not in phase6_ids]
    guaranteed     = sorted(query_chunks_scored, key=lambda c: (-c["RelevanceScore"], c["id"]))[:_QUERY_FLOOR]
    guaranteed_ids = {c["id"] for c in guaranteed}
    remaining      = sorted(
        [c for c in other_chunks_scored] +
        [c for c in query_chunks_scored if c["id"] not in guaranteed_ids],
        key=lambda c: (-c["RelevanceScore"], c["id"])
    )[:max(0, max_results - len(guaranteed))]
    final = [_slim(c) for c in guaranteed + remaining]

    # ── Cache store: save full ranked list for subsequent page calls ─────────
    payload = {
        "final":      final,
        "top_tags":   top_tags[:5],
        "discovered": discovered_keywords[:10],
    }
    with _result_cache_lock:
        if ckey in _RESULT_CACHE:
            _RESULT_CACHE.pop(ckey, None)
        _RESULT_CACHE[ckey] = (time.monotonic(), payload)
        _RESULT_CACHE.move_to_end(ckey)
        while len(_RESULT_CACHE) > _CACHE_MAX:
            _RESULT_CACHE.popitem(last=False)

    # ── Pagination ────────────────────────────────────────────────────────────
    # Slice the fully-ranked list into fixed-size pages.
    # Each page is page_size chunks — safe under the 100K MCP output limit at p90.
    total_ranked   = len(final)
    total_pages    = max(1, -(-total_ranked // page_size))  # ceiling division
    max_pages      = _LEVEL_MAX_PAGES.get(level, 1)
    page           = min(page, total_pages)  # clamp to valid range
    offset         = (page - 1) * page_size
    page_results   = final[offset: offset + page_size]
    has_more       = page < total_pages and page < max_pages

    phase_counts = {}
    for c in page_results:
        mt = c["MatchType"]
        phase_counts[mt] = phase_counts.get(mt, 0) + 1

    duration_ms = round((time.monotonic() - t0) * 1000)
    logging.info(
        f"search_kb complete: {len(page_results)} chunks (page {page}/{total_pages}) "
        f"| level={level} | phases={phase_counts}"
    )
    log_event("search_kb",
              terms=terms, query=query, level=level, domains=active_domains,
              chunks_returned=len(page_results), phase_counts=phase_counts,
              top_tags=top_tags[:5], duration_ms=duration_ms,
              page=page, total_pages=total_pages,
              result_cache_hit=False)

    result = {
        "results":      page_results,
        "total":        total_ranked,
        "page":         page,
        "page_size":    page_size,
        "total_pages":  total_pages,
        "max_pages":    max_pages,
        "has_more":     has_more,
        "level":        level,
        "domains":      active_domains,
        "phases":       phase_counts,
        "top_tags":     top_tags[:5],
        "discovered":   discovered_keywords[:10],
    }

    if len(page_results) == 0 and page == 1:
        log_event("search_kb_warning",
                  warning_type="no_results",
                  chunks_returned=0,
                  level=level, terms=terms, duration_ms=duration_ms)

    return result

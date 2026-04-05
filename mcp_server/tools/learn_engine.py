# -*- coding: utf-8 -*-
"""
learn_engine.py — shared engine for the learn tool (MCP and local).

Subclass LearnEngine and implement:
    - learned_file  (Path property)
    - detail_dir    (Path property)
    - _persist(chunk) -> dict   # write + commit/log
    - _extra_meta() -> dict     # source-specific metadata fields
"""
import hashlib, json, logging, re, sys, time
from abc import ABC, abstractmethod
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# -- NLP — loaded once at import time, shared by all subclasses ---------------
try:
    import spacy as _spacy
    _nlp = _spacy.load("en_core_web_md")
except Exception:
    _nlp = None
    logging.warning("learn_engine: spaCy unavailable — semantic dedup and NLP enrichment disabled")

try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent.parent.parent / "indexers"))
    from utils.nlp_classifier import classify_content_nlp as _classify
    _HAS_CLASSIFIER = True
except Exception:
    _HAS_CLASSIFIER = False
    logging.warning("learn_engine: nlp_classifier unavailable — category defaults to 'general'")

def _load_sanitizer():
    """Load sanitize_cpni via importlib to bypass package __init__.py requirements."""
    import importlib.util
    candidates = [
        Path(__file__).parent.parent.parent / "indexers" / "utils" / "cpni_sanitizer.py",
        Path(__file__).parent.parent / "indexers" / "utils" / "cpni_sanitizer.py",
    ]
    for p in candidates:
        try:
            if not p.exists():
                continue
            spec = importlib.util.spec_from_file_location("cpni_sanitizer", p)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.sanitize_cpni
        except Exception:
            continue
    return None

_sanitize_cpni = _load_sanitizer()
if _sanitize_cpni is None:
    _sanitize_cpni = lambda t: t
    logging.warning("learn_engine: cpni_sanitizer unavailable — CPNI redaction disabled")

# -- Similarity thresholds ----------------------------------------------------
# Single threshold: >= _SIM_DUPLICATE -> duplicate (rejected). Below -> new chunk saved.
# No merge window — below the threshold is always a new chunk.
#
# Tag overlap confirmation (_TAG_OVERLAP_MIN shared domain tags) is required for
# cross-ticket and static KB matches to prevent false positives from lexical overlap.
#
# Lexical ceiling (_SIM_CEILING): if similarity >= this AND chunks share zero domain
# tags, still reject — content is too similar to be substantive regardless of topic.
_SIM_DUPLICATE      = 0.92
_SIM_CEILING        = 0.98   # hard reject even with no shared domain tags above this score
_TAG_OVERLAP_MIN    = 2
_STATIC_KB_TIMEOUT  = 8.0    # wall-clock seconds budget for entire Pass 3
_KEYWORD_MIN_MATCH  = 3      # min keyword hits to admit a chunk to spaCy comparison
_KEYWORD_TOP_N      = 20     # top N significant words extracted from incoming text

# Common English + VPO noise words excluded from keyword pre-filter
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "is", "are", "was", "were", "be", "been", "has", "have",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "this", "that", "these", "those", "it", "its", "from", "by", "as", "if",
    "not", "no", "so", "then", "than", "also", "all", "any", "can", "when",
    "what", "which", "who", "how", "after", "before", "into", "out", "up",
    "about", "per", "via", "both", "each", "their", "they", "we", "our",
    "you", "your", "he", "she", "his", "her", "my", "me", "us", "them",
    "post", "pre", "new", "old", "get", "set", "run", "use", "see", "show",
    "check", "send", "add", "fix", "issue", "ticket", "step", "note",
}


def _keyword_set(text: str) -> set:
    """Extract top N significant lowercase words from text for pre-filter."""
    words = re.findall(r'[a-z][a-z0-9_]{2,}', text.lower())
    counts = Counter(w for w in words if w not in _STOPWORDS)
    return {w for w, _ in counts.most_common(_KEYWORD_TOP_N)}


def _keyword_match(kw_set: set, candidate: str) -> bool:
    """Return True if candidate text contains >= _KEYWORD_MIN_MATCH words from kw_set."""
    if not kw_set:
        return True  # no filter possible — admit all
    candidate_lower = candidate.lower()
    hits = sum(1 for w in kw_set if w in candidate_lower)
    return hits >= _KEYWORD_MIN_MATCH


def _domain_tags(chunk: dict) -> set:
    """Return tags that are CONTENT_TAGS keys (domain-specific)."""
    try:
        import sys as _s
        _s.path.insert(0, str(Path(__file__).parent.parent.parent / "indexers"))
        import config as _cfg
        domain_keys = set(_cfg.CONTENT_TAGS.keys())
        return {t for t in chunk.get("tags", []) if t in domain_keys}
    except Exception:
        return set(chunk.get("tags", []))


def _tag_overlap_check(sim: float, new_tags: set, existing_chunk: dict) -> bool:
    """
    Returns True (confirmed duplicate) if:
      - sim >= _SIM_CEILING (too similar regardless of tags), OR
      - sim >= _SIM_DUPLICATE AND existing chunk has domain tags AND shared >= _TAG_OVERLAP_MIN
    Returns False (not confirmed) otherwise.
    """
    if sim >= _SIM_CEILING:
        return True
    existing_domain_tags = _domain_tags(existing_chunk)
    if not existing_domain_tags:
        return False
    return len(new_tags & existing_domain_tags) >= _TAG_OVERLAP_MIN


# -- Pure functions ------------------------------------------------------------

def sha8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()[:8]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def gate1_quality(text: str) -> tuple[bool, str]:
    """Structural quality gate. Returns (passes, reason)."""
    words = text.split()
    if len(words) < 15:
        return False, f"too short ({len(words)} words, minimum 15)"
    if len(text) > 0 and sum(1 for c in text if ord(c) not in range(32, 127)) / len(text) > 0.15:
        return False, "excessive non-printable characters (likely garbled OCR or raw binary)"
    if Counter(w.lower() for w in words).most_common(1)[0][1] / len(words) > 0.5:
        return False, "single word dominates >50% of content"
    alpha = sum(1 for c in text if c.isalpha())
    if len(text) > 0 and alpha / len(text) < 0.35:
        return False, "insufficient interpretive content (ratio of letters too low — likely raw log dump)"
    return True, ""


def nlp_enrich(text: str, caller_tags: list[str], category: str) -> tuple[str, list[str], dict]:
    """Returns (resolved_category, merged_tags, nlp_metadata)."""
    nlp_meta: dict[str, Any] = {}
    tags = list(caller_tags)

    if _HAS_CLASSIFIER:
        try:
            result = _classify(text, auto_classify=True, auto_tag=True)
            nlp_meta = {
                "nlp_category": result["category"],
                "nlp_entities": result["entities"],
                "key_phrases":  result["key_phrases"],
            }
            if category == "auto":
                category = result["category"]
            nlp_tags = result.get("tags", [])
            merged   = ([category]
                        + [t for t in nlp_tags if t != category]
                        + [t for t in tags if t not in nlp_tags and t != category])
            tags = merged[:10]
        except Exception as e:
            logging.warning(f"learn_engine: NLP enrichment failed: {e}")
            if category == "auto":
                category = "general"
    else:
        if category == "auto":
            category = "general"
        tags = [category] + [t for t in tags if t != category]

    return category, tags, nlp_meta


def build_chunk(text: str, ticket_key: str, category: str,
                tags: list[str], nlp_meta: dict,
                user_id: str, title: str, extra_meta: dict) -> dict:
    """Construct a fully-formed chunk record."""
    ticket_part    = ticket_key.strip() or "general"
    chunk_id       = f"learned::{ticket_part}::{sha8(text)}"
    resolved_title = title.strip() or text[:60].replace("\n", " ")
    breadcrumb     = f"Learned | {ticket_part} | {category}"
    return {
        "id":           chunk_id,
        "text":         f"[{breadcrumb}]\n{text}",
        "text_raw":     text,
        "element_type": "learned",
        "metadata": {
            "doc_id":     "learned",
            "ticket_key": ticket_key.strip(),
            "user_id":    user_id,
            "session_ts": datetime.now(timezone.utc).isoformat(),
            "title":      resolved_title,
            **nlp_meta,
            **extra_meta,
        },
        "tags": tags,
    }


# -- Abstract engine ----------------------------------------------------------

class LearnEngine(ABC):
    """
    Abstract base for the learn tool.

    Subclasses provide:
      - learned_file  -> Path to chunks.learned.jsonl
      - detail_dir    -> Path to the detail/ directory (for static KB dedup)
      - _persist(chunk) -> dict   # write chunk and commit
      - _extra_meta() -> dict     # source-specific metadata fields
    """

    @property
    @abstractmethod
    def learned_file(self) -> Path: ...

    @property
    @abstractmethod
    def detail_dir(self) -> Path: ...

    @abstractmethod
    def _persist(self, chunk: dict) -> dict: ...

    @abstractmethod
    def _extra_meta(self) -> dict: ...

    # -- Shared pipeline ------------------------------------------------------

    def process(self, text: str, ticket_key: str = "", category: str = "auto",
                tags: list[str] = [], title: str = "",
                user_id: str = "unknown") -> dict:
        """Gate 1 -> Gate 2 (dedup scan) -> NLP -> build -> persist"""
        text = _sanitize_cpni(text)

        ok, reason = gate1_quality(text)
        if not ok:
            return {"status": "rejected", "gate": 1, "reason": reason}

        action, match_id, similarity = self._scan(text, ticket_key)
        if action == "duplicate":
            return {
                "status":            "duplicate",
                "existing_chunk_id": match_id,
                "similarity":        similarity,
                "message":           "This knowledge already exists in the KB. No chunk was saved.",
            }

        resolved_category, merged_tags, nlp_meta = nlp_enrich(text, list(tags), category)
        chunk = build_chunk(
            text, ticket_key, resolved_category, merged_tags,
            nlp_meta, user_id,
            title.strip() or text[:60].replace("\n", " "),
            self._extra_meta(),
        )
        result = self._persist(chunk)
        result.update({
            "status":             "ok",
            "chunk_id":           chunk["id"],
            "category":           resolved_category,
            "tags":               merged_tags,
            "title":              chunk["metadata"]["title"],
            "similarity_checked": round(similarity, 4),
        })
        return result

    # -- Internal helpers -----------------------------------------------------

    def _scan(self, text: str, ticket_key: str) -> tuple[str, str, float]:
        """
        3-pass dedup scan. Returns (action, chunk_id, similarity):
          "duplicate" -- >= 0.925 confirmed (tag overlap or ceiling required for cross-ticket/static)
          "new"       -- below threshold, always saved as a new chunk

        Lexical ceiling: >= 0.98 is always rejected regardless of tag overlap.
        Tag overlap: cross-ticket and static KB matches at 0.925-0.979 require
          >= 2 shared domain tags to confirm. No tag gate for same-ticket matches.
        """
        norm      = normalize(text)
        text_hash = sha8(norm)

        # Pass 1: exact hash match in learned file
        if self.learned_file.exists():
            with open(self.learned_file, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        if sha8(normalize(rec.get("text_raw") or rec.get("text", ""))) == text_hash:
                            return "duplicate", rec.get("id", ""), 1.0
                    except Exception:
                        pass

        if _nlp is None:
            return "new", "", 0.0

        doc_new = _nlp(text[:500])

        # Derive domain tags from incoming text for tag overlap checks
        new_tags: set = set()
        try:
            if _HAS_CLASSIFIER:
                _quick = _classify(text[:500], auto_classify=False, auto_tag=True)
                new_tags = _domain_tags({"tags": _quick.get("tags", [])})
        except Exception:
            pass

        # Pass 2: semantic scan of learned file
        ticket_part    = ticket_key.strip() or "general"
        best_sim       = 0.0
        best_cross_sim = 0.0
        best_cross_id  = ""
        best_cross_rec: dict = {}

        if self.learned_file.exists():
            with open(self.learned_file, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec        = json.loads(line)
                        rec_ticket = rec.get("metadata", {}).get("ticket_key", "") or "general"
                        candidate  = (rec.get("text_raw") or rec.get("text", ""))[:500]
                        if not candidate:
                            continue
                        sim = doc_new.similarity(_nlp(candidate))
                        best_sim = max(best_sim, sim)
                        if rec_ticket == ticket_part:
                            # Same-ticket: no tag gate needed
                            if sim >= _SIM_DUPLICATE:
                                return "duplicate", rec.get("id", ""), round(sim, 4)
                        else:
                            if sim > best_cross_sim:
                                best_cross_sim = sim
                                best_cross_id  = rec.get("id", "")
                                best_cross_rec = rec
                    except Exception:
                        pass

        # Cross-ticket: tag overlap gate + lexical ceiling
        if best_cross_sim >= _SIM_DUPLICATE:
            if _tag_overlap_check(best_cross_sim, new_tags, best_cross_rec):
                return "duplicate", best_cross_id, round(best_cross_sim, 4)
            logging.info(
                f"learn_engine: cross-ticket similarity {best_cross_sim:.3f} to "
                f"{best_cross_id} not confirmed (tag overlap insufficient)"
            )

        # Pass 3: semantic scan of static KB
        # Two-stage: keyword pre-filter (fast) → spaCy similarity (only on matches)
        # This bounds expensive NLP calls to chunks that share significant vocabulary
        # with the incoming text, preserving dedup quality without scanning all chunks.
        kw_set          = _keyword_set(text)
        best_static_sim = 0.0
        best_static_id  = ""
        best_static_rec: dict = {}
        t3_start = time.monotonic()
        for cat in ("troubleshooting", "queries", "sop", "general", "manual"):
            if time.monotonic() - t3_start >= _STATIC_KB_TIMEOUT:
                logging.info("learn_engine: Pass 3 time budget exhausted — skipping remaining categories")
                break
            cat_file = self.detail_dir / f"chunks.{cat}.jsonl"
            if not cat_file.exists():
                continue
            with open(cat_file, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    if time.monotonic() - t3_start >= _STATIC_KB_TIMEOUT:
                        break
                    try:
                        rec       = json.loads(line)
                        candidate = (rec.get("search_text") or rec.get("text_raw") or rec.get("text", ""))[:500]
                        if not candidate:
                            continue
                        # Stage 1: keyword pre-filter — skip spaCy if no vocabulary overlap
                        if not _keyword_match(kw_set, candidate):
                            continue
                        # Stage 2: spaCy similarity on keyword-matched candidates only
                        sim = doc_new.similarity(_nlp(candidate[:500]))
                        if sim > best_static_sim:
                            best_static_sim = sim
                            best_static_id  = rec.get("id", "")
                            best_static_rec = rec
                        if best_static_sim >= _SIM_CEILING:
                            break
                    except Exception:
                        pass
            if best_static_sim >= _SIM_CEILING:
                break

        if best_static_sim >= _SIM_DUPLICATE:
            if _tag_overlap_check(best_static_sim, new_tags, best_static_rec):
                return "duplicate", best_static_id, round(best_static_sim, 4)
            logging.info(
                f"learn_engine: static KB similarity {best_static_sim:.3f} to "
                f"{best_static_id} not confirmed (tag overlap insufficient)"
            )

        return "new", "", round(max(best_sim, best_static_sim, best_cross_sim), 4)

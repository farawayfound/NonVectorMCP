# -*- coding: utf-8 -*-
"""ChunkyPotato learn engine — quality-gated, dedup-checked knowledge ingestion."""
import hashlib
import json
import logging
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import get_settings
from backend.indexers.utils.pii_sanitizer import sanitize_pii

# -- NLP — loaded once at import time -----------------------------------------
try:
    import spacy as _spacy
    _nlp = _spacy.load("en_core_web_md")
except Exception:
    _nlp = None
    logging.warning("learn_engine: spaCy unavailable — semantic dedup disabled")

try:
    from backend.indexers.utils.nlp_classifier import classify_content_nlp as _classify
    _HAS_CLASSIFIER = True
except Exception:
    _HAS_CLASSIFIER = False
    logging.warning("learn_engine: nlp_classifier unavailable — category defaults to 'general'")

# -- Similarity thresholds ----------------------------------------------------
_SIM_DUPLICATE = 0.92
_SIM_CEILING = 0.98
_TAG_OVERLAP_MIN = 2
_STATIC_KB_TIMEOUT = 8.0
_KEYWORD_MIN_MATCH = 3
_KEYWORD_TOP_N = 20

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
    "check", "send", "add", "fix", "issue", "step", "note",
}


def _sha8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()[:8]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _keyword_set(text: str) -> set:
    words = re.findall(r'[a-z][a-z0-9_]{2,}', text.lower())
    counts = Counter(w for w in words if w not in _STOPWORDS)
    return {w for w, _ in counts.most_common(_KEYWORD_TOP_N)}


def _keyword_match(kw_set: set, candidate: str) -> bool:
    if not kw_set:
        return True
    hits = sum(1 for w in kw_set if w in candidate.lower())
    return hits >= _KEYWORD_MIN_MATCH


def _domain_tags(chunk: dict) -> set:
    content_tags = get_settings().CONTENT_TAGS
    if content_tags:
        domain_keys = set(content_tags.keys())
        return {t for t in chunk.get("tags", []) if t in domain_keys}
    return set(chunk.get("tags", []))


def _tag_overlap_check(sim: float, new_tags: set, existing_chunk: dict) -> bool:
    if sim >= _SIM_CEILING:
        return True
    existing_domain_tags = _domain_tags(existing_chunk)
    if not existing_domain_tags:
        return False
    return len(new_tags & existing_domain_tags) >= _TAG_OVERLAP_MIN


# -- Quality gate --------------------------------------------------------------

def gate_quality(text: str) -> tuple[bool, str]:
    """Structural quality gate. Returns (passes, reason)."""
    words = text.split()
    if len(words) < 15:
        return False, f"too short ({len(words)} words, minimum 15)"
    if len(text) > 0 and sum(1 for c in text if ord(c) not in range(32, 127)) / len(text) > 0.15:
        return False, "excessive non-printable characters"
    if Counter(w.lower() for w in words).most_common(1)[0][1] / len(words) > 0.5:
        return False, "single word dominates >50% of content"
    alpha = sum(1 for c in text if c.isalpha())
    if len(text) > 0 and alpha / len(text) < 0.35:
        return False, "insufficient interpretive content"
    return True, ""


# -- NLP enrichment ------------------------------------------------------------

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
                "key_phrases": result["key_phrases"],
            }
            if category == "auto":
                category = result["category"]
            nlp_tags = result.get("tags", [])
            merged = ([category]
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


def build_chunk(text: str, topic_key: str, category: str,
                tags: list[str], nlp_meta: dict,
                user_id: str, title: str) -> dict:
    """Construct a fully-formed learned chunk record."""
    topic_part = topic_key.strip() or "general"
    chunk_id = f"learned::{topic_part}::{_sha8(text)}"
    resolved_title = title.strip() or text[:60].replace("\n", " ")
    breadcrumb = f"Learned | {topic_part} | {category}"
    return {
        "id": chunk_id,
        "text": f"[{breadcrumb}]\n{text}",
        "text_raw": text,
        "element_type": "learned",
        "metadata": {
            "doc_id": "learned",
            "topic_key": topic_part,
            "user_id": user_id,
            "session_ts": datetime.now(timezone.utc).isoformat(),
            "title": resolved_title,
            **nlp_meta,
        },
        "tags": tags,
    }


# -- Learn engine --------------------------------------------------------------

class LearnEngine:
    """Per-user learn engine with quality gating and dedup scanning."""

    def __init__(self, index_dir: Path):
        self.index_dir = Path(index_dir)
        self.detail_dir = self.index_dir / "detail"
        self.learned_file = self.detail_dir / "chunks.learned.jsonl"
        self.detail_dir.mkdir(parents=True, exist_ok=True)

    def process(self, text: str, topic_key: str = "", category: str = "auto",
                tags: list[str] | None = None, title: str = "",
                user_id: str = "unknown") -> dict:
        """Gate 1 (quality) -> Gate 2 (dedup scan) -> NLP -> build -> persist."""
        tags = tags or []
        text = sanitize_pii(text)

        ok, reason = gate_quality(text)
        if not ok:
            return {"status": "rejected", "gate": 1, "reason": reason}

        action, match_id, similarity = self._scan(text, topic_key)
        if action == "duplicate":
            return {
                "status": "duplicate",
                "existing_chunk_id": match_id,
                "similarity": similarity,
                "message": "This knowledge already exists in the KB. No chunk was saved.",
            }

        resolved_category, merged_tags, nlp_meta = nlp_enrich(text, list(tags), category)
        chunk = build_chunk(
            text, topic_key, resolved_category, merged_tags,
            nlp_meta, user_id,
            title.strip() or text[:60].replace("\n", " "),
        )
        self._persist(chunk)
        return {
            "status": "ok",
            "chunk_id": chunk["id"],
            "category": resolved_category,
            "tags": merged_tags,
            "title": chunk["metadata"]["title"],
            "similarity_checked": round(similarity, 4),
        }

    def _persist(self, chunk: dict):
        """Append chunk to learned JSONL file."""
        with open(self.learned_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        logging.info(f"learn_engine: persisted {chunk['id']}")

    def _scan(self, text: str, topic_key: str) -> tuple[str, str, float]:
        """3-pass dedup scan. Returns (action, chunk_id, similarity)."""
        norm = _normalize(text)
        text_hash = _sha8(norm)

        # Pass 1: exact hash match in learned file
        if self.learned_file.exists():
            with open(self.learned_file, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        if _sha8(_normalize(rec.get("text_raw") or rec.get("text", ""))) == text_hash:
                            return "duplicate", rec.get("id", ""), 1.0
                    except Exception:
                        pass

        if _nlp is None:
            return "new", "", 0.0

        doc_new = _nlp(text[:500])

        # Derive domain tags from incoming text for tag overlap checks
        new_tags: set = set()
        if _HAS_CLASSIFIER:
            try:
                _quick = _classify(text[:500], auto_classify=False, auto_tag=True)
                new_tags = _domain_tags({"tags": _quick.get("tags", [])})
            except Exception:
                pass

        # Pass 2: semantic scan of learned file
        topic_part = topic_key.strip() or "general"
        best_sim = 0.0
        best_cross_sim = 0.0
        best_cross_id = ""
        best_cross_rec: dict = {}

        if self.learned_file.exists():
            with open(self.learned_file, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        rec = json.loads(line)
                        rec_topic = rec.get("metadata", {}).get("topic_key", "") or "general"
                        candidate = (rec.get("text_raw") or rec.get("text", ""))[:500]
                        if not candidate:
                            continue
                        sim = doc_new.similarity(_nlp(candidate))
                        best_sim = max(best_sim, sim)
                        if rec_topic == topic_part:
                            if sim >= _SIM_DUPLICATE:
                                return "duplicate", rec.get("id", ""), round(sim, 4)
                        else:
                            if sim > best_cross_sim:
                                best_cross_sim = sim
                                best_cross_id = rec.get("id", "")
                                best_cross_rec = rec
                    except Exception:
                        pass

        # Cross-topic: tag overlap gate + lexical ceiling
        if best_cross_sim >= _SIM_DUPLICATE:
            if _tag_overlap_check(best_cross_sim, new_tags, best_cross_rec):
                return "duplicate", best_cross_id, round(best_cross_sim, 4)

        # Pass 3: semantic scan of static KB (time-bounded)
        kw_set = _keyword_set(text)
        best_static_sim = 0.0
        best_static_id = ""
        best_static_rec: dict = {}
        t3_start = time.monotonic()

        for cat in ("troubleshooting", "queries", "sop", "general", "manual"):
            if time.monotonic() - t3_start >= _STATIC_KB_TIMEOUT:
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
                        rec = json.loads(line)
                        candidate = (rec.get("search_text") or rec.get("text_raw") or rec.get("text", ""))[:500]
                        if not candidate:
                            continue
                        if not _keyword_match(kw_set, candidate):
                            continue
                        sim = doc_new.similarity(_nlp(candidate[:500]))
                        if sim > best_static_sim:
                            best_static_sim = sim
                            best_static_id = rec.get("id", "")
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

        return "new", "", round(max(best_sim, best_static_sim, best_cross_sim), 4)

    def get_learned_count(self) -> int:
        """Return count of learned chunks."""
        if not self.learned_file.exists():
            return 0
        count = 0
        with open(self.learned_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count

    def list_learned(self, limit: int = 50) -> list[dict]:
        """Return recent learned chunks (newest first)."""
        if not self.learned_file.exists():
            return []
        chunks = []
        with open(self.learned_file, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    chunks.append(json.loads(line))
                except Exception:
                    pass
        chunks.sort(key=lambda c: c.get("metadata", {}).get("session_ts", ""), reverse=True)
        return chunks[:limit]

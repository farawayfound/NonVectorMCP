# -*- coding: utf-8 -*-
"""Per-document insights built from the user's indexed chunks.

Surfaces what the indexer already knows (entities, key phrases, categories,
cross-refs, PII redaction counts) plus a one-shot Ollama-generated summary.
Cached at `{user_index_dir}/insights/{doc_id}.json` and regenerated whenever
`build_index` finishes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from backend.storage import get_user_index_dir

_PII_MARKERS = (
    "<EMAIL>", "<PHONE>", "<CREDENTIAL>", "<ACCOUNT_NUMBER>",
    "<ADDRESS>", "<PERSON_NAME>",
)

_SUMMARY_SYSTEM = (
    "You summarize documents for a knowledge base. Write 3 to 5 short sentences "
    "capturing what the document is about, its most important facts, and who or "
    "what it concerns. Plain prose, no headings, no bullets, no preamble."
)


def _iter_chunks(detail_dir: Path) -> Iterable[dict]:
    unified = detail_dir / "chunks.jsonl"
    if unified.exists():
        with open(unified, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
        return
    for f in detail_dir.glob("chunks.*.jsonl"):
        if f.name == "chunks.jsonl":
            continue
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def list_doc_ids(user_id: str) -> list[str]:
    """Return the set of distinct doc_ids present in the user's index."""
    detail_dir = get_user_index_dir(user_id) / "detail"
    if not detail_dir.exists():
        return []
    seen: set[str] = set()
    for chunk in _iter_chunks(detail_dir):
        doc_id = chunk.get("metadata", {}).get("doc_id")
        if doc_id:
            seen.add(doc_id)
    return sorted(seen)


def _count_pii(text: str, counts: Counter) -> None:
    if not text:
        return
    for marker in _PII_MARKERS:
        if marker in text:
            counts[marker.strip("<>")] += text.count(marker)


def _aggregate(user_id: str, doc_id: str) -> dict[str, Any]:
    """Single-pass aggregation of chunk metadata for one doc_id."""
    detail_dir = get_user_index_dir(user_id) / "detail"
    entities: Counter[str] = Counter()
    key_phrases: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    pii: Counter[str] = Counter()
    chunk_count = 0
    word_count = 0
    pages: set[int] = set()
    first_chunks: list[str] = []  # for summary context

    for chunk in _iter_chunks(detail_dir):
        meta = chunk.get("metadata") or {}
        if meta.get("doc_id") != doc_id:
            continue
        chunk_count += 1
        category = meta.get("nlp_category") or "general"
        categories[category] += 1

        for t in chunk.get("tags") or []:
            if isinstance(t, str):
                tags[t] += 1

        ents = meta.get("nlp_entities") or []
        for ent in ents:
            # entities may be {"text": ..., "label": ...} or plain strings
            if isinstance(ent, dict):
                label = ent.get("text") or ent.get("value")
                kind = ent.get("label") or ent.get("type") or ""
            else:
                label, kind = str(ent), ""
            if label and len(label) > 1:
                entities[f"{label}|{kind}"] += 1

        for kp in meta.get("key_phrases") or []:
            if isinstance(kp, str) and len(kp) > 1:
                key_phrases[kp.lower()] += 1

        text = chunk.get("text_raw") or chunk.get("text") or ""
        word_count += len(text.split())
        _count_pii(text, pii)

        for key in ("page_start", "page_end"):
            p = meta.get(key)
            if isinstance(p, int) and p > 0:
                pages.add(p)

        if len(first_chunks) < 6 and text:
            first_chunks.append(text[:800])

    if chunk_count == 0:
        return {"doc_id": doc_id, "empty": True}

    top_entities = []
    for key, count in entities.most_common(15):
        label, _, kind = key.partition("|")
        top_entities.append({"label": label, "kind": kind, "count": count})

    return {
        "doc_id": doc_id,
        "chunk_count": chunk_count,
        "word_count": word_count,
        "page_count": len(pages) or None,
        "reading_time_min": max(1, round(word_count / 220)) if word_count else 0,
        "categories": dict(categories.most_common()),
        "top_entities": top_entities,
        "top_key_phrases": [
            {"phrase": p, "count": c} for p, c in key_phrases.most_common(20)
        ],
        "top_tags": [{"tag": t, "count": c} for t, c in tags.most_common(15)],
        "pii_counts": dict(pii),
        "_summary_context": "\n\n".join(first_chunks),
    }


async def _generate_summary(context: str, doc_id: str) -> str:
    """Ask Ollama for a short neutral summary. Returns '' on failure."""
    if not context.strip():
        return ""
    try:
        from backend.chat.ollama_client import generate
        prompt = (
            f"Document: {doc_id}\n\n"
            f"Excerpts from the document:\n---\n{context[:6000]}\n---\n\n"
            "Summary:"
        )
        text = await generate(
            prompt=prompt,
            system=_SUMMARY_SYSTEM,
            temperature=0.2,
            max_tokens=400,
        )
        return (text or "").strip()
    except Exception as exc:
        logging.warning("insights: summary generation failed for %s: %s", doc_id, exc)
        return ""


def _insights_path(user_id: str, doc_id: str) -> Path:
    index_dir = get_user_index_dir(user_id)
    insights_dir = index_dir / "insights"
    insights_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", doc_id)
    return insights_dir / f"{safe}.json"


def load_cached_insights(user_id: str, doc_id: str) -> dict | None:
    path = _insights_path(user_id, doc_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


async def build_insights(user_id: str, doc_id: str, *, force: bool = False) -> dict:
    """Build or refresh insights for a single doc. Caches result on disk."""
    if not force:
        cached = load_cached_insights(user_id, doc_id)
        if cached and not cached.get("empty"):
            return cached

    agg = _aggregate(user_id, doc_id)
    if agg.get("empty"):
        return agg

    context = agg.pop("_summary_context", "")
    summary = await _generate_summary(context, doc_id)
    agg["summary"] = summary

    path = _insights_path(user_id, doc_id)
    path.write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
    return agg


async def build_all_insights(user_id: str) -> dict[str, Any]:
    """Build insights for every doc in the user's index. Best-effort."""
    results: dict[str, Any] = {}
    for doc_id in list_doc_ids(user_id):
        try:
            results[doc_id] = await build_insights(user_id, doc_id, force=True)
        except Exception as exc:
            logging.exception("insights: failed for %s / %s", user_id, doc_id)
            results[doc_id] = {"doc_id": doc_id, "error": str(exc)}
    return results


def build_all_insights_sync(user_id: str) -> dict[str, Any]:
    """Sync wrapper for background threads that lack an event loop."""
    try:
        return asyncio.run(build_all_insights(user_id))
    except RuntimeError:
        # Already inside an event loop — schedule and wait.
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(build_all_insights(user_id))
        finally:
            loop.close()

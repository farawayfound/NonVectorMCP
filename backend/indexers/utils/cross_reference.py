# -*- coding: utf-8 -*-
"""Cross-reference builder for chunk linking via spaCy word vectors."""
import logging
from typing import List, Dict, Set
from collections import defaultdict, Counter
import numpy as np

try:
    import spacy
    nlp = spacy.load("en_core_web_md")
except Exception:
    nlp = None
    logging.warning("spaCy model not loaded — cross-reference similarity disabled")

_doc_cache: dict = {}
_DOC_CACHE_MAX = 10000


def clear_doc_cache():
    _doc_cache.clear()


def auto_generate_aliases(all_chunks: List[Dict], min_freq: int = 10) -> Dict[str, List[str]]:
    if not nlp:
        return {}
    term_contexts = defaultdict(set)
    for chunk in all_chunks:
        tags = chunk.get("tags", [])
        entities = chunk.get("metadata", {}).get("nlp_entities", {})
        all_terms = set(tags)
        for ent_list in entities.values():
            all_terms.update([e.lower() for e in ent_list])
        for term in all_terms:
            term_contexts[term].update(all_terms - {term})

    aliases = {}
    term_freq = Counter([t for chunk in all_chunks for t in chunk.get("tags", [])])
    for term, freq in term_freq.most_common(20):
        if freq >= min_freq:
            term_doc = nlp(term)
            similar = []
            for other_term in term_contexts[term]:
                if other_term in term_freq and term_freq[other_term] >= min_freq:
                    other_doc = nlp(other_term)
                    if term_doc.vector_norm and other_doc.vector_norm and term_doc.similarity(other_doc) > 0.75:
                        similar.append(other_term)
            if similar:
                aliases[term] = [term] + similar[:3]
    return aliases


def get_term_aliases() -> Dict[str, List[str]]:
    from backend.config import get_settings
    return get_settings().TERM_ALIASES


def expand_terms(tags: List[str], term_aliases: Dict[str, List[str]]) -> Set[str]:
    expanded = set(tags)
    for tag in tags:
        tag_lower = tag.lower()
        for base, aliases in term_aliases.items():
            if tag_lower in [a.lower() for a in aliases]:
                expanded.update(aliases)
    return expanded


def build_search_text(chunk: Dict) -> str:
    parts = [
        chunk.get("metadata", {}).get("breadcrumb", ""),
        " ".join(chunk.get("tags", [])),
        " ".join(chunk.get("metadata", {}).get("key_phrases", []))
    ]
    entities = chunk.get("metadata", {}).get("nlp_entities", {})
    for ent_list in entities.values():
        parts.extend(ent_list)
    return " ".join(p for p in parts if p).lower()


def _get_vector(chunk_id: str, text: str):
    if chunk_id not in _doc_cache:
        if not text:
            return None
        if len(_doc_cache) >= _DOC_CACHE_MAX:
            evict = list(_doc_cache.keys())[:_DOC_CACHE_MAX // 2]
            for k in evict:
                del _doc_cache[k]
        _doc_cache[chunk_id] = nlp(text[:500]).vector
    return _doc_cache[chunk_id]


def compute_similarity(chunk1: Dict, chunk2: Dict) -> float:
    if not nlp:
        return 0.0
    v1 = _get_vector(chunk1.get("id"), chunk1.get("text_raw", chunk1.get("text", "")))
    v2 = _get_vector(chunk2.get("id"), chunk2.get("text_raw", chunk2.get("text", "")))
    if v1 is None or v2 is None:
        return 0.0
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))


def find_related_chunks(target_chunk: Dict, all_chunks: List[Dict],
                        max_related: int = 5, min_similarity: float = 0.7) -> List[str]:
    if not nlp:
        return []
    target_id = target_chunk.get("id")
    target_doc_id = target_chunk.get("metadata", {}).get("doc_id")
    target_tags = set(target_chunk.get("tags", []))
    candidates = []
    for chunk in all_chunks:
        chunk_id = chunk.get("id")
        chunk_doc_id = chunk.get("metadata", {}).get("doc_id")
        if chunk_id == target_id or chunk_doc_id == target_doc_id:
            continue
        chunk_tags = set(chunk.get("tags", []))
        if len(target_tags & chunk_tags) >= 3:
            sim = compute_similarity(target_chunk, chunk)
            if sim >= min_similarity:
                candidates.append((chunk_id, sim))
    candidates.sort(key=lambda x: x[1], reverse=True)
    return [cid for cid, _ in candidates[:max_related]]


def build_topic_clusters(all_chunks: List[Dict]) -> Dict[str, List[str]]:
    clusters = defaultdict(list)
    for chunk in all_chunks:
        tags = chunk.get("tags", [])
        if len(tags) >= 2:
            cluster_key = "+".join(sorted(tags[:3]))
            clusters[cluster_key].append(chunk.get("id"))
    return dict(clusters)


def enrich_chunk_with_cross_refs(chunk: Dict, all_chunks: List[Dict],
                                 clusters: Dict[str, List[str]],
                                 term_aliases: Dict[str, List[str]],
                                 max_related: int = 5,
                                 min_similarity: float = 0.7) -> Dict:
    expanded = expand_terms(chunk.get("tags", []), term_aliases)
    chunk["search_keywords"] = list(expanded)
    chunk["search_text"] = build_search_text(chunk)
    related = find_related_chunks(chunk, all_chunks, max_related, min_similarity)
    chunk["related_chunks"] = related
    chunk_id = chunk.get("id")
    for cluster_key, members in clusters.items():
        if chunk_id in members:
            chunk["topic_cluster_id"] = cluster_key
            chunk["cluster_size"] = len(members)
            break
    return chunk

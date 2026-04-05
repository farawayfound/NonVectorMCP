# -*- coding: utf-8 -*-
"""
Text processing utilities for VPO RAG
"""

import re, hashlib, sys
from pathlib import Path
from typing import List, Tuple, Dict, Any

# Add indexers directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

try:
    from utils.cpni_sanitizer import sanitize_cpni as _sanitize_cpni
except ImportError:
    try:
        from cpni_sanitizer import sanitize_cpni as _sanitize_cpni
    except ImportError:
        _sanitize_cpni = lambda t: t

def sha8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()[:8]

def rough_token_len(text: str) -> int:
    return max(1, len(text) // 4)

def split_with_overlap(words: List[str], target_tokens: int, overlap_tokens: int) -> List[str]:
    out = []; i = 0
    while i < len(words):
        j = min(len(words), i + target_tokens)
        out.append(" ".join(words[i:j]).strip())
        if j >= len(words): break
        i = max(j - overlap_tokens, i + 1)
    return out

def should_deduplicate(text: str, seen_hashes: dict, intensity: int) -> bool:
    """Check if chunk should be deduplicated based on intensity setting"""
    if intensity == 0:
        return False
    text_hash = sha8(text)
    if intensity == 1:
        if text_hash in seen_hashes:
            return True
        seen_hashes[text_hash] = text[:1000]
        return False
    try:
        from rapidfuzz import fuzz
        threshold = 100 - (intensity - 1) * 3
        text_sample = text[:1000]
        for existing_sample in seen_hashes.values():
            if fuzz.token_set_ratio(text_sample, existing_sample) >= threshold:
                return True
        seen_hashes[text_hash] = text_sample
        return False
    except Exception:
        if text_hash in seen_hashes:
            return True
        seen_hashes[text_hash] = text[:1000]
        return False

def sanitize_for_json(s: str) -> str:
    """Remove control characters that break JSON serialization"""
    if not s:
        return ""
    s = re.sub(r'[\x00-\x1F\x7F]', ' ', s)
    s = re.sub(r' +', ' ', s)
    return s.strip()

def normalize_text(s: str) -> str:
    # Remove soft hyphens and ligatures
    s = s.replace("\u00ad", "")
    s = s.replace("\ufb01", "fi").replace("\ufb02", "fl")
    
    # Preserve code blocks and queries - don't join hyphenated lines
    # Only join lines if they're clearly prose (not code/queries)
    out = []
    for line in s.splitlines():
        line = line.rstrip()
        # Don't join lines that look like code/queries
        if any(marker in line for marker in ['index=', 'sourcetype=', '|', 'SELECT', 'WHERE', '{', '}']):
            out.append(line + "\n")
        elif line.endswith("-") and not line.endswith("--"):
            # Only join hyphenated words in prose
            out.append(line[:-1])
        else:
            out.append(line + " ")
    
    s = "".join(out)
    # Collapse multiple spaces but preserve single newlines in code blocks
    s = re.sub(r" +", " ", s)  # Multiple spaces to single
    s = re.sub(r"\n{3,}", "\n\n", s)  # Multiple newlines to double
    s = s.strip()
    s = _sanitize_cpni(s)
    return sanitize_for_json(s)

def get_pdf_outline(doc: "fitz.Document") -> List[Tuple[int, str, int]]:
    try:
        toc = doc.get_toc(simple=True)
    except Exception:
        toc = []
    out = []
    for item in toc:
        if len(item) >= 3:
            level, title, page_no = item[0], normalize_text(item[1]), int(item[2]) - 1
            out.append((level, title, page_no))
    return out

def build_hierarchy(doc: "fitz.Document", max_depth: int = 6) -> List[Dict[str, Any]]:
    toc = get_pdf_outline(doc)
    if not toc:
        step = max(10, max(1, doc.page_count // 15))
        out = []
        for i in range(0, doc.page_count, step):
            out.append({"level": 1, "title": f"Section {i+1}-{min(i+step, doc.page_count)}", "page": i})
        return out
    out = [{"level": lvl, "title": title, "page": pg} for (lvl, title, pg) in toc if lvl <= max_depth]
    out.sort(key=lambda x: x["page"])
    return out

def build_breadcrumb_path(hierarchy: List[Dict[str, Any]], current_idx: int) -> str:
    path = []
    current = hierarchy[current_idx]
    path.append(current["title"])
    for i in range(current_idx - 1, -1, -1):
        if hierarchy[i]["level"] < current["level"]:
            path.insert(0, hierarchy[i]["title"])
            current = hierarchy[i]
    return " > ".join(path)

def summarize_for_router(text: str, max_chars: int = 2000) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r'(?<=[.!?])\s+', text)
    if len(sentences) <= 3:
        return text[:max_chars]
    summary = sentences[0] + " " + sentences[1]
    remaining = max_chars - len(summary) - len(sentences[-1]) - 10
    if remaining > 100:
        middle = " ".join(sentences[2:-1])
        summary += " " + middle[:remaining] + "... " + sentences[-1]
    else:
        summary += "... " + sentences[-1]
    return summary[:max_chars]

def classify_profile(filename: str) -> str:
    n = filename.lower()
    for profile_name, keywords in config.DOC_PROFILES.items():
        if any(k in n for k in keywords):
            return profile_name
    return "general"

def extract_content_tags(text: str) -> List[str]:
    """Extract content-based tags from text for better routing"""
    text_lower = text.lower()
    tags = []
    for tag, keywords in config.CONTENT_TAGS.items():
        if any(kw in text_lower for kw in keywords):
            tags.append(tag)
    return tags

def deduplicate_cross_file(new_chunks: List[Dict], intensity: int, existing_chunks: List[Dict] = None) -> List[Dict]:
    """Filter near-duplicate chunks across files and across runs.
    Seeds seen_hashes from existing_chunks so re-indexed content is caught.
    """
    if intensity == 0:
        return new_chunks
    seen: dict = {}
    # Seed with existing corpus so second-run duplicates are caught
    if existing_chunks:
        for chunk in existing_chunks:
            text = chunk.get("text_raw", chunk.get("text", ""))
            if text:
                seen[sha8(text)] = text[:1000]
    result = []
    for chunk in new_chunks:
        text = chunk.get("text_raw", chunk.get("text", ""))
        if not should_deduplicate(text, seen, intensity):
            result.append(chunk)
    return result

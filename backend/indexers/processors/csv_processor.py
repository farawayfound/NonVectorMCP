# -*- coding: utf-8 -*-
"""CSV processing for ChunkyLink document indexing."""
import csv
import re
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Tuple


def sha8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()[:8]


def should_deduplicate(text: str, seen_hashes: dict, intensity: int) -> bool:
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


def detect_csv_type(headers: List[str], sample_rows: List[Dict]) -> Tuple[str, str]:
    headers_lower = [h.lower() for h in headers]
    priority_cols = ['description', 'summary', 'text', 'comment', 'note', 'name', 'title', 'content']
    for priority in priority_cols:
        for h in headers:
            if priority in h.lower():
                return 'tabular_data', h
    if sample_rows:
        for h in headers:
            sample_text = ' '.join(str(row.get(h, '')) for row in sample_rows[:5])
            if len(sample_text) > 50:
                return 'tabular_data', h
    return 'tabular_data', headers[0] if headers else 'text'


def extract_technical_codes(text: str) -> List[str]:
    codes = []
    codes.extend(re.findall(r'\b[A-Z]{3,5}-\d{3,4}\b', text))
    codes.extend(re.findall(r'\b(INC|TICKET|CASE)\d+\b', text, re.IGNORECASE))
    return list(set(codes))[:10]


def build_for_csv(csv_path: Path, cfg: Dict[str, Any]) -> Dict[str, Any]:
    chunks = []
    dedup_intensity = cfg.get("DEDUPLICATION_INTENSITY", 1)
    seen_hashes = {}
    try:
        with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            sample_rows, all_rows = [], []
            for i, row in enumerate(reader):
                all_rows.append(row)
                if i < 5:
                    sample_rows.append(row)
            if not all_rows:
                return {"router": [], "detail": []}
            csv_type, primary_col = detect_csv_type(headers, sample_rows)
            for row_num, row in enumerate(all_rows, start=2):
                primary_text = str(row.get(primary_col, '')).strip()
                if not primary_text or len(primary_text) < 10:
                    continue
                text_parts = []
                for col, val in row.items():
                    val_str = str(val).strip()
                    if val_str and val_str not in ['', 'Empty', 'None', 'N/A']:
                        text_parts.append(f"{col}: {val_str}")
                full_text = '\n'.join(text_parts)
                tech_codes = extract_technical_codes(full_text)
                breadcrumb_parts = [f"CSV Data ({csv_type})"]
                for col, val in list(row.items())[:5]:
                    val_str = str(val).strip()
                    if val_str and val_str not in ['', 'Empty', 'None'] and len(val_str) < 50:
                        breadcrumb_parts.append(val_str)
                        if len(breadcrumb_parts) >= 4:
                            break
                breadcrumb = " > ".join(breadcrumb_parts)
                row_id = f"row-{row_num}"
                id_match = re.search(r'\b([A-Z]{2,}\d+|[A-Z]+-\d+)\b', primary_text)
                if id_match:
                    row_id = id_match.group(1)
                tags = ["csv-data", csv_type.replace('_', '-')]
                for code in tech_codes[:5]:
                    tags.append(code.lower())
                if not should_deduplicate(full_text, seen_hashes, dedup_intensity):
                    chunks.append({
                        "id": f"{csv_path.name}::{row_id}::{sha8(full_text)}",
                        "text": f"[{breadcrumb}]\n{full_text}", "text_raw": full_text,
                        "element_type": "csv_row",
                        "metadata": {"doc_id": csv_path.name, "source_type": "csv_data",
                                     "csv_type": csv_type, "row_number": row_num,
                                     "primary_column": primary_col,
                                     "technical_codes": tech_codes, "breadcrumb": breadcrumb,
                                     "column_count": len(headers)},
                        "tags": tags[:10], "raw_markdown": None
                    })
    except Exception as e:
        raise Exception(f"Failed to process CSV {csv_path.name}: {e}")
    return {"router": [], "detail": chunks}

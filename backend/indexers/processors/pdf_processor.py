# -*- coding: utf-8 -*-
"""PDF processing for ChunkyPotato document indexing."""
import logging
from pathlib import Path
from typing import List, Dict, Any

try:
    import fitz
except Exception as e:
    fitz = None
    logging.warning("pdf_processor: PyMuPDF unavailable — PDF processing disabled. Run: pip install pymupdf")

from backend.indexers.utils.text_processing import (
    normalize_text, build_hierarchy, build_breadcrumb_path,
    summarize_for_router, sha8, rough_token_len, split_with_overlap, should_deduplicate
)
from backend.indexers.processors.table_extractor import extract_tables
from backend.indexers.utils.ocr_processor import process_pdf_images


def blocks_by_page(doc: "fitz.Document") -> List[List[Dict[str, Any]]]:
    pages = []
    for p in doc:
        blks = p.get_text("blocks")
        blks = sorted(blks, key=lambda b: (round(b[1], 1), round(b[0], 1)))
        page_elems = []
        for b in blks:
            x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
            txt = normalize_text(text)
            if txt:
                page_elems.append({"element_type": "paragraph", "text": txt, "bbox": [x0, y0, x1, y1]})
        pages.append(page_elems)
    return pages


def slice_spans(hierarchy: List[Dict[str, Any]], total_pages: int) -> List[Dict[str, Any]]:
    spans = []
    for idx, node in enumerate(hierarchy):
        start = node["page"]
        end = total_pages - 1
        for j in range(idx + 1, len(hierarchy)):
            nxt = hierarchy[j]
            if nxt["level"] <= node["level"]:
                end = max(start, nxt["page"] - 1)
                break
        spans.append({"title": node["title"], "level": node["level"], "page_start": start, "page_end": end})
    return spans


def build_for_pdf(pdf_path: Path, cfg: Dict[str, Any]) -> Dict[str, Any]:
    if fitz is None:
        raise RuntimeError("PyMuPDF not installed. Run: pip install pymupdf")
    logging.info(f"Processing PDF: {pdf_path.name}")
    doc = fitz.open(str(pdf_path))
    try:
        pages = blocks_by_page(doc)
        tables = extract_tables(pdf_path, cfg)
        table_map = {}
        for tb in tables:
            page = tb.get("page")
            if page is not None:
                table_map.setdefault(page, []).append(tb)
        image_texts = process_pdf_images(doc, cfg)
        ocr_by_page = {}
        for img_data in image_texts:
            ocr_by_page.setdefault(img_data["page"] - 1, []).append(img_data["text"])
        hierarchy = build_hierarchy(doc, cfg.get("MAX_HIERARCHY_DEPTH", 6))
        spans = slice_spans(hierarchy, doc.page_count)
        total_pages = len(pages)
    finally:
        doc.close()

    router_records = []
    detail_records = []
    dedup_intensity = cfg.get("DEDUPLICATION_INTENSITY", 1)
    seen_hashes = {}

    for idx, span in enumerate(spans):
        ps, pe = span["page_start"], span["page_end"]
        raw_text = []
        for p in range(ps, pe + 1):
            for el in pages[p]:
                if el["element_type"] == "paragraph":
                    raw_text.append(el["text"])
            if p in ocr_by_page:
                raw_text.append("\n[OCR from images]\n" + "\n".join(ocr_by_page[p]))

        summary = summarize_for_router(" ".join(raw_text), cfg.get("MAX_ROUTER_SUMMARY_CHARS", 3000))
        ch_id = f"ch{idx+1:02d}"
        breadcrumb = build_breadcrumb_path(hierarchy, idx)

        router_records.append({
            "route_id": f"{pdf_path.name}::{ch_id}",
            "title": span["title"], "breadcrumb": breadcrumb,
            "level": span["level"], "scope_pages": [ps + 1, pe + 1],
            "summary": summary, "tags": []
        })

        current_block_text = []
        block_pages = []
        for p in range(ps, pe + 1):
            for el in pages[p]:
                if el["element_type"] == "paragraph":
                    current_block_text.append(el["text"])
                    block_pages.append(p)
            joined = " ".join(current_block_text).strip()
            target_tokens = cfg.get("PARA_TARGET_TOKENS", 300)
            if rough_token_len(joined) >= target_tokens * 1.5:
                words = joined.split()
                parts = split_with_overlap(words, target_tokens, cfg.get("PARA_OVERLAP_TOKENS", 50))
                for part in parts:
                    rec_id = f"{pdf_path.name}::{ch_id}::p{block_pages[0]+1}-{block_pages[-1]+1}::para::{sha8(part)}"
                    bc = build_breadcrumb_path(hierarchy, idx)
                    if not should_deduplicate(part, seen_hashes, dedup_intensity):
                        detail_records.append({
                            "id": rec_id, "text": f"[{bc}]\n{part}", "text_raw": part,
                            "element_type": "paragraph",
                            "metadata": {"doc_id": pdf_path.name, "chapter_id": ch_id,
                                         "page_start": block_pages[0] + 1, "page_end": block_pages[-1] + 1},
                            "raw_markdown": None
                        })
                current_block_text, block_pages = [], []

        if current_block_text:
            joined = " ".join(current_block_text).strip()
            words = joined.split()
            parts = split_with_overlap(words, cfg.get("PARA_TARGET_TOKENS", 300), cfg.get("PARA_OVERLAP_TOKENS", 50))
            pg0, pg1 = block_pages[0] + 1, block_pages[-1] + 1
            for part in parts:
                rec_id = f"{pdf_path.name}::{ch_id}::p{pg0}-{pg1}::para::{sha8(part)}"
                bc = build_breadcrumb_path(hierarchy, idx)
                if not should_deduplicate(part, seen_hashes, dedup_intensity):
                    detail_records.append({
                        "id": rec_id, "text": f"[{bc}]\n{part}", "text_raw": part,
                        "element_type": "paragraph",
                        "metadata": {"doc_id": pdf_path.name, "chapter_id": ch_id,
                                     "page_start": pg0, "page_end": pg1},
                        "raw_markdown": None
                    })

        for p in range(ps, pe + 1):
            for tb in table_map.get(p, []):
                md = tb.get("markdown", "")
                if md:
                    tbl_id = f"{pdf_path.name}::{ch_id}::p{p+1}::tbl::{sha8(md[:200])}"
                    bc = build_breadcrumb_path(hierarchy, idx)
                    if not should_deduplicate(md[:200], seen_hashes, dedup_intensity):
                        detail_records.append({
                            "id": tbl_id, "text": f"[{bc}]\nTable:\n{md}",
                            "element_type": "table",
                            "metadata": {"doc_id": pdf_path.name, "chapter_id": ch_id,
                                         "page_start": p + 1, "page_end": p + 1},
                            "raw_markdown": md
                        })

    return {"router": router_records, "detail": detail_records, "pages": total_pages}

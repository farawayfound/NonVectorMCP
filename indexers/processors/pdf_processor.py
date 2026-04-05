# -*- coding: utf-8 -*-
"""
PDF processing for VPO RAG indexing
"""

import re, logging, sys
from pathlib import Path
from typing import List, Dict, Any

# Add indexers directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

try:
    import fitz
except Exception as e:
    raise SystemExit("Please install PyMuPDF: pip install pymupdf") from e

from utils.text_processing import (
    normalize_text, build_hierarchy, build_breadcrumb_path, 
    summarize_for_router, sha8, rough_token_len, split_with_overlap, should_deduplicate
)
from processors.table_extractor import extract_tables
from utils.ocr_processor import process_pdf_images

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
        start = node["page"]; end = total_pages - 1
        for j in range(idx + 1, len(hierarchy)):
            nxt = hierarchy[j]
            if nxt["level"] <= node["level"]:
                end = max(start, nxt["page"] - 1); break
        spans.append({"title": node["title"], "level": node["level"], "page_start": start, "page_end": end})
    return spans

def build_for_pdf(pdf_path: Path, cfg: Dict[str, Any]) -> Dict[str, Any]:
    logging.info(f"Processing PDF: {pdf_path.name}")
    doc = fitz.open(str(pdf_path))
    try:
        pages = blocks_by_page(doc)
        
        # Extract tables
        tables = extract_tables(pdf_path)
        table_map = {}
        for tb in tables:
            page = tb.get("page")
            if page is not None:
                table_map.setdefault(page, []).append(tb)
        
        # Extract and OCR images
        image_texts = process_pdf_images(doc, cfg)
        ocr_by_page = {}
        for img_data in image_texts:
            page_num = img_data["page"] - 1
            ocr_by_page.setdefault(page_num, []).append(img_data["text"])
        
        hierarchy = build_hierarchy(doc, cfg.get("MAX_HIERARCHY_DEPTH", config.MAX_HIERARCHY_DEPTH))
        spans = slice_spans(hierarchy, doc.page_count)
        total_pages = len(pages)
    finally:
        doc.close()
    
    router_records = []
    detail_records = []
    dedup_intensity = cfg.get("DEDUPLICATION_INTENSITY", 1)
    seen_hashes = {}  # For deduplication
    
    for idx, span in enumerate(spans):
        ps, pe = span["page_start"], span["page_end"]
        raw_text = []
        for p in range(ps, pe + 1):
            for el in pages[p]:
                if el["element_type"] == "paragraph":
                    raw_text.append(el["text"])
            if p in ocr_by_page:
                raw_text.append("\n[OCR from images]\n" + "\n".join(ocr_by_page[p]))
        
        summary = summarize_for_router(" ".join(raw_text), cfg.get("MAX_ROUTER_SUMMARY_CHARS", config.MAX_ROUTER_SUMMARY_CHARS))
        ch_id = f"ch{idx+1:02d}"
        breadcrumb = build_breadcrumb_path(hierarchy, idx)
        
        router_records.append({
            "route_id": f"{pdf_path.name}::{ch_id}",
            "title": span["title"],
            "breadcrumb": breadcrumb,
            "level": span["level"],
            "scope_pages": [ps + 1, pe + 1],
            "summary": summary,
            "tags": []
        })
        
        # Process chunks
        current_block_text = []
        block_pages = []
        for p in range(ps, pe + 1):
            for el in pages[p]:
                if el["element_type"] == "paragraph":
                    current_block_text.append(el["text"])
                    block_pages.append(p)
            
            joined = " ".join(current_block_text).strip()
            target_tokens = cfg.get("PARA_TARGET_TOKENS", config.PARA_TARGET_TOKENS)
            if rough_token_len(joined) >= target_tokens * 1.5:
                words = joined.split()
                parts = split_with_overlap(words, target_tokens, cfg.get("PARA_OVERLAP_TOKENS", config.PARA_OVERLAP_TOKENS))
                for part in parts:
                    rec_id = f"{pdf_path.name}::{ch_id}::p{block_pages[0]+1}-{block_pages[-1]+1}::para::{sha8(part)}"
                    breadcrumb = build_breadcrumb_path(hierarchy, idx)
                    contextualized_text = f"[{breadcrumb}]\n{part}"
                    if not should_deduplicate(part, seen_hashes, dedup_intensity):
                        detail_records.append({
                            "id": rec_id, 
                            "text": contextualized_text,
                            "text_raw": part,
                            "element_type": "paragraph",
                            "metadata": {
                                "doc_id": pdf_path.name, 
                                "chapter_id": ch_id,
                                "page_start": block_pages[0] + 1, 
                                "page_end": block_pages[-1] + 1
                            },
                            "raw_markdown": None
                        })
                current_block_text, block_pages = [], []
        
        if current_block_text:
            joined = " ".join(current_block_text).strip()
            words = joined.split()
            parts = split_with_overlap(words, cfg.get("PARA_TARGET_TOKENS", config.PARA_TARGET_TOKENS), cfg.get("PARA_OVERLAP_TOKENS", config.PARA_OVERLAP_TOKENS))
            pg0 = block_pages[0] + 1; pg1 = block_pages[-1] + 1
            for part in parts:
                rec_id = f"{pdf_path.name}::{ch_id}::p{pg0}-{pg1}::para::{sha8(part)}"
                breadcrumb = build_breadcrumb_path(hierarchy, idx)
                contextualized_text = f"[{breadcrumb}]\n{part}"
                if not should_deduplicate(part, seen_hashes, dedup_intensity):
                    detail_records.append({
                        "id": rec_id, 
                        "text": contextualized_text,
                        "text_raw": part,
                        "element_type": "paragraph",
                        "metadata": {
                            "doc_id": pdf_path.name, 
                            "chapter_id": ch_id,
                            "page_start": pg0, "page_end": pg1
                        },
                        "raw_markdown": None
                    })
        
        # Add tables
        for p in range(ps, pe + 1):
            for tb in table_map.get(p, []):
                md = tb.get("markdown", "")
                if md:
                    tbl_id = f"{pdf_path.name}::{ch_id}::p{p+1}::tbl::{sha8(md[:200])}"
                    breadcrumb = build_breadcrumb_path(hierarchy, idx)
                    if not should_deduplicate(md[:200], seen_hashes, dedup_intensity):
                        detail_records.append({
                            "id": tbl_id,
                            "text": f"[{breadcrumb}]\nTable:\n{md}",
                            "element_type": "table",
                            "metadata": {
                                "doc_id": pdf_path.name,
                                "chapter_id": ch_id,
                                "page_start": p + 1, "page_end": p + 1
                            },
                            "raw_markdown": md
                        })
    
    return {"router": router_records, "detail": detail_records, "pages": total_pages}
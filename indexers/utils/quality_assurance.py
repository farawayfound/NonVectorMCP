# -*- coding: utf-8 -*-
"""
Quality assurance utilities for knowledge retention
"""

import json, logging, re, sys
from pathlib import Path
from typing import Dict, List, Any

# Add indexers directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

def validate_extraction_completeness(pdf_path: Path, extracted_records: List[Dict]) -> Dict[str, Any]:
    """Validate that extraction captured most content"""
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        
        # Count original pages and text blocks
        total_pages = doc.page_count
        total_text_blocks = 0
        total_chars = 0
        
        for page in doc:
            blocks = page.get_text("blocks")
            total_text_blocks += len([b for b in blocks if b[4].strip()])
            total_chars += len(page.get_text())
        
        # Count extracted chunks
        extracted_chunks = len(extracted_records)
        extracted_chars = sum(len(r.get("text", "")) for r in extracted_records)
        
        coverage = {
            "pdf_file": pdf_path.name,
            "original_pages": total_pages,
            "original_text_blocks": total_text_blocks,
            "original_chars": total_chars,
            "extracted_chunks": extracted_chunks,
            "extracted_chars": extracted_chars,
            "char_retention_ratio": extracted_chars / max(total_chars, 1),
            "chunks_per_page": extracted_chunks / max(total_pages, 1)
        }
        
        # Flag potential issues
        if coverage["char_retention_ratio"] < 0.7:
            logging.warning(f"Low text retention ({coverage['char_retention_ratio']:.1%}) for {pdf_path.name}")
        
        return coverage
        
    except Exception as e:
        logging.error(f"QA validation failed for {pdf_path.name}: {e}")
        return {"pdf_file": pdf_path.name, "error": str(e)}

def generate_qa_report(qa_results: List[Dict], output_dir: Path):
    """Generate quality assurance report"""
    report = {
        "total_files": len(qa_results),
        "avg_retention_ratio": sum(r.get("char_retention_ratio", 0) for r in qa_results) / len(qa_results),
        "low_retention_files": [r for r in qa_results if r.get("char_retention_ratio", 1) < 0.7],
        "files": qa_results
    }
    
    qa_file = output_dir / "qa_report.json"
    with open(qa_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    logging.info(f"QA Report: {report['total_files']} files, {report['avg_retention_ratio']:.1%} avg retention")
    if report['low_retention_files']:
        logging.warning(f"{len(report['low_retention_files'])} files have low retention rates")

_PRINTABLE_ASCII = frozenset(range(32, 127))

def is_quality_chunk(text: str, min_words: int = 10) -> bool:
    """Return False for chunks that are too short or contain excessive non-printable-ASCII (garbled OCR)."""
    words = text.split()
    if len(words) < min_words:
        return False
    if text and sum(1 for c in text if ord(c) not in _PRINTABLE_ASCII) / len(text) > 0.15:
        return False
    from collections import Counter
    if Counter(w.lower() for w in words).most_common(1)[0][1] / len(words) > 0.5:
        return False
    return True
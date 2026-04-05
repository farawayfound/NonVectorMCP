# -*- coding: utf-8 -*-
"""
Table extraction for PDF processing
"""

import logging, sys
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

def extract_tables(pdf_path: Path) -> List[Dict[str, Any]]:
    """Extract tables from PDF using pdfplumber and optionally Camelot"""
    tables = []
    
    # pdfplumber with smart detection
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, page in enumerate(pdf.pages):
                # Quick check: skip if page has no lines or very few words
                if not page.lines and len(page.extract_words()) < 20:
                    continue
                
                # Only try line-based extraction (faster and more reliable)
                try:
                    for tbl in page.extract_tables(table_settings={"vertical_strategy": "lines", "horizontal_strategy": "lines"}) or []:
                        if not tbl or len(tbl) < 2: continue
                        max_cols = max(len(r) for r in tbl)
                        if max_cols < 2: continue
                        header = [(tbl[0][c] or "").strip() for c in range(max_cols)]
                        body = [[(r[c] or "").strip() if c < len(r) else "" for c in range(max_cols)] for r in tbl[1:]]
                        md = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * max_cols) + " |"]
                        md += ["| " + " | ".join(r) + " |" for r in body]
                        tables.append({"element_type": "table", "markdown": "\n".join(md), "page": i, "source": "pdfplumber"})
                except Exception:
                    pass
    except Exception:
        pass
    
    # Camelot (optional)
    if config.ENABLE_CAMELOT:
        try:
            import camelot
            for flavor in ["lattice", "stream"]:
                try:
                    for tb in camelot.read_pdf(str(pdf_path), pages="all", flavor=flavor):
                        df = tb.df
                        if df.shape[0] >= 2 and df.shape[1] >= 2:
                            header = list(df.iloc[0].fillna("").map(str))
                            body = df.iloc[1:].fillna("").astype(str).values.tolist()
                            md = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
                            md += ["| " + " | ".join(r) + " |" for r in body]
                            page_num = getattr(tb, "page", None)
                            tables.append({"element_type": "table", "markdown": "\n".join(md), 
                                         "page": (page_num - 1) if page_num else None, "source": f"camelot:{flavor}"})
                except Exception:
                    continue
        except Exception:
            pass
    
    # Deduplicate
    seen, uniq = set(), []
    for t in tables:
        sig = (t.get("page"), (t.get("markdown") or "")[:400])
        if sig not in seen:
            seen.add(sig)
            uniq.append(t)
    return uniq

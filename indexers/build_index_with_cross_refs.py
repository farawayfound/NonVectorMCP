# -*- coding: utf-8 -*-
"""
Combined VPO RAG Indexer with Inline Cross-Referencing
- Processes documents and builds cross-references in one pass
- 2x faster than two-stage approach
- Maintains all existing functionality
"""

import os, io, re, json, math, hashlib, datetime, logging, sys
from pathlib import Path
from typing import List, Dict, Any

# Support both package and direct execution
try:
    # Try package imports first (when run as: python -m indexers.build_index_with_cross_refs)
    from indexers import config
    from indexers.core.incremental_indexer import IncrementalIndexer
    from indexers.utils.topic_metadata import add_topic_metadata
    from indexers.utils.text_processing import classify_profile, summarize_for_router, normalize_text, extract_content_tags
    from indexers.utils.nlp_classifier import enrich_record_with_nlp
    from indexers.utils.cross_reference import (
        enrich_chunk_with_cross_refs, 
        build_topic_clusters,
        get_term_aliases,
        auto_generate_aliases
    )
    from indexers.processors.pdf_processor import build_for_pdf
    from indexers.processors.text_processor import build_for_txt, build_for_docx, build_for_pptx
    from indexers.processors.csv_processor import build_for_csv
except ImportError:
    # Fall back to direct imports (when run as: cd indexers && python build_index_with_cross_refs.py)
    sys.path.insert(0, str(Path(__file__).parent))
    import config
    from core.incremental_indexer import IncrementalIndexer
    from utils.topic_metadata import add_topic_metadata
    from utils.text_processing import classify_profile, summarize_for_router, normalize_text, extract_content_tags
    from utils.nlp_classifier import enrich_record_with_nlp
    from utils.cross_reference import (
        enrich_chunk_with_cross_refs, 
        build_topic_clusters,
        get_term_aliases,
        auto_generate_aliases
    )
    from processors.pdf_processor import build_for_pdf
    from processors.text_processor import build_for_txt, build_for_docx, build_for_pptx
    from processors.csv_processor import build_for_csv

def sha8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()[:8]

def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')

def ensure_dirs():
    for p in [
        Path(config.OUT_DIR, "detail"),
        Path(config.OUT_DIR, "router"),
        Path(config.OUT_DIR, "logs"),
        Path(config.OUT_DIR, "manifests"),
        Path(config.OUT_DIR, "state"),
    ]:
        p.mkdir(parents=True, exist_ok=True)

ensure_dirs()
log_path = Path(config.OUT_DIR, "logs", "build_index_with_cross_refs.log")
logging.basicConfig(
    filename=str(log_path),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger().addHandler(console)

try:
    import fitz
    fitz.TOOLS.mupdf_display_errors(False)
except Exception as e:
    raise SystemExit("Please install PyMuPDF: pip install pymupdf") from e



def split_with_overlap(words: List[str], target_tokens: int, overlap_tokens: int) -> List[str]:
    out = []; i = 0
    while i < len(words):
        j = min(len(words), i + target_tokens)
        out.append(" ".join(words[i:j]).strip())
        if j >= len(words): break
        i = max(j - overlap_tokens, i + 1)
    return out

def split_glossary_entries(text: str) -> List[dict]:
    entries = []
    for line in re.split(r"[\r\n]+", text):
        line = line.strip()
        if not line: continue
        m = re.match(r"^([A-Za-z0-9\/\-\(\)\s]{2,40})\s*[-–:]\s*(.+)$", line)
        if m:
            term, definition = m.group(1).strip(), m.group(2).strip()
            entries.append((term, definition))
    chunks = []
    for term, definition in entries:
        part = f"{term}: {definition}"
        chunks.append({
            "id": f"gloss::{sha8(part)}",
            "text": part,
            "element_type": "glossary",
            "metadata": {
                "doc_id": None,
                "chapter_id": "glossary",
                "page_start": None, "page_end": None
            },
            "raw_markdown": None
        })
    return chunks

def near_duplicate(a_text: str, b_text: str) -> bool:
    try:
        from rapidfuzz import fuzz
        a = " ".join(a_text.split())[:20000]
        b = " ".join(b_text.split())[:20000]
        return fuzz.token_set_ratio(a, b) >= 90
    except Exception:
        return False

def main():
    ensure_dirs()
    
    indexer = IncrementalIndexer(config.OUT_DIR)
    files_by_status = indexer.get_files_to_process(config.SRC_DIR)
    files_to_process = files_by_status["new"] + files_by_status["modified"]
    
    if not files_to_process:
        logging.info("No new or modified files to process.")
        return
    
    logging.info(f"Processing {len(files_to_process)} files ({len(files_by_status['new'])} new, {len(files_by_status['modified'])} modified)")
    
    all_router_docs, all_router_chapters, all_detail = [], [], []
    manifest = {"started": now_iso(), "files": [], "out_dir": config.OUT_DIR, "totals": {}}
    sop_buckets = {}

    for path in files_to_process:
        if path in files_by_status["modified"]:
            old_doc_ids = indexer.get_existing_doc_ids(path)
            if old_doc_ids:
                indexer.remove_old_records(old_doc_ids)
                logging.info(f"Removed old records for modified file: {path.name}")
        
        if getattr(config, 'ENABLE_AUTO_CLASSIFICATION', False):
            prof = "auto"
        else:
            prof = classify_profile(path.name)
        logging.info(f"Processing [{prof}] {path}")

        if path.suffix.lower() == ".pptx":
            try:
                res = build_for_pptx(path, vars(config))
                full_text = " ".join([r["summary"] for r in res["router"]])[:5000]
                for record in res["router"]:
                    all_router_chapters.append(enrich_record_with_nlp(add_topic_metadata(record, path), record.get("summary", "")))
                
                doc_record = {
                    "route_id": f"{path.name}::doc",
                    "title": path.stem,
                    "scope_pages": [1, len(res["router"])],
                    "summary": summarize_for_router(full_text, config.MAX_ROUTER_SUMMARY_CHARS),
                    "tags": [prof]
                }
                all_router_docs.append(enrich_record_with_nlp(add_topic_metadata(doc_record, path), full_text))
                
                for record in res["detail"]:
                    all_detail.append(enrich_record_with_nlp(add_topic_metadata(record, path), record.get("text_raw", record.get("text", ""))))
            except Exception as ex:
                logging.exception(f"PPTX error {path.name}: {ex}")

        elif path.suffix.lower() == ".pdf":
            try:
                if prof == "glossary" or "glossary" in path.name.lower():
                    doc = fitz.open(str(path))
                    text = " ".join([normalize_text(pg.get_text("text")) for pg in doc])
                    gloss_chunks = split_glossary_entries(text)
                    doc_record = {
                        "route_id": f"{path.name}::doc",
                        "title": path.stem,
                        "scope_pages": [1, doc.page_count],
                        "summary": summarize_for_router(text, config.MAX_ROUTER_SUMMARY_CHARS),
                        "tags": ["glossary"]
                    }
                    all_router_docs.append(add_topic_metadata(doc_record, path))
                    
                    for c in gloss_chunks:
                        c["metadata"]["doc_id"] = path.name
                        all_detail.append(enrich_record_with_nlp(add_topic_metadata(c, path), c.get("text", "")))
                    doc.close()
                else:
                    res = build_for_pdf(path, vars(config))
                    full_text = " ".join([r["summary"] for r in res["router"]])[:4000]
                    for record in res["router"]:
                        all_router_chapters.append(enrich_record_with_nlp(add_topic_metadata(record, path), record.get("summary", "")))
                    
                    content_tags = extract_content_tags(full_text)
                    doc_record = {
                        "route_id": f"{path.name}::doc",
                        "title": path.stem,
                        "scope_pages": [1, res["pages"]],
                        "summary": summarize_for_router(full_text, config.MAX_ROUTER_SUMMARY_CHARS),
                        "tags": [prof] + content_tags
                    }
                    all_router_docs.append(enrich_record_with_nlp(add_topic_metadata(doc_record, path), full_text))
                    
                    for record in res["detail"]:
                        all_detail.append(enrich_record_with_nlp(add_topic_metadata(record, path), record.get("text_raw", record.get("text", ""))))
                    
                    if prof == "sop" or "sop" in path.name.lower():
                        base = re.sub(r"v\d+|\d{8}_\d{6}", "", path.stem, flags=re.I).strip().lower()
                        sop_buckets.setdefault(base, []).append(path)
            except Exception as ex:
                logging.exception(f"PDF error {path.name}: {ex}")
                continue

        elif path.suffix.lower() == ".txt":
            try:
                res = build_for_txt(path, vars(config))
                full_text = res["router"][0]["summary"] if res["router"] else ""
                for record in res["router"]:
                    all_router_chapters.append(enrich_record_with_nlp(add_topic_metadata(record, path), record.get("summary", "")))
                for record in res["detail"]:
                    all_detail.append(enrich_record_with_nlp(add_topic_metadata(record, path), record.get("text_raw", "")))
                
                doc_record = {
                    "route_id": f"{path.name}::doc",
                    "title": path.stem,
                    "scope_pages": [1, 1],
                    "summary": full_text,
                    "tags": [prof]
                }
                all_router_docs.append(enrich_record_with_nlp(add_topic_metadata(doc_record, path), full_text))
            except Exception as ex:
                logging.exception(f"TXT error {path.name}: {ex}")

        elif path.suffix.lower() == ".docx":
            try:
                res = build_for_docx(path, vars(config))
                full_text = " ".join([r["summary"] for r in res["router"]])[:4000]
                for record in res["router"]:
                    all_router_chapters.append(enrich_record_with_nlp(add_topic_metadata(record, path), record.get("summary", "")))
                for record in res["detail"]:
                    all_detail.append(enrich_record_with_nlp(add_topic_metadata(record, path), record.get("text_raw", "")))
                
                doc_record = {
                    "route_id": f"{path.name}::doc",
                    "title": path.stem,
                    "scope_pages": [1, len(res["router"])],
                    "summary": summarize_for_router(full_text, config.MAX_ROUTER_SUMMARY_CHARS),
                    "tags": [prof]
                }
                all_router_docs.append(enrich_record_with_nlp(add_topic_metadata(doc_record, path), full_text))
            except Exception as ex:
                logging.exception(f"DOCX error {path.name}: {ex}")

        elif path.suffix.lower() == ".csv":
            try:
                res = build_for_csv(path, vars(config))
                logging.info(f"Processed {len(res['detail'])} CSV records from {path.name}")
                
                # Apply NLP enrichment to CSV data (same as PDFs)
                for record in res["detail"]:
                    all_detail.append(enrich_record_with_nlp(add_topic_metadata(record, path), record.get("text_raw", "")))
                
                # Build summary from first few rows
                sample_text = ' '.join([r.get("text_raw", "")[:200] for r in res["detail"][:5]])
                csv_type = res["detail"][0]["metadata"].get("csv_type", "data") if res["detail"] else "data"
                
                doc_record = {
                    "route_id": f"{path.name}::doc",
                    "title": f"CSV Data - {path.stem}",
                    "scope_pages": [1, len(res["detail"])],
                    "summary": f"CSV dataset with {len(res['detail'])} records (type: {csv_type})",
                    "tags": ["csv-data", csv_type]
                }
                all_router_docs.append(enrich_record_with_nlp(add_topic_metadata(doc_record, path), sample_text))
            except Exception as ex:
                logging.exception(f"CSV error {path.name}: {ex}")

        manifest["files"].append({"file": path.name, "profile": prof})
        indexer.mark_processed(path, [path.name])

    # SOP deduplication
    pruned_ids = set()
    for base, paths in sop_buckets.items():
        if len(paths) >= 2:
            paths = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
            keep, others = paths[0], paths[1:]
            try:
                doc_keep = fitz.open(str(keep))
                text_keep = " ".join([normalize_text(pg.get_text("text")) for pg in doc_keep.pages[:10]])
                for o in others:
                    doc_o = fitz.open(str(o))
                    text_o = " ".join([normalize_text(pg.get_text("text")) for pg in doc_o.pages[:10]])
                    if near_duplicate(text_keep, text_o):
                        pruned_ids.add(o.name)
                        logging.info(f"Near-duplicate SOP pruned: {o.name} (keeping {keep.name})")
            except Exception:
                pass
    
    if pruned_ids:
        all_detail = [d for d in all_detail if d["metadata"].get("doc_id") not in pruned_ids]
        all_router_docs = [r for r in all_router_docs if r["route_id"].split("::")[0] not in pruned_ids]
        all_router_chapters = [r for r in all_router_chapters if r["route_id"].split("::")[0] not in pruned_ids]

    # Build cross-references inline (if enabled)
    if getattr(config, 'ENABLE_CROSS_REFERENCES', True) and all_detail:
        logging.info(f"Building cross-references for {len(all_detail)} new chunks...")
        
        max_related = getattr(config, 'MAX_RELATED_CHUNKS', 5)
        min_similarity = getattr(config, 'MIN_SIMILARITY_THRESHOLD', 0.7)
        
        # Load existing chunks for symmetrical cross-referencing
        chunks_file = Path(config.OUT_DIR) / "detail" / "chunks.jsonl"
        existing_chunks = []
        if chunks_file.exists():
            logging.info("Loading existing chunks for symmetrical cross-referencing...")
            with open(chunks_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        existing_chunks.append(json.loads(line))
            logging.info(f"Loaded {len(existing_chunks)} existing chunks")
        
        # Combine new + existing for full corpus analysis
        all_chunks = existing_chunks + all_detail
        logging.info(f"Total corpus: {len(all_chunks)} chunks ({len(existing_chunks)} existing + {len(all_detail)} new)")
        
        term_aliases = get_term_aliases()
        if not term_aliases:
            logging.info("Auto-generating term aliases from full corpus...")
            term_aliases = auto_generate_aliases(all_chunks)
            logging.info(f"Generated {len(term_aliases)} term alias groups")
        else:
            logging.info(f"Using {len(term_aliases)} term alias groups from config")
        
        clusters = build_topic_clusters(all_chunks)
        logging.info(f"Created {len(clusters)} topic clusters")
        
        # Build cross-refs for new chunks (forward refs: new→existing)
        logging.info("Building forward references (new→existing)...")
        for i, chunk in enumerate(all_detail):
            if i % 100 == 0 and i > 0:
                logging.info(f"Processing new chunk {i}/{len(all_detail)}")
            enrich_chunk_with_cross_refs(chunk, all_chunks, clusters, term_aliases, max_related, min_similarity)
        
        # Build backward refs (existing→new) for symmetry
        if existing_chunks:
            logging.info(f"Building backward references (existing→new) for symmetry...")
            new_chunk_ids = {c.get("id") for c in all_detail}
            updated_existing = 0
            
            for i, existing_chunk in enumerate(existing_chunks):
                if i % 100 == 0 and i > 0:
                    logging.info(f"Updating existing chunk {i}/{len(existing_chunks)}")
                
                # Re-compute cross-refs for existing chunks to include new chunks
                old_related = set(existing_chunk.get("related_chunks", []))
                enrich_chunk_with_cross_refs(existing_chunk, all_chunks, clusters, term_aliases, max_related, min_similarity)
                new_related = set(existing_chunk.get("related_chunks", []))
                
                # Check if any new chunks were added to related_chunks
                if new_related & new_chunk_ids:
                    updated_existing += 1
            
            logging.info(f"Updated {updated_existing} existing chunks with backward references")
            
            # Replace all_detail with combined chunks for writing
            all_detail = all_chunks
        
        total_related = sum(len(c.get("related_chunks", [])) for c in all_detail)
        avg_related = total_related / len(all_detail) if all_detail else 0
        logging.info(f"Average related chunks per chunk: {avg_related:.2f}")

    # Write records (overwrite detail if symmetrical cross-refs were built)
    if getattr(config, 'ENABLE_CROSS_REFERENCES', True) and len(all_detail) > len(files_to_process) * 10:
        # Symmetrical cross-refs were built, need to overwrite chunks.jsonl
        logging.info("Writing all chunks (symmetrical cross-refs enabled)...")
        chunks_file = Path(config.OUT_DIR) / "detail" / "chunks.jsonl"
        with open(chunks_file, 'w', encoding='utf-8') as f:
            for chunk in all_detail:
                f.write(json.dumps(chunk, ensure_ascii=False) + '\n')
        
        # Append only router records
        new_records = {
            "router_docs": all_router_docs,
            "router_chapters": all_router_chapters,
            "detail": []  # Already written
        }
    else:
        # No symmetrical cross-refs, append as normal
        new_records = {
            "router_docs": all_router_docs,
            "router_chapters": all_router_chapters,
            "detail": all_detail
        }
    
    indexer.append_new_records(new_records)
    
    manifest["completed"] = now_iso()
    with open(Path(config.OUT_DIR, "manifests", "run_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    
    indexer.finalize_run()

    logging.info(f"Combined processing complete. Processed {len(files_to_process)} files with cross-references.")

if __name__ == "__main__":
    main()

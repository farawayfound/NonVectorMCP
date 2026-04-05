# -*- coding: utf-8 -*-
"""
JSON-based VPO RAG Indexer
Outputs structured JSONL files to JSON/ directory
Usage: python build_index_json.py
"""

import re, json, hashlib, datetime, logging, sys
from pathlib import Path
from typing import List, Dict, Any
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

# Support both package and direct execution
try:
    # Try package imports first (when run as: python -m indexers.build_index_with_cross_refs)
    from indexers import config
    from indexers.core.incremental_indexer import IncrementalIndexer
    from indexers.utils.topic_metadata import add_topic_metadata
    from indexers.utils.text_processing import classify_profile, summarize_for_router, normalize_text, extract_content_tags, deduplicate_cross_file
    from indexers.utils.nlp_classifier import enrich_record_with_nlp
    from indexers.utils.cross_reference import (
        enrich_chunk_with_cross_refs, 
        build_topic_clusters,
        get_term_aliases,
        auto_generate_aliases,
        clear_doc_cache
    )
    from indexers.processors.pdf_processor import build_for_pdf
    from indexers.processors.text_processor import build_for_txt, build_for_docx, build_for_pptx
    from indexers.processors.csv_processor import build_for_csv
    from indexers.utils.quality_assurance import is_quality_chunk
except ImportError:
    # Fall back to direct imports (when run as: cd indexers && python build_index_with_cross_refs.py)
    sys.path.insert(0, str(Path(__file__).parent))
    import config
    from core.incremental_indexer import IncrementalIndexer
    from utils.topic_metadata import add_topic_metadata
    from utils.text_processing import classify_profile, summarize_for_router, normalize_text, extract_content_tags, deduplicate_cross_file
    from utils.nlp_classifier import enrich_record_with_nlp
    from utils.cross_reference import (
        enrich_chunk_with_cross_refs, 
        build_topic_clusters,
        get_term_aliases,
        auto_generate_aliases,
        clear_doc_cache
    )
    from processors.pdf_processor import build_for_pdf
    from processors.text_processor import build_for_txt, build_for_docx, build_for_pptx
    from processors.csv_processor import build_for_csv
    from utils.quality_assurance import is_quality_chunk

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

try:
    from indexers.utils.cpni_sanitizer import sanitize_cpni as _sanitize_cpni
except ImportError:
    try:
        from utils.cpni_sanitizer import sanitize_cpni as _sanitize_cpni
    except ImportError:
        _sanitize_cpni = lambda t: t

def _promote_nlp_category(enriched: Dict) -> Dict:
    """Promote nlp_category to first tag position"""
    nlp_cat = enriched.get("metadata", {}).get("nlp_category")
    if nlp_cat:
        enriched["tags"] = [nlp_cat] + [t for t in enriched.get("tags", []) if t != nlp_cat]
    return enriched

def _enrich(record: Dict, text: str, path: Path) -> Dict:
    text = _sanitize_cpni(text)
    if "text_raw" in record:
        record["text_raw"] = _sanitize_cpni(record["text_raw"])
    return _promote_nlp_category(enrich_record_with_nlp(add_topic_metadata(record, path), text))

ensure_dirs()
log_path = Path(config.OUT_DIR, "logs", "build_index.log")
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

def near_duplicate(a_text: str, b_text: str, intensity: int) -> bool:
    if intensity == 0:
        return False
    if intensity == 1:
        return a_text == b_text
    
    try:
        from rapidfuzz import fuzz
        threshold = 100 - (intensity - 1) * 3
        a = " ".join(a_text.split())[:20000]
        b = " ".join(b_text.split())[:20000]
        return fuzz.token_set_ratio(a, b) >= threshold
    except Exception:
        return False

def write_chunks_by_category(all_chunks: List[Dict], detail_dir: Path):
    """Write chunks to temp files, then atomically replace live files on success."""
    from collections import defaultdict

    chunks_by_category = defaultdict(list)
    for chunk in all_chunks:
        category = chunk.get('metadata', {}).get('nlp_category', 'general')
        chunks_by_category[category].append(chunk)

    tmp_files = []  # (tmp_path, final_path)
    try:
        # Write all category files to .tmp
        for category, chunks in chunks_by_category.items():
            final = detail_dir / f"chunks.{category}.jsonl"
            tmp   = detail_dir / f"chunks.{category}.jsonl.tmp"
            with open(tmp, 'w', encoding='utf-8') as f:
                for chunk in chunks:
                    f.write(json.dumps(chunk, ensure_ascii=False) + '\n')
            tmp_files.append((tmp, final))
            logging.info(f"Wrote {len(chunks)} chunks to chunks.{category}.jsonl")

        # Write unified file to .tmp
        unified_tmp   = detail_dir / "chunks.jsonl.tmp"
        unified_final = detail_dir / "chunks.jsonl"
        with open(unified_tmp, 'w', encoding='utf-8') as f:
            for chunk in all_chunks:
                f.write(json.dumps(chunk, ensure_ascii=False) + '\n')
        tmp_files.append((unified_tmp, unified_final))
        logging.info(f"Wrote {len(all_chunks)} chunks to unified chunks.jsonl")

        # All writes succeeded — atomically replace live files
        for tmp, final in tmp_files:
            tmp.replace(final)

    except Exception:
        # Clean up any .tmp files so they don't linger
        for tmp, _ in tmp_files:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
        raise

def _has_unenriched_learned_chunks(learned_file: Path) -> bool:
    """Return True if chunks.learned.jsonl exists and contains any chunk missing search_text."""
    if not learned_file.exists():
        return False
    with open(learned_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    chunk = json.loads(line)
                    if not chunk.get('search_text'):
                        return True
                except Exception:
                    pass
    return False


def enrich_learned_chunks():
    """Cross-reference and keyword-enrich learned chunks against the existing KB.
    Called when no source files changed but chunks.learned.jsonl has unenriched entries.
    """
    detail_dir = Path(config.OUT_DIR) / "detail"
    learned_file = detail_dir / "chunks.learned.jsonl"

    logging.info("Enriching learned chunks against existing KB...")

    # Load all existing KB chunks (category files, excluding learned)
    all_kb_chunks = []
    for cat_file in detail_dir.glob("chunks.*.jsonl"):
        if cat_file.name in ("chunks.jsonl", "chunks.learned.jsonl"):
            continue
        with open(cat_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        all_kb_chunks.append(json.loads(line))
                    except Exception:
                        pass

    # Load learned chunks
    learned_chunks = []
    with open(learned_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    learned_chunks.append(json.loads(line))
                except Exception:
                    pass

    if not learned_chunks:
        logging.info("No learned chunks found — skipping.")
        return

    logging.info(f"Loaded {len(all_kb_chunks)} KB chunks + {len(learned_chunks)} learned chunks")

    max_related = getattr(config, 'MAX_RELATED_CHUNKS', 5)
    min_similarity = getattr(config, 'MIN_SIMILARITY_THRESHOLD', 0.7)
    all_chunks = all_kb_chunks + learned_chunks

    term_aliases = get_term_aliases()
    if not term_aliases:
        term_aliases = auto_generate_aliases(all_chunks)

    clusters = build_topic_clusters(all_chunks)

    for chunk in learned_chunks:
        enrich_chunk_with_cross_refs(chunk, all_chunks, clusters, term_aliases, max_related, min_similarity)

    # Write enriched learned chunks back
    with open(learned_file, 'w', encoding='utf-8') as f:
        for chunk in learned_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + '\n')

    logging.info(f"Enriched {len(learned_chunks)} learned chunks with cross-references.")


def _process_file(path: Path, prof: str, cfg: dict) -> dict:
    """Process a single file in a worker process. Returns router + detail records."""
    # Re-import in worker process (each process needs its own module state)
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).parent))
    import config as _config
    # Apply cfg overrides so worker sees same config as parent
    for k, v in cfg.items():
        setattr(_config, k, v)

    from utils.topic_metadata import add_topic_metadata
    from utils.text_processing import classify_profile, summarize_for_router, normalize_text, extract_content_tags
    from utils.nlp_classifier import enrich_record_with_nlp
    from processors.pdf_processor import build_for_pdf
    from processors.text_processor import build_for_txt, build_for_docx, build_for_pptx
    from processors.csv_processor import build_for_csv
    from utils.quality_assurance import is_quality_chunk
    try:
        from utils.cpni_sanitizer import sanitize_cpni as _san
    except ImportError:
        _san = lambda t: t

    import fitz, re, hashlib, logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    def _sha8(s):
        return hashlib.sha256(s.encode('utf-8', errors='ignore')).hexdigest()[:8]

    def _promote(enriched):
        cat = enriched.get('metadata', {}).get('nlp_category')
        if cat:
            enriched['tags'] = [cat] + [t for t in enriched.get('tags', []) if t != cat]
        return enriched

    def _enrich_w(record, text, p):
        text = _san(text)
        if 'text_raw' in record:
            record['text_raw'] = _san(record['text_raw'])
        return _promote(enrich_record_with_nlp(add_topic_metadata(record, p), text))

    router_docs, router_chapters, detail = [], [], []
    sop_key = None

    try:
        if path.suffix.lower() == '.pptx':
            res = build_for_pptx(path, cfg)
            full_text = ' '.join([r['summary'] for r in res['router']])[:5000]
            router_chapters.extend([_enrich_w(r, r.get('summary', ''), path) for r in res['router']])
            router_docs.append(_enrich_w({
                'route_id': f'{path.name}::doc', 'title': path.stem,
                'scope_pages': [1, len(res['router'])],
                'summary': summarize_for_router(full_text, cfg.get('MAX_ROUTER_SUMMARY_CHARS', 3000)),
                'tags': [prof]
            }, full_text, path))
            detail.extend([_enrich_w(r, r.get('text_raw', r.get('text', '')), path) for r in res['detail']])

        elif path.suffix.lower() == '.pdf':
            if prof == 'glossary' or 'glossary' in path.name.lower():
                doc = fitz.open(str(path))
                try:
                    text = ' '.join([normalize_text(pg.get_text('text')) for pg in doc])
                    page_count = doc.page_count
                finally:
                    doc.close()
                gloss_chunks = split_glossary_entries(text)
                router_docs.append(add_topic_metadata({
                    'route_id': f'{path.name}::doc', 'title': path.stem,
                    'scope_pages': [1, page_count],
                    'summary': summarize_for_router(text, cfg.get('MAX_ROUTER_SUMMARY_CHARS', 3000)),
                    'tags': ['glossary']
                }, path))
                for c in gloss_chunks:
                    c['metadata']['doc_id'] = path.name
                    detail.append(_enrich_w(c, c.get('text', ''), path))
                doc.close()
            else:
                res = build_for_pdf(path, cfg)
                full_text = ' '.join([r['summary'] for r in res['router']])[:4000]
                router_chapters.extend([_enrich_w(r, r.get('summary', ''), path) for r in res['router']])
                content_tags = extract_content_tags(full_text)
                router_docs.append(_enrich_w({
                    'route_id': f'{path.name}::doc', 'title': path.stem,
                    'scope_pages': [1, res['pages']],
                    'summary': summarize_for_router(full_text, cfg.get('MAX_ROUTER_SUMMARY_CHARS', 3000)),
                    'tags': [prof] + content_tags
                }, full_text, path))
                detail.extend([_enrich_w(r, r.get('text_raw', r.get('text', '')), path) for r in res['detail']])
                if prof == 'sop' or 'sop' in path.name.lower():
                    sop_key = re.sub(r'v\d+|\d{8}_\d{6}', '', path.stem, flags=re.I).strip().lower()

        elif path.suffix.lower() == '.txt':
            res = build_for_txt(path, cfg)
            full_text = res['router'][0]['summary'] if res['router'] else ''
            router_chapters.extend([_enrich_w(r, r.get('summary', ''), path) for r in res['router']])
            detail.extend([_enrich_w(r, r.get('text_raw', ''), path) for r in res['detail']])
            router_docs.append(_enrich_w({
                'route_id': f'{path.name}::doc', 'title': path.stem,
                'scope_pages': [1, 1], 'summary': full_text, 'tags': [prof]
            }, full_text, path))

        elif path.suffix.lower() == '.docx':
            res = build_for_docx(path, cfg)
            full_text = ' '.join([r['summary'] for r in res['router']])[:4000]
            router_chapters.extend([_enrich_w(r, r.get('summary', ''), path) for r in res['router']])
            detail.extend([_enrich_w(r, r.get('text_raw', ''), path) for r in res['detail']])
            router_docs.append(_enrich_w({
                'route_id': f'{path.name}::doc', 'title': path.stem,
                'scope_pages': [1, len(res['router'])],
                'summary': summarize_for_router(full_text, cfg.get('MAX_ROUTER_SUMMARY_CHARS', 3000)),
                'tags': [prof]
            }, full_text, path))

        elif path.suffix.lower() == '.csv':
            res = build_for_csv(path, cfg)
            detail.extend([_enrich_w(r, r.get('text_raw', ''), path) for r in res['detail']])
            sample_text = ' '.join([r.get('text_raw', '')[:200] for r in res['detail'][:5]])
            csv_type = res['detail'][0]['metadata'].get('csv_type', 'data') if res['detail'] else 'data'
            router_docs.append(_enrich_w({
                'route_id': f'{path.name}::doc',
                'title': f'CSV Data - {path.stem}',
                'scope_pages': [1, len(res['detail'])],
                'summary': f"CSV dataset with {len(res['detail'])} records (type: {csv_type})",
                'tags': ['csv-data', csv_type]
            }, sample_text, path))

    except Exception as ex:
        logging.exception(f'Worker error {path.name}: {ex}')

    # Quality filter
    min_words = cfg.get('CHUNK_QUALITY_MIN_WORDS', 10)
    detail = [c for c in detail if is_quality_chunk(c.get('text_raw', c.get('text', '')), min_words)]

    return {
        'path': str(path),
        'prof': prof,
        'sop_key': sop_key,
        'router_docs': router_docs,
        'router_chapters': router_chapters,
        'detail': detail,
    }


def main():
    ensure_dirs()
    indexer = IncrementalIndexer(config.OUT_DIR)
    files_by_status = indexer.get_files_to_process(config.SRC_DIR)
    files_to_process = files_by_status["new"] + files_by_status["modified"]

    if not files_to_process:
        learned_file = Path(config.OUT_DIR) / "detail" / "chunks.learned.jsonl"
        if getattr(config, 'ENABLE_CROSS_REFERENCES', True) and _has_unenriched_learned_chunks(learned_file):
            logging.info("No source files changed — enriching unenriched learned chunks only.")
            enrich_learned_chunks()
        else:
            logging.info("No new or modified files to process.")
        return
    
    logging.info(f"Processing {len(files_to_process)} files ({len(files_by_status['new'])} new, {len(files_by_status['modified'])} modified)")
    
    all_router_docs, all_router_chapters, all_detail = [], [], []
    manifest = {"started": now_iso(), "files": [], "out_dir": config.OUT_DIR, "totals": {}}
    sop_buckets = {}

    # Build config dict to pass to worker processes
    cfg = {k: getattr(config, k) for k in dir(config) if not k.startswith('_')}

    # Determine worker count: use FILE_WORKERS from config, or auto-size
    ocr_workers = getattr(config, 'PARALLEL_OCR_WORKERS', 4)
    total_cores = multiprocessing.cpu_count()
    file_workers = getattr(config, 'FILE_WORKERS', 0)
    if not file_workers:
        # Auto: leave enough cores for OCR workers running inside each file worker
        file_workers = max(1, min(8, total_cores // max(1, ocr_workers // 2)))
    logging.info(f"Parallel file processing: {file_workers} workers (OCR workers per file: {ocr_workers}, total cores: {total_cores})")

    # Pre-classify files
    file_tasks = []
    for path in files_to_process:
        if getattr(config, 'ENABLE_AUTO_CLASSIFICATION', False):
            prof = 'auto'
        else:
            prof = classify_profile(path.name)
        file_tasks.append((path, prof))

    # Remove old records for modified files before parallel processing
    for path in files_by_status['modified']:
        old_doc_ids = indexer.get_existing_doc_ids(path)
        if old_doc_ids:
            indexer.remove_old_records(old_doc_ids)
            logging.info(f"Removed old records for modified file: {path.name}")

    # Process files in parallel
    with ProcessPoolExecutor(max_workers=file_workers) as executor:
        futures = {
            executor.submit(_process_file, path, prof, cfg): (path, prof)
            for path, prof in file_tasks
        }
        for future in as_completed(futures):
            path, prof = futures[future]
            logging.info(f"Processing [{prof}] {path}")
            try:
                result = future.result()
                all_router_docs.extend(result['router_docs'])
                all_router_chapters.extend(result['router_chapters'])
                all_detail.extend(result['detail'])
                if result['sop_key']:
                    sop_buckets.setdefault(result['sop_key'], []).append(path)
                manifest['files'].append({'file': path.name, 'profile': prof})
                indexer.mark_processed(path, [path.name])
                logging.info(f"Completed [{prof}] {path.name} — {len(result['detail'])} chunks")
            except Exception as ex:
                logging.exception(f"Worker failed for {path.name}: {ex}")

    # Chunk quality filter (already applied per-file in worker, this catches any stragglers)
    min_words = getattr(config, 'CHUNK_QUALITY_MIN_WORDS', 10)
    before = len(all_detail)
    all_detail = [c for c in all_detail if is_quality_chunk(c.get("text_raw", c.get("text", "")), min_words)]
    if before - len(all_detail):
        logging.info(f"Quality filter removed {before - len(all_detail)} low-quality chunks ({before} → {len(all_detail)})")

    # Cross-file / cross-run deduplication
    dedup_intensity = getattr(config, 'DEDUPLICATION_INTENSITY', 1)
    if getattr(config, 'ENABLE_CROSS_FILE_DEDUP', False) and dedup_intensity > 0:
        # Load existing chunks to seed seen_hashes so re-indexed content is caught
        existing_for_dedup = []
        chunks_file = Path(config.OUT_DIR) / "detail" / "chunks.jsonl"
        if chunks_file.exists():
            with open(chunks_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        existing_for_dedup.append(json.loads(line))
        before = len(all_detail)
        all_detail = deduplicate_cross_file(all_detail, dedup_intensity, existing_for_dedup)
        removed = before - len(all_detail)
        if removed:
            logging.info(f"Cross-file dedup removed {removed} duplicate chunks ({before} → {len(all_detail)})")

    # SOP deduplication
    pruned_ids = set()
    for base, paths in sop_buckets.items():
        if len(paths) >= 2:
            paths = sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)
            keep, others = paths[0], paths[1:]
            try:
                doc_keep = fitz.open(str(keep))
                try:
                    text_keep = " ".join([normalize_text(pg.get_text("text")) for pg in doc_keep.pages[:10]])
                finally:
                    doc_keep.close()
                for o in others:
                    doc_o = fitz.open(str(o))
                    try:
                        text_o = " ".join([normalize_text(pg.get_text("text")) for pg in doc_o.pages[:10]])
                    finally:
                        doc_o.close()
                    if near_duplicate(text_keep, text_o, dedup_intensity):
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

        max_related    = getattr(config, 'MAX_RELATED_CHUNKS', 5)
        min_similarity = getattr(config, 'MIN_SIMILARITY_THRESHOLD', 0.7)

        # Determine whether this is a full rebuild or incremental.
        # Full rebuild: all source files are new — existing_chunks on disk are
        # the previous build's output and must NOT be loaded (they would duplicate
        # all_detail and inflate the corpus by 2x).
        is_full_rebuild = len(files_by_status['modified']) == 0 and \
                          len(files_by_status['unchanged']) == 0

        existing_chunks = []
        if not is_full_rebuild:
            chunks_file = Path(config.OUT_DIR) / "detail" / "chunks.jsonl"
            if chunks_file.exists():
                logging.info("Loading existing chunks for symmetrical cross-referencing...")
                with open(chunks_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            existing_chunks.append(json.loads(line))
                logging.info(f"Loaded {len(existing_chunks)} existing chunks")
        else:
            logging.info("Full rebuild — skipping existing chunks load (all files reprocessed)")

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
                
                enrich_chunk_with_cross_refs(existing_chunk, all_chunks, clusters, term_aliases, max_related, min_similarity)
                if set(existing_chunk.get("related_chunks", [])) & new_chunk_ids:
                    updated_existing += 1
            
            logging.info(f"Updated {updated_existing} existing chunks with backward references")
            
            # Replace all_detail with combined chunks for writing
            all_detail = all_chunks
        
        total_related = sum(len(c.get("related_chunks", [])) for c in all_detail)
        avg_related = total_related / len(all_detail) if all_detail else 0
        logging.info(f"Average related chunks per chunk: {avg_related:.2f}")
        clear_doc_cache()  # release spaCy Doc objects — no longer needed

    # Write records with category-based routing
    detail_dir = Path(config.OUT_DIR) / "detail"

    if getattr(config, 'ENABLE_CROSS_REFERENCES', True) and existing_chunks:
        # Symmetrical cross-refs built — all_detail already contains existing + new.
        # write_chunks_by_category atomically replaces all category files.
        logging.info("Writing all chunks by category (symmetrical cross-refs)...")
        write_chunks_by_category(all_detail, detail_dir)
        indexer.append_new_records({
            "router_docs": all_router_docs,
            "router_chapters": all_router_chapters,
            "detail": []
        })
    elif is_full_rebuild or not (detail_dir / "chunks.jsonl").exists():
        # Full rebuild (or first run) with no existing_chunks loaded — write directly.
        # Never append here: the old chunks.jsonl must be fully replaced.
        logging.info("Writing new chunks by category (full rebuild / first run)...")
        write_chunks_by_category(all_detail, detail_dir)
        indexer.append_new_records({
            "router_docs": all_router_docs,
            "router_chapters": all_router_chapters,
            "detail": []
        })
    else:
        # Incremental run, cross-refs disabled — append new chunks then re-split.
        indexer.append_new_records({
            "router_docs": all_router_docs,
            "router_chapters": all_router_chapters,
            "detail": all_detail
        })
        unified_file = detail_dir / "chunks.jsonl"
        logging.info("Splitting unified index into category files...")
        all_chunks = []
        with open(unified_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    all_chunks.append(json.loads(line))
        write_chunks_by_category(all_chunks, detail_dir)
    
    manifest["completed"] = now_iso()
    with open(Path(config.OUT_DIR, "manifests", "run_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    
    indexer.finalize_run()

    logging.info(f"Combined processing complete. Processed {len(files_to_process)} files with cross-references.")

if __name__ == "__main__":
    multiprocessing.freeze_support()  # no-op on Linux, required for Windows exe packaging
    multiprocessing.set_start_method('spawn', force=True)
    main()

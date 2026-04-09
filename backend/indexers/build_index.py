# -*- coding: utf-8 -*-
"""ChunkyPotato document indexer — builds JSONL knowledge base from source documents."""
import re
import json
import hashlib
import datetime
import logging
import multiprocessing
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed

from backend.config import get_settings
from backend.indexers.incremental_indexer import IncrementalIndexer
from backend.indexers.utils.topic_metadata import add_topic_metadata
from backend.indexers.utils.text_processing import (
    classify_profile, summarize_for_router, normalize_text, deduplicate_cross_file
)
from backend.indexers.utils.nlp_classifier import enrich_record_with_nlp
from backend.indexers.utils.cross_reference import (
    enrich_chunk_with_cross_refs, build_topic_clusters,
    get_term_aliases, auto_generate_aliases, clear_doc_cache
)
from backend.indexers.processors.pdf_processor import build_for_pdf
from backend.indexers.processors.text_processor import build_for_txt, build_for_docx, build_for_pptx
from backend.indexers.processors.csv_processor import build_for_csv
from backend.indexers.utils.quality_assurance import is_quality_chunk
from backend.indexers.utils.pii_sanitizer import sanitize_pii


def sha8(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()[:8]


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _promote_nlp_category(enriched: Dict) -> Dict:
    nlp_cat = enriched.get("metadata", {}).get("nlp_category")
    if nlp_cat:
        enriched["tags"] = [nlp_cat] + [t for t in enriched.get("tags", []) if t != nlp_cat]
    return enriched


def _enrich(record: Dict, text: str, path: Path) -> Dict:
    text = sanitize_pii(text)
    if "text_raw" in record:
        record["text_raw"] = sanitize_pii(record["text_raw"])
    return _promote_nlp_category(enrich_record_with_nlp(add_topic_metadata(record, path), text))


def split_glossary_entries(text: str) -> List[dict]:
    entries = []
    for line in re.split(r"[\r\n]+", text):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z0-9\/\-\(\)\s]{2,40})\s*[-\u2013:]\s*(.+)$", line)
        if m:
            entries.append((m.group(1).strip(), m.group(2).strip()))
    chunks = []
    for term, definition in entries:
        part = f"{term}: {definition}"
        chunks.append({
            "id": f"gloss::{sha8(part)}", "text": part, "element_type": "glossary",
            "metadata": {"doc_id": None, "chapter_id": "glossary", "page_start": None, "page_end": None},
            "raw_markdown": None
        })
    return chunks


def write_chunks_by_category(all_chunks: List[Dict], detail_dir: Path):
    chunks_by_category = defaultdict(list)
    for chunk in all_chunks:
        category = chunk.get('metadata', {}).get('nlp_category', 'general')
        chunks_by_category[category].append(chunk)
    tmp_files = []
    try:
        for category, chunks in chunks_by_category.items():
            final = detail_dir / f"chunks.{category}.jsonl"
            tmp = detail_dir / f"chunks.{category}.jsonl.tmp"
            with open(tmp, 'w', encoding='utf-8') as f:
                for chunk in chunks:
                    f.write(json.dumps(chunk, ensure_ascii=False) + '\n')
            tmp_files.append((tmp, final))
            logging.info(f"Wrote {len(chunks)} chunks to chunks.{category}.jsonl")

        unified_tmp = detail_dir / "chunks.jsonl.tmp"
        unified_final = detail_dir / "chunks.jsonl"
        with open(unified_tmp, 'w', encoding='utf-8') as f:
            for chunk in all_chunks:
                f.write(json.dumps(chunk, ensure_ascii=False) + '\n')
        tmp_files.append((unified_tmp, unified_final))

        for tmp, final in tmp_files:
            tmp.replace(final)
    except Exception:
        for tmp, _ in tmp_files:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
        raise


def main(src_dir: str = None, out_dir: str = None):
    """Run the indexing pipeline.

    Args:
        src_dir: Source documents directory. Defaults to settings.UPLOADS_DIR / "demo".
        out_dir: Output index directory. Defaults to settings.INDEXES_DIR / "demo".
    """
    settings = get_settings()
    if src_dir is None:
        src_dir = str(settings.UPLOADS_DIR / "demo")
    if out_dir is None:
        out_dir = str(settings.INDEXES_DIR / "demo")

    out_path = Path(out_dir)
    for p in [out_path / "detail", out_path / "router", out_path / "logs",
              out_path / "manifests", out_path / "state"]:
        p.mkdir(parents=True, exist_ok=True)

    log_path = out_path / "logs" / "build_index.log"
    logging.basicConfig(filename=str(log_path), level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logging.getLogger().addHandler(console)

    indexer = IncrementalIndexer(out_dir)
    files_by_status = indexer.get_files_to_process(src_dir)
    files_to_process = files_by_status["new"] + files_by_status["modified"]

    if not files_to_process:
        logging.info("No new or modified files to process.")
        return

    logging.info(f"Processing {len(files_to_process)} files "
                 f"({len(files_by_status['new'])} new, {len(files_by_status['modified'])} modified)")

    all_router_docs, all_router_chapters, all_detail = [], [], []
    manifest = {"started": now_iso(), "files": [], "out_dir": out_dir, "totals": {}}

    cfg = {
        "PARA_TARGET_TOKENS": settings.PARA_TARGET_TOKENS,
        "PARA_OVERLAP_TOKENS": settings.PARA_OVERLAP_TOKENS,
        "MIN_CHUNK_TOKENS": settings.MIN_CHUNK_TOKENS,
        "CHUNK_QUALITY_MIN_WORDS": settings.CHUNK_QUALITY_MIN_WORDS,
        "MAX_ROUTER_SUMMARY_CHARS": settings.MAX_ROUTER_SUMMARY_CHARS,
        "MAX_HIERARCHY_DEPTH": settings.MAX_HIERARCHY_DEPTH,
        "DEDUPLICATION_INTENSITY": settings.DEDUPLICATION_INTENSITY,
        "ENABLE_OCR": settings.ENABLE_OCR,
        "OCR_MIN_IMAGE_SIZE": settings.OCR_MIN_IMAGE_SIZE,
        "OCR_LANGUAGES": settings.OCR_LANGUAGES,
        "PARALLEL_OCR_WORKERS": settings.PARALLEL_OCR_WORKERS,
        "TESSERACT_PATH": settings.TESSERACT_PATH,
        "ENABLE_CAMELOT": settings.ENABLE_CAMELOT,
        "ENABLE_AUTO_CLASSIFICATION": settings.ENABLE_AUTO_CLASSIFICATION,
    }

    # Remove old records for modified files
    for path in files_by_status['modified']:
        old_doc_ids = indexer.get_existing_doc_ids(path)
        if old_doc_ids:
            indexer.remove_old_records(old_doc_ids)

    # Process files sequentially (avoid multiprocessing complexity with backend.config imports)
    for path in files_to_process:
        prof = 'auto' if settings.ENABLE_AUTO_CLASSIFICATION else classify_profile(path.name, settings.DOC_PROFILES)
        logging.info(f"Processing [{prof}] {path.name}")
        try:
            result = _process_file_inline(path, prof, cfg)
            all_router_docs.extend(result['router_docs'])
            all_router_chapters.extend(result['router_chapters'])
            all_detail.extend(result['detail'])
            manifest['files'].append({'file': path.name, 'profile': prof})
            indexer.mark_processed(path, [path.name])
            logging.info(f"Completed [{prof}] {path.name} — {len(result['detail'])} chunks")
        except Exception as ex:
            logging.exception(f"Failed for {path.name}: {ex}")

    # Quality filter
    min_words = settings.CHUNK_QUALITY_MIN_WORDS
    before = len(all_detail)
    all_detail = [c for c in all_detail if is_quality_chunk(c.get("text_raw", c.get("text", "")), min_words)]
    if before - len(all_detail):
        logging.info(f"Quality filter removed {before - len(all_detail)} low-quality chunks")

    # Cross-file dedup
    if settings.ENABLE_CROSS_FILE_DEDUP and settings.DEDUPLICATION_INTENSITY > 0:
        existing_for_dedup = []
        chunks_file = out_path / "detail" / "chunks.jsonl"
        if chunks_file.exists():
            with open(chunks_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        existing_for_dedup.append(json.loads(line))
        before = len(all_detail)
        all_detail = deduplicate_cross_file(all_detail, settings.DEDUPLICATION_INTENSITY, existing_for_dedup)
        removed = before - len(all_detail)
        if removed:
            logging.info(f"Cross-file dedup removed {removed} duplicate chunks")

    # Cross-references
    existing_chunks = []
    if settings.ENABLE_CROSS_REFERENCES and all_detail:
        logging.info(f"Building cross-references for {len(all_detail)} chunks...")
        is_full_rebuild = not files_by_status['modified'] and not files_by_status['unchanged']
        if not is_full_rebuild:
            chunks_file = out_path / "detail" / "chunks.jsonl"
            if chunks_file.exists():
                with open(chunks_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            existing_chunks.append(json.loads(line))

        all_chunks = existing_chunks + all_detail
        term_aliases = get_term_aliases()
        if not term_aliases:
            term_aliases = auto_generate_aliases(all_chunks)
        clusters = build_topic_clusters(all_chunks)

        for chunk in all_detail:
            enrich_chunk_with_cross_refs(chunk, all_chunks, clusters, term_aliases,
                                        settings.MAX_RELATED_CHUNKS, settings.MIN_SIMILARITY_THRESHOLD)

        if existing_chunks:
            new_chunk_ids = {c.get("id") for c in all_detail}
            for existing_chunk in existing_chunks:
                enrich_chunk_with_cross_refs(existing_chunk, all_chunks, clusters, term_aliases,
                                            settings.MAX_RELATED_CHUNKS, settings.MIN_SIMILARITY_THRESHOLD)
            all_detail = all_chunks

        clear_doc_cache()

    # Write output
    detail_dir = out_path / "detail"
    write_chunks_by_category(all_detail, detail_dir)
    indexer.append_new_records({
        "router_docs": all_router_docs,
        "router_chapters": all_router_chapters,
        "detail": [],
    })

    manifest["completed"] = now_iso()
    manifest["totals"] = {"chunks": len(all_detail), "files": len(files_to_process)}
    with open(out_path / "manifests" / "run_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    indexer.finalize_run()
    logging.info(f"Indexing complete. {len(files_to_process)} files, {len(all_detail)} chunks.")


def _process_file_inline(path: Path, prof: str, cfg: dict) -> dict:
    """Process a single file in the current process."""
    import fitz

    router_docs, router_chapters, detail = [], [], []

    try:
        if path.suffix.lower() == '.pptx':
            res = build_for_pptx(path, cfg)
            full_text = ' '.join([r['summary'] for r in res['router']])[:5000]
            router_chapters.extend([_enrich(r, r.get('summary', ''), path) for r in res['router']])
            router_docs.append(_enrich({
                'route_id': f'{path.name}::doc', 'title': path.stem,
                'scope_pages': [1, len(res['router'])],
                'summary': summarize_for_router(full_text, cfg.get('MAX_ROUTER_SUMMARY_CHARS', 3000)),
                'tags': [prof]
            }, full_text, path))
            detail.extend([_enrich(r, r.get('text_raw', r.get('text', '')), path) for r in res['detail']])

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
                    detail.append(_enrich(c, c.get('text', ''), path))
            else:
                res = build_for_pdf(path, cfg)
                full_text = ' '.join([r['summary'] for r in res['router']])[:4000]
                router_chapters.extend([_enrich(r, r.get('summary', ''), path) for r in res['router']])
                router_docs.append(_enrich({
                    'route_id': f'{path.name}::doc', 'title': path.stem,
                    'scope_pages': [1, res['pages']],
                    'summary': summarize_for_router(full_text, cfg.get('MAX_ROUTER_SUMMARY_CHARS', 3000)),
                    'tags': [prof]
                }, full_text, path))
                detail.extend([_enrich(r, r.get('text_raw', r.get('text', '')), path) for r in res['detail']])

        elif path.suffix.lower() == '.txt':
            res = build_for_txt(path, cfg)
            full_text = res['router'][0]['summary'] if res['router'] else ''
            router_chapters.extend([_enrich(r, r.get('summary', ''), path) for r in res['router']])
            detail.extend([_enrich(r, r.get('text_raw', ''), path) for r in res['detail']])
            router_docs.append(_enrich({
                'route_id': f'{path.name}::doc', 'title': path.stem,
                'scope_pages': [1, 1], 'summary': full_text, 'tags': [prof]
            }, full_text, path))

        elif path.suffix.lower() == '.docx':
            res = build_for_docx(path, cfg)
            full_text = ' '.join([r['summary'] for r in res['router']])[:4000]
            router_chapters.extend([_enrich(r, r.get('summary', ''), path) for r in res['router']])
            detail.extend([_enrich(r, r.get('text_raw', ''), path) for r in res['detail']])
            router_docs.append(_enrich({
                'route_id': f'{path.name}::doc', 'title': path.stem,
                'scope_pages': [1, len(res['router'])],
                'summary': summarize_for_router(full_text, cfg.get('MAX_ROUTER_SUMMARY_CHARS', 3000)),
                'tags': [prof]
            }, full_text, path))

        elif path.suffix.lower() == '.csv':
            res = build_for_csv(path, cfg)
            detail.extend([_enrich(r, r.get('text_raw', ''), path) for r in res['detail']])
            sample_text = ' '.join([r.get('text_raw', '')[:200] for r in res['detail'][:5]])
            csv_type = res['detail'][0]['metadata'].get('csv_type', 'data') if res['detail'] else 'data'
            router_docs.append(_enrich({
                'route_id': f'{path.name}::doc', 'title': f'CSV Data - {path.stem}',
                'scope_pages': [1, len(res['detail'])],
                'summary': f"CSV dataset with {len(res['detail'])} records (type: {csv_type})",
                'tags': ['csv-data', csv_type]
            }, sample_text, path))

    except Exception as ex:
        logging.exception(f'Error processing {path.name}: {ex}')

    min_words = cfg.get('CHUNK_QUALITY_MIN_WORDS', 10)
    detail = [c for c in detail if is_quality_chunk(c.get('text_raw', c.get('text', '')), min_words)]

    return {
        'router_docs': router_docs,
        'router_chapters': router_chapters,
        'detail': detail,
    }


if __name__ == "__main__":
    main()

# Indexers - Agent Context

## Entry Point
```bash
cd indexers && python build_index.py
```

## Pipeline
```
Documents → Extract → Chunk (512 tokens, 128 overlap) → NLP → Cross-refs → JSON/detail/
```

## Key Components
- `core/incremental_indexer.py` — Hash-based change detection, state in `JSON/state/`
- `processors/pdf_processor.py` — PyMuPDF + pdfplumber tables + OCR
- `processors/text_processor.py` — DOCX, PPTX, TXT
- `processors/csv_processor.py` — CSV + JIRA ticket detection
- `utils/nlp_classifier.py` — spaCy auto-classification (7 categories) + tagging
- `utils/cross_reference.py` — Bidirectional semantic links (≥0.7 similarity)
- `utils/text_processing.py` — Chunking, dedup, sha8, split_with_overlap, should_deduplicate

## Config (config.py)
```python
SRC_DIR = r"C:\path\to\documents"
OUT_DIR = r"C:\path\to\JSON"
ENABLE_AUTO_CLASSIFICATION = True   # NLP vs filename-based
ENABLE_CROSS_REFERENCES = True
PARA_TARGET_TOKENS = 512
MIN_SIMILARITY_THRESHOLD = 0.7
DEDUPLICATION_INTENSITY = 1         # 0=off, 1=exact, 2-9=fuzzy
```

## Dev Standards
- Imports: try package first, fallback to direct (`sys.path.insert`)
- Naming: snake_case functions, PascalCase classes, UPPER_SNAKE_CASE constants
- Error handling: `logging.exception()`, continue processing
- File I/O: stream JSONL line-by-line, always `encoding='utf-8'`, `ensure_ascii=False`
- Shared utils: `sha8`, `split_with_overlap`, `should_deduplicate` live in `utils/text_processing.py`

## Tests
```bash
cd indexers && pytest tests/
```
See `tests/Agents.md` for test details.

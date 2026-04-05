# Indexers - Document Processing System

## Overview

Processes documents into structured JSON chunks with NLP enrichment and cross-references.

## Quick Start

```bash
python build_index.py
```

## Configuration

Edit `config.py`:

```python
SRC_DIR = r"C:\path\to\documents"  # Source files
OUT_DIR = r"C:\path\to\JSON"       # For JSON
# OR
OUT_DIR = r"C:\path\to\MD"         # For Markdown
```

## Structure

```
indexers/
├── build_index.py             # Main indexer
├── config.py                  # Configuration
├── core/                      # Incremental processing
│   └── incremental_indexer.py
├── processors/                # Format handlers
│   ├── pdf_processor.py
│   ├── text_processor.py      # PPTX, DOCX, TXT
│   ├── csv_processor.py
│   └── table_extractor.py
├── utils/                     # NLP and cross-refs
│   ├── nlp_classifier.py      # Auto-categorization
│   ├── cross_reference.py     # Semantic linking
│   ├── ocr_processor.py       # Image text extraction
│   ├── text_processing.py     # Chunking, normalization
│   ├── topic_metadata.py      # Breadcrumbs, hierarchy
│   └── quality_assurance.py   # Validation
├── scripts/                   # Alternative tools
│   └── build_index_md.py      # Markdown output (advanced)
└── tests/                     # Test suites
```

## Features

- **Multi-Format:** PDF, PPTX, DOCX, TXT, CSV
- **NLP-Powered:** Auto-classification, tagging, entity extraction
- **Cross-References:** Bidirectional semantic links
- **Incremental:** Only processes new/modified files
- **Category Routing:** 7 categories (troubleshooting, queries, sop, manual, reference, glossary, general)

## Output Format

```json
{"id":"doc.pdf::ch01::p10::para::abc123","text":"Content...","metadata":{"nlp_category":"troubleshooting"},"tags":["troubleshooting","device"],"related_chunks":["doc2.pdf::ch03::p15::para::def456"]}
```

## Testing

```bash
python tests/test_index_builders.py
```

## Documentation

- **Main README:** `../README.md`
- **Comparison:** `../INDEXER_COMPARISON.md`
- **Architecture:** `../ARCHITECTURE.md`
- **Configuration:** `../Documentation/Configuration.md`
- **Troubleshooting:** `../Documentation/Troubleshooting.md`

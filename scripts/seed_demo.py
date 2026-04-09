#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed demo content — index documents from data/uploads/demo/ into data/indexes/demo/.

Run once on first boot or whenever demo content changes:
    python -m scripts.seed_demo
"""
import sys
import logging
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import get_settings
from backend.database import init_db_sync


def main():
    settings = get_settings()

    # Ensure data directories exist
    demo_uploads = settings.UPLOADS_DIR / "demo"
    demo_index = settings.INDEXES_DIR / "demo"
    demo_uploads.mkdir(parents=True, exist_ok=True)
    for sub in ("detail", "router", "logs", "manifests", "state"):
        (demo_index / sub).mkdir(parents=True, exist_ok=True)

    # Init database
    init_db_sync()
    logging.info("Database initialized.")

    # Check for demo documents
    doc_extensions = ("*.pdf", "*.txt", "*.docx", "*.pptx", "*.csv")
    files = []
    for ext in doc_extensions:
        files.extend(demo_uploads.glob(ext))

    if not files:
        print(f"\nNo demo documents found in {demo_uploads}")
        print("Place your resume, project docs, or other files there, then re-run this script.")
        print(f"\nSupported formats: {', '.join(e.replace('*', '') for e in doc_extensions)}")

        # Create a sample placeholder
        sample = demo_uploads / "README.txt"
        if not sample.exists():
            sample.write_text(
                "ChunkyPotato Demo Content\n"
                "=======================\n\n"
                "Place your resume, project descriptions, and other documents here.\n"
                "Supported formats: PDF, TXT, DOCX, PPTX, CSV\n\n"
                "Then run: python -m scripts.seed_demo\n",
                encoding="utf-8",
            )
            print(f"\nCreated placeholder: {sample}")
        return

    print(f"\nFound {len(files)} document(s) in {demo_uploads}:")
    for f in files:
        print(f"  - {f.name} ({f.stat().st_size / 1024:.1f} KB)")

    print("\nBuilding index...")
    from backend.indexers.build_index import main as build_main
    build_main(src_dir=str(demo_uploads), out_dir=str(demo_index))

    # Verify output
    chunk_count = 0
    detail_dir = demo_index / "detail"
    for f in detail_dir.glob("chunks.*.jsonl"):
        if f.name == "chunks.jsonl":
            continue
        count = sum(1 for line in open(f, encoding="utf-8") if line.strip())
        chunk_count += count
        print(f"  {f.name}: {count} chunks")

    print(f"\nDone. Total: {chunk_count} chunks indexed.")
    print(f"Index location: {demo_index}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    main()

# -*- coding: utf-8 -*-
"""
VPO RAG Indexers Package
"""

from .core.incremental_indexer import IncrementalIndexer
from .utils.topic_metadata import add_topic_metadata
from .utils.text_processing import classify_profile, summarize_for_router
from .processors.pdf_processor import build_for_pdf

__all__ = [
    'IncrementalIndexer',
    'add_topic_metadata', 
    'classify_profile',
    'summarize_for_router',
    'build_for_pdf'
]
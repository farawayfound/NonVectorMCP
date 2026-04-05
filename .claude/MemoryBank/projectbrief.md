# Project Brief

**Name:** vpoRAG
**Description:** A comprehensive Retrieval-Augmented Generation (RAG) system tailored for domain-aware search and knowledge assistance. It bridges local LLM generation (via Ollama) with advanced NLP processing (via spaCy) to provide engineers with context-aware answers.

## Core Objectives
- Centralize scattered engineering knowledge (SOPs, documentation, Jira tickets) into an intelligent, searchable JSONL knowledge base.
- Expose a Model Context Protocol (MCP) server for seamless IDE integration (e.g., Amazon Q in VS Code).
- Provide a fast, standalone API backend (FastAPI) for chat interactions and document queries.
- Automate the ingestion and classification of incoming data, such as Jira CSV exports and user-provided documents.

## Key Features
- **MCP Server:** Tools for `search_kb`, `search_jira`, and `build_index`.
- **RAG Pipeline:** Context retrieval, relevance gating, prompt formatting, and asynchronous streaming.
- **NLP Engine:** Automated tagging, content classification, semantic deduplication, and cross-referencing using `spaCy`.
- **Jira Integration:** Automated CSV drop workflow mapping to a MySQL database.
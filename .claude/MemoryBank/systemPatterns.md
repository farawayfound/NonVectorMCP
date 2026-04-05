# System Patterns

## Architecture & Pipelines

- **RAG Pipeline (`backend/chat/chat_service.py`):**
  - Query formulation -> Term extraction (`_extract_terms`).
  - Retrieval -> Search JSONL KB or indexed user documents (`search_kb`).
  - Gating -> `safeguard.check_relevance` ensures the context is relevant before querying the LLM to prevent hallucinations.
  - Generation -> Asynchronously stream the LLM response via Ollama (`ollama_client.py`).

- **Deduplication Engine (`mcp_server/tools/learn_engine.py`):**
  - A 3-pass system for new knowledge chunks:
    1. **Exact Hash:** Quick rejection of identical text.
    2. **Semantic Scan (Same/Cross Ticket):** Uses spaCy to compare incoming text with learned chunks. Incorporates a tag overlap check to prevent lexical false positives.
    3. **Static KB Scan:** A two-stage pipeline utilizing keyword pre-filtering (fast) before falling back to full spaCy similarity (expensive) to respect time budgets (`_STATIC_KB_TIMEOUT`).

- **NLP & Classification (`indexers/utils/nlp_classifier.py`):**
  - Extensive use of `spaCy` for auto-tagging and classification.
  - Phrases are matched to predefined categories (queries, troubleshooting, sop, reference, manual) using `PhraseMatcher`.
  - Caches 300-dimensional float32 vectors (`cross_reference.py`) to reduce memory footprint compared to full `Doc` objects while maintaining similarity accuracy.

- **Event Logging & State:**
  - Structured JSONL logging for all MCP tool calls (`mcp_access.log`).
  - SQLite for lightweight state management (e.g., invite codes, auth).

- **Jira CSV Drop Workflow:**
  - `inotify` watches a Samba share for new Jira CSV exports.
  - Scripts validate file structure (UTF-8, required columns) before upserting into MySQL (`jira_db`). Erroneous files are isolated in an `invalid/` directory.
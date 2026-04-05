# Tech Context

## Languages & Frameworks
- **Python 3:** Core language for both backend and indexing tasks.
- **FastAPI:** Provides the REST API and streaming endpoints for the chat web interface.
- **Model Context Protocol (MCP):** Server implementation allowing tools to be exposed to IDE clients.

## AI / ML Technologies
- **Ollama:** Powers local LLM generation. Interacted with asynchronously via `httpx`.
- **spaCy (`en_core_web_md`):** Used extensively for:
  - Natural Language Processing (NLP)
  - Named Entity Recognition (NER)
  - Semantic Similarity (Vector Embeddings)
  - Content classification and auto-tagging

## Data Storage
- **JSONL (JSON Lines):** Primary storage format for the vector/knowledge base chunks.
- **MySQL:** Hosts the `jira_db` containing parsed Jira ticket data (`dpstriage`, `postrca`).
- **SQLite:** Used via `aiosqlite` for backend authentication and invite code management.

## Infrastructure & Deployment
- **systemd:** Manages daemonized processes (`vporag-mcp`, `vporag-csv-sync`).
- **Samba:** Exposes network shares for the Jira CSV drop workflow.
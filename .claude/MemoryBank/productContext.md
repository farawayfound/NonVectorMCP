# Product Context

## Why this project exists
Engineering teams often deal with fragmented knowledge bases spanning wikis, PDFs, runbooks, and Jira tickets. Legacy keyword search tools (like PowerShell scripts) often fail to capture semantic meaning or provide actionable answers. 
vpoRAG was created to unify this knowledge into a domain-aware format that can directly answer questions, summarize issues, and link related concepts.

## Problems Solved
- **Information Silos:** Integrates KB documents and Jira tickets (DPSTRIAGE, POSTRCA) into a single querying interface.
- **Context Switching:** By providing an MCP server, engineers can query the KB and Jira directly within VS Code, without breaking their workflow.
- **Knowledge Duplication:** The system's `learn_engine` employs a rigorous 3-pass semantic deduplication process to prevent redundant information from cluttering the knowledge base.
- **Unstructured Data Navigation:** Uses NLP to automatically classify content into logical categories (troubleshooting, queries, sop, glossary) and extract key entities, making the data highly structured and discoverable.

## User Experience
- **IDE Integration:** Engineers configure their Amazon Q VS Code extension with a simple `Bearer vporag-<PID>` token. Tools are auto-discovered during triage sessions.
- **Web/Chat Interface:** Users can engage with the FastAPI chat backend in two modes: "Ask Me Anything" (AMA) using the global demo KB, or by interacting with their own uploaded documents.
- **Zero-Touch Ingestion:** To update Jira data, users simply drop a CSV into a Samba share; the system automatically validates and ingests it.
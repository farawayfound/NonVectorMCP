# ChunkyLink

Self-hostable document RAG system with local LLM inference. No vector database — uses chunk-based search with NLP classification and semantic cross-references.

## Features

- **Ask Me Anything** — RAG-powered Q&A grounded in indexed documents
- **Document Management** — Upload, index, and search your own documents (PDF, DOCX, PPTX, TXT, CSV)
- **Local Inference** — Ollama integration with configurable models
- **Invite System** — Share access via invite codes, no registration required
- **Admin Dashboard** — Manage invite codes, monitor activity, system health
- **Privacy-First** — Built-in PII sanitization, all data stays on your hardware

## Architecture

- **Backend**: FastAPI + SQLite + JSONL knowledge base
- **Frontend**: React + TypeScript (Vite)
- **LLM**: Ollama (any compatible model)
- **NLP**: spaCy for classification, tagging, and semantic linking

## Quick Start

```bash
# Clone and configure
cp .env.example .env
# Edit .env with your settings

# Backend
pip install -r requirements.txt
python -m spacy download en_core_web_md
uvicorn backend.main:app --reload

# Frontend
cd frontend && npm install && npm run dev

# Or use Docker
cd docker && docker compose up
```

## Target Hardware

Designed for modest self-hosting: Ryzen 5 mini PC, 32GB RAM, Ollama local inference.

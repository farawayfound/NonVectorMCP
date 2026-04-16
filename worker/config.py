# -*- coding: utf-8 -*-
"""Worker configuration — loaded from environment variables."""
import os
from pathlib import Path


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# Redis (connects back to the M1 host)
REDIS_URL = _env("REDIS_URL", "redis://localhost:6379/0")

# M1 backend base URL for posting results
M1_BASE_URL = _env("M1_BASE_URL", "http://localhost:8000")

# Shared secret matching the backend's NANOBOT_API_KEY
NANOBOT_API_KEY = _env("NANOBOT_API_KEY", "")

# Ollama (runs locally on nanobot)
# Defaults match production; set OLLAMA_MODEL / OLLAMA_NUM_CTX to match `ollama list` (wrong tag => HTTP 404 on /api/generate).
OLLAMA_BASE_URL = _env("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = _env("OLLAMA_MODEL", "gemma4:26b").strip() or "gemma4:26b"
OLLAMA_TIMEOUT = int(_env("OLLAMA_TIMEOUT", "300"))
OLLAMA_NUM_CTX = int(_env("OLLAMA_NUM_CTX", "32000") or "32000")

# Crawling
MAX_SEARCH_RESULTS = int(_env("MAX_SEARCH_RESULTS", "10"))
MAX_CONCURRENT_SCRAPES = int(_env("MAX_CONCURRENT_SCRAPES", "4"))
SCRAPE_TIMEOUT = int(_env("SCRAPE_TIMEOUT", "30"))
RESPECT_ROBOTS_TXT = _env("RESPECT_ROBOTS_TXT", "true").lower() == "true"

# Worker identity (for Redis consumer groups)
WORKER_ID = _env("WORKER_ID", "nanobot-1")

# Logging
LOG_LEVEL = _env("LOG_LEVEL", "INFO")

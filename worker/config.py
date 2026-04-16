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
# These are *fallback* defaults — the backend Settings (admin_config.json) is
# the single source of truth.  It pushes model/num_ctx to Redis and the worker
# syncs before each job (see main._sync_worker_config).  Env-var overrides here
# only matter when Redis hasn't been seeded yet (first boot / Redis down).
OLLAMA_BASE_URL = _env("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = _env("OLLAMA_MODEL", "gemma4:26b")
OLLAMA_TIMEOUT = int(_env("OLLAMA_TIMEOUT", "300"))
OLLAMA_NUM_CTX = int(_env("OLLAMA_NUM_CTX", "32000"))

# Crawling
MAX_SEARCH_RESULTS = int(_env("MAX_SEARCH_RESULTS", "10"))
MAX_CONCURRENT_SCRAPES = int(_env("MAX_CONCURRENT_SCRAPES", "4"))
SCRAPE_TIMEOUT = int(_env("SCRAPE_TIMEOUT", "30"))
RESPECT_ROBOTS_TXT = _env("RESPECT_ROBOTS_TXT", "true").lower() == "true"

# Worker identity (for Redis consumer groups)
WORKER_ID = _env("WORKER_ID", "nanobot-1")

# Logging
LOG_LEVEL = _env("LOG_LEVEL", "INFO")

# -*- coding: utf-8 -*-
"""ChunkyPotato unified configuration — loaded from environment variables."""
import json
import os
from pathlib import Path
from functools import lru_cache


class Settings:
    """All settings with sensible defaults. Override via environment variables or .env file."""

    def __init__(self):
        self._load_dotenv()

        # ── Paths ──
        self.DATA_DIR = Path(os.getenv("DATA_DIR", "./data")).resolve()
        self.INDEXES_DIR = self.DATA_DIR / "indexes"
        self.UPLOADS_DIR = self.DATA_DIR / "uploads"
        self.DB_PATH = self.DATA_DIR / "db" / "chunkylink.db"
        self.LOG_DIR = self.DATA_DIR / "logs"

        # ── Server ──
        self.HOST = os.getenv("HOST", "0.0.0.0")
        self.PORT = int(os.getenv("PORT", "8000"))
        self.SECRET_KEY = os.getenv("SECRET_KEY", "change-me-to-a-random-string")
        self.CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")]

        # ── Ollama ──
        self.OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e4b")
        self.OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
        self.OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))

        # ── GitHub OAuth ──
        self.GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
        self.GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
        self.GITHUB_ALLOWED_ADMINS = [u.strip() for u in os.getenv("GITHUB_ALLOWED_ADMINS", "").split(",") if u.strip()]
        # Optional: set to frontend dev-server origin (e.g. http://localhost:5173) so
        # that the post-OAuth redirect lands on the Vite dev server instead of the
        # backend.  Leave empty (default) for production same-origin deployments.
        self.FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")

        # ── SMTP (for invite code emails) ──
        self.SMTP_HOST = os.getenv("SMTP_HOST", "")
        self.SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
        self.SMTP_USER = os.getenv("SMTP_USER", "")
        self.SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
        self.SMTP_FROM = os.getenv("SMTP_FROM", "")
        self.SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

        # ── AMA Rate Limiting ──
        self.AMA_RATE_LIMIT = int(os.getenv("AMA_RATE_LIMIT", "2"))
        self.AMA_RATE_WINDOW = int(os.getenv("AMA_RATE_WINDOW", "3600"))

        # ── Demo ──
        self.OWNER_NAME = os.getenv("OWNER_NAME", "the owner")

        # ── Chunking ──
        self.PARA_TARGET_TOKENS = int(os.getenv("PARA_TARGET_TOKENS", "300"))
        self.PARA_OVERLAP_TOKENS = int(os.getenv("PARA_OVERLAP_TOKENS", "50"))
        self.MIN_CHUNK_TOKENS = int(os.getenv("MIN_CHUNK_TOKENS", "30"))
        self.CHUNK_QUALITY_MIN_WORDS = int(os.getenv("CHUNK_QUALITY_MIN_WORDS", "15"))
        self.MAX_ROUTER_SUMMARY_CHARS = int(os.getenv("MAX_ROUTER_SUMMARY_CHARS", "3000"))
        self.MAX_HIERARCHY_DEPTH = int(os.getenv("MAX_HIERARCHY_DEPTH", "6"))

        # ── Deduplication ──
        self.DEDUPLICATION_INTENSITY = int(os.getenv("DEDUPLICATION_INTENSITY", "1"))
        self.ENABLE_CROSS_FILE_DEDUP = os.getenv("ENABLE_CROSS_FILE_DEDUP", "false").lower() == "true"

        # ── NLP & Tagging ──
        self.ENABLE_AUTO_CLASSIFICATION = os.getenv("ENABLE_AUTO_CLASSIFICATION", "true").lower() == "true"
        self.ENABLE_AUTO_TAGGING = os.getenv("ENABLE_AUTO_TAGGING", "true").lower() == "true"
        self.MAX_TAGS_PER_CHUNK = int(os.getenv("MAX_TAGS_PER_CHUNK", "25"))
        self.ENABLE_CAMELOT = os.getenv("ENABLE_CAMELOT", "false").lower() == "true"

        # ── OCR ──
        self.ENABLE_OCR = os.getenv("ENABLE_OCR", "false").lower() == "true"
        self.OCR_MIN_IMAGE_SIZE = (150, 150)
        self.OCR_LANGUAGES = os.getenv("OCR_LANGUAGES", "eng")
        self.PARALLEL_OCR_WORKERS = int(os.getenv("PARALLEL_OCR_WORKERS", "4"))
        self.TESSERACT_PATH = os.getenv("TESSERACT_PATH", None)

        # ── Cross-References ──
        self.ENABLE_CROSS_REFERENCES = os.getenv("ENABLE_CROSS_REFERENCES", "true").lower() == "true"
        self.MAX_RELATED_CHUNKS = int(os.getenv("MAX_RELATED_CHUNKS", "5"))
        self.MIN_SIMILARITY_THRESHOLD = float(os.getenv("MIN_SIMILARITY_THRESHOLD", "0.65"))

        # ── PII Sanitizer ──
        self.PII_INTERNAL_DOMAINS = [d.strip() for d in os.getenv("PII_INTERNAL_DOMAINS", "").split(",") if d.strip()]
        # Index-time redaction (admin-configurable; persisted in admin_config.json)
        self.INDEX_SANITIZE_WORKSPACE = os.getenv("INDEX_SANITIZE_WORKSPACE", "true").lower() == "true"
        self.INDEX_SANITIZE_AMA_KB = os.getenv("INDEX_SANITIZE_AMA_KB", "true").lower() == "true"

        # ── Domain config (empty by default — users populate as needed) ──
        self.TERM_ALIASES: dict[str, list[str]] = {}
        self.CONTENT_TAGS: dict[str, list[str]] = {}
        self.TAG_STOPLIST: set[str] = {
            "address", "report", "client", "issue", "select",
            "your", "home", "usage", "task", "role",
        }

        # ── Suggestions ──
        self.SUGGESTION_MODEL = os.getenv("SUGGESTION_MODEL", "lfm2:24b-a2b")

        # ── Chat ──
        self.RELEVANCE_THRESHOLD = float(os.getenv("RELEVANCE_THRESHOLD", "15.0"))
        self.MAX_CONTEXT_CHUNKS = int(os.getenv("MAX_CONTEXT_CHUNKS", "5"))
        self.MAX_CONTEXT_CHUNK_CHARS = int(os.getenv("MAX_CONTEXT_CHUNK_CHARS", "1200"))
        self.CHAT_MAX_TOKENS = int(os.getenv("CHAT_MAX_TOKENS", "2048"))
        self.CHAT_TEMPERATURE = float(os.getenv("CHAT_TEMPERATURE", "0.3"))
        # Reasoning trace in chat responses. Off by default: for RAG-style Q&A the
        # model's reasoning rarely improves answer quality but adds seconds of
        # prefill+decode before visible text reaches the user. Flip to "true" if
        # you're using a model that specifically benefits from visible thinking.
        self.CHAT_ENABLE_THINKING = os.getenv("CHAT_ENABLE_THINKING", "false").lower() == "true"
        # Quick | Standard | Deep | Exhaustive — Quick reduces per-message CPU vs Standard
        self.CHAT_SEARCH_LEVEL = os.getenv("CHAT_SEARCH_LEVEL", "Quick")
        # 0 = TTL disabled (LRU only); else seconds until identical search cache entries expire
        self.SEARCH_RESULT_CACHE_TTL_SEC = int(os.getenv("SEARCH_RESULT_CACHE_TTL_SEC", "300"))

        # ── Library / Distributed Worker ──
        self.REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.NANOBOT_API_KEY = os.getenv("NANOBOT_API_KEY", "")
        self.LIBRARY_ARTIFACTS_DIR = self.DATA_DIR / "library"

        # ── Runtime admin overrides (mutable; persisted to DATA_DIR/admin_config.json) ──
        # These are set/updated via the admin Configuration tab at runtime.
        # "Default" overrides apply to the Your Documents agent only.
        self.SYSTEM_PROMPT_OVERRIDE: str | None = None
        self.SYSTEM_RULES_OVERRIDE: str | None = None
        # AMA-specific overrides apply to the Ask Me Anything agent only.
        self.AMA_SYSTEM_PROMPT_OVERRIDE: str | None = None
        self.AMA_SYSTEM_RULES_OVERRIDE: str | None = None
        self._load_admin_config()

    def _load_admin_config(self) -> None:
        """Load runtime admin overrides from DATA_DIR/admin_config.json."""
        path = self.DATA_DIR / "admin_config.json"
        if not path.exists():
            return
        try:
            data: dict = json.loads(path.read_text(encoding="utf-8"))
            if data.get("num_ctx"):
                self.OLLAMA_NUM_CTX = int(data["num_ctx"])
            if data.get("system_prompt") is not None:
                self.SYSTEM_PROMPT_OVERRIDE = data["system_prompt"] or None
            if data.get("system_rules") is not None:
                self.SYSTEM_RULES_OVERRIDE = data["system_rules"] or None
            if data.get("suggestion_model"):
                self.SUGGESTION_MODEL = data["suggestion_model"]
            om = data.get("ollama_model")
            if om and str(om).strip():
                self.OLLAMA_MODEL = str(om).strip()
            if data.get("ama_system_prompt") is not None:
                self.AMA_SYSTEM_PROMPT_OVERRIDE = data["ama_system_prompt"] or None
            if data.get("ama_system_rules") is not None:
                self.AMA_SYSTEM_RULES_OVERRIDE = data["ama_system_rules"] or None
            if "index_sanitize_workspace" in data:
                self.INDEX_SANITIZE_WORKSPACE = bool(data["index_sanitize_workspace"])
            if "index_sanitize_ama_kb" in data:
                self.INDEX_SANITIZE_AMA_KB = bool(data["index_sanitize_ama_kb"])
        except Exception:
            pass

    def save_admin_config(self) -> None:
        """Persist current runtime overrides to DATA_DIR/admin_config.json."""
        path = self.DATA_DIR / "admin_config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "num_ctx": self.OLLAMA_NUM_CTX,
            "system_prompt": self.SYSTEM_PROMPT_OVERRIDE or "",
            "system_rules": self.SYSTEM_RULES_OVERRIDE or "",
            "ama_system_prompt": self.AMA_SYSTEM_PROMPT_OVERRIDE or "",
            "ama_system_rules": self.AMA_SYSTEM_RULES_OVERRIDE or "",
            "index_sanitize_workspace": self.INDEX_SANITIZE_WORKSPACE,
            "index_sanitize_ama_kb": self.INDEX_SANITIZE_AMA_KB,
            "suggestion_model": self.SUGGESTION_MODEL,
            "ollama_model": self.OLLAMA_MODEL,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_dotenv(self):
        """Load .env file from project root if it exists."""
        env_file = Path(__file__).resolve().parent.parent / ".env"
        if not env_file.exists():
            return
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key not in os.environ:
                os.environ[key] = value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

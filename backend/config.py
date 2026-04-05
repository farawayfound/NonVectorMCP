# -*- coding: utf-8 -*-
"""ChunkyLink unified configuration — loaded from environment variables."""
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
        self.OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
        self.OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
        self.OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))

        # ── GitHub OAuth ──
        self.GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
        self.GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
        self.GITHUB_ALLOWED_ADMINS = [u.strip() for u in os.getenv("GITHUB_ALLOWED_ADMINS", "").split(",") if u.strip()]

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

        # ── Domain config (empty by default — users populate as needed) ──
        self.TERM_ALIASES: dict[str, list[str]] = {}
        self.CONTENT_TAGS: dict[str, list[str]] = {}
        self.DOC_PROFILES: dict[str, list[str]] = {
            "glossary": ["glossary", "acronym"],
            "manual": ["manual", "playbook", "handbook"],
            "sop": ["sop", "procedure", "how-to"],
            "queries": ["query", "queries", "sql"],
            "reference": ["reference", "guide"],
        }
        self.TAG_STOPLIST: set[str] = {
            "address", "report", "client", "issue", "select",
            "your", "home", "experience", "usage", "task", "role",
        }

        # ── Search ──
        self.DEFAULT_SEARCH_DOMAINS = ["experience", "skills", "education"]

        # ── Chat ──
        self.RELEVANCE_THRESHOLD = float(os.getenv("RELEVANCE_THRESHOLD", "15.0"))
        self.MAX_CONTEXT_CHUNKS = int(os.getenv("MAX_CONTEXT_CHUNKS", "5"))
        self.MAX_CONTEXT_CHUNK_CHARS = int(os.getenv("MAX_CONTEXT_CHUNK_CHARS", "1200"))
        self.CHAT_MAX_TOKENS = int(os.getenv("CHAT_MAX_TOKENS", "2048"))
        self.CHAT_TEMPERATURE = float(os.getenv("CHAT_TEMPERATURE", "0.3"))
        # Quick | Standard | Deep | Exhaustive — Quick reduces per-message CPU vs Standard
        self.CHAT_SEARCH_LEVEL = os.getenv("CHAT_SEARCH_LEVEL", "Quick")

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

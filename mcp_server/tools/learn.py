# -*- coding: utf-8 -*-
"""learn tool — MCP entry point. Delegates all logic to LearnEngine."""
import json, logging, re, subprocess, time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "indexers"))
import config
from logger import log_event
from tools.learn_engine import LearnEngine


class McpLearnEngine(LearnEngine):
    """LearnEngine subclass for the MCP server — server paths, git commit, access log."""

    @property
    def learned_file(self) -> Path:
        return Path(config.JSON_KB_DIR) / "detail" / "chunks.learned.jsonl"

    @property
    def detail_dir(self) -> Path:
        return Path(config.JSON_KB_DIR) / "detail"

    def _extra_meta(self) -> dict:
        return {}   # MCP chunks have no extra source marker

    def _persist(self, chunk: dict) -> dict:
        self.learned_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.learned_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        title       = chunk.get("metadata", {}).get("title", chunk["id"])[:60]
        user_id     = chunk.get("metadata", {}).get("user_id", "unknown")
        ticket_part = chunk.get("metadata", {}).get("ticket_key") or "general"
        commit_hash = self._git_commit(f"learn: {user_id} [{ticket_part}] {title}")
        return {"commit": commit_hash}

    def _git_commit(self, message: str) -> str:
        try:
            subprocess.run(
                ["git", "-C", str(self.detail_dir), "add", "chunks.learned.jsonl"],
                check=True, capture_output=True, timeout=15
            )
            result = subprocess.run(
                ["git", "-C", str(self.detail_dir), "commit", "-m", message],
                check=True, capture_output=True, text=True, timeout=15
            )
            for line in result.stdout.splitlines():
                m = re.search(r'\b([0-9a-f]{7,})\b', line)
                if m:
                    return m.group(1)
        except subprocess.CalledProcessError as e:
            logging.warning(f"learn: git commit failed: {e.stderr}")
        except Exception as e:
            logging.warning(f"learn: git commit error: {e}")
        return ""


_engine = McpLearnEngine()


async def run(
    text: str,
    ticket_key: str = "",
    category: str = "auto",
    tags: list[str] = [],
    title: str = "",
) -> dict:
    """Persist a session-discovered knowledge chunk to the dynamic learned KB.

    Args:
        text:       The discovery — synthesized in the structured format (≥15 words).
        ticket_key: Jira ticket key this discovery relates to (e.g. 'DPS-4821').
        category:   NLP category override. Use 'auto' to let NLP decide.
                    Valid values: auto | troubleshooting | queries | sop |
                                  manual | reference | glossary | general
        tags:       Additional tags to merge with NLP-generated tags.
        title:      Short title for the chunk (auto-derived from text if omitted).
    """
    t0 = time.monotonic()

    try:
        from logger import get_session
        user_id = get_session().get("user_id", "unknown")
    except Exception:
        user_id = "unknown"

    result = _engine.process(text, ticket_key, category, list(tags), title, user_id)

    duration_ms = round((time.monotonic() - t0) * 1000)

    if result["status"] == "ok":
        log_event("learn",
                  chunk_id=result.get("chunk_id"), category=result.get("category"),
                  ticket_key=ticket_key, user_id=user_id,
                  commit=result.get("commit"), tags=result.get("tags"),
                  action=result["status"], duration_ms=duration_ms)
        logging.info(f"learn: {result['status']} {result.get('chunk_id')} "
                     f"({result.get('category')}) commit={result.get('commit')}")
    else:
        log_event("learn_rejected",
                  gate=result.get("gate"), reason=result.get("reason", result["status"]),
                  existing_chunk_id=result.get("existing_chunk_id"),
                  similarity=result.get("similarity"),
                  user_id=user_id, ticket_key=ticket_key, duration_ms=duration_ms)

    result["duration_ms"] = duration_ms
    return result

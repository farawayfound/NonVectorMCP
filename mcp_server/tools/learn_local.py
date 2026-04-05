# -*- coding: utf-8 -*-
"""
learn_local.py — offline entry point. Delegates all logic to LearnEngine.

Usage:
    python mcp_server/tools/learn_local.py \
        --text "Discovery text here" \
        --ticket_key DPS-1234 \
        --category auto \
        --tags "dvr,worldbox" \
        --title "Short title"

Output: JSON to stdout — {"status": "ok"|"rejected"|"duplicate", ...}
"""
import argparse, json, sys
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "indexers"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.learn_engine import LearnEngine


class LocalLearnEngine(LearnEngine):
    """LearnEngine subclass for offline / local mode — no git, marks chunks as source=local."""

    @property
    def learned_file(self) -> Path:
        return _REPO_ROOT / "JSON" / "detail" / "chunks.learned.jsonl"

    @property
    def detail_dir(self) -> Path:
        return _REPO_ROOT / "JSON" / "detail"

    def _extra_meta(self) -> dict:
        return {"source": "local"}   # pending sync to server

    def _persist(self, chunk: dict) -> dict:
        self.learned_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.learned_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        return {}   # no git commit locally — sync handled by Sync-LearnedChunks.ps1


_engine = LocalLearnEngine()


def learn(text: str, ticket_key: str = "", category: str = "auto",
          tags: list[str] = [], title: str = "", user_id: str = "local") -> dict:
    return _engine.process(text, ticket_key, category, list(tags), title, user_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Learn a chunk locally (offline mode)")
    parser.add_argument("--text",       required=True)
    parser.add_argument("--ticket_key", default="")
    parser.add_argument("--category",   default="auto")
    parser.add_argument("--tags",       default="")
    parser.add_argument("--title",      default="")
    parser.add_argument("--user_id",    default="local")
    args = parser.parse_args()

    tag_list = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    result   = learn(args.text, args.ticket_key, args.category, tag_list, args.title, args.user_id)
    print(json.dumps(result, ensure_ascii=False))

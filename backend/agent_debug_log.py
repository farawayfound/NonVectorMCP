# -*- coding: utf-8 -*-
"""Session-scoped NDJSON debug log (debug mode)."""
import json
import os
import time
from pathlib import Path


def _debug_log_paths() -> list[Path]:
    root = Path(__file__).resolve().parent.parent / "debug-bdbe85.log"
    data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
    alt = data_dir / "logs" / "debug-bdbe85.log"
    return [root, alt] if alt.resolve() != root.resolve() else [root]


def agent_debug_log(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict | None = None,
    run_id: str = "pre-fix",
) -> None:
    # region agent log
    try:
        payload = {
            "sessionId": "bdbe85",
            "timestamp": int(time.time() * 1000),
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "runId": run_id,
        }
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        for path in _debug_log_paths():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line)
            except Exception:
                pass
    except Exception:
        pass
    # endregion

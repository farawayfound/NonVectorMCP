# -*- coding: utf-8 -*-
"""Session-scoped NDJSON debug log (debug mode)."""
import json
import time
from pathlib import Path

_LOG_FILE = Path(__file__).resolve().parent.parent / "debug-bdbe85.log"


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
        with open(_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # endregion

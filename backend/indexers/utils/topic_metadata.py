# -*- coding: utf-8 -*-
"""Topic metadata utilities for document classification."""
from pathlib import Path
from typing import Dict


def add_topic_metadata(record: Dict, file_path: Path) -> Dict:
    from backend.config import get_settings
    settings = get_settings()

    path_parts = file_path.parts
    topic = "general"
    for part in path_parts:
        part_lower = part.lower()
        for profile_name, keywords in settings.DOC_PROFILES.items():
            if any(keyword.lower() in part_lower for keyword in keywords):
                topic = profile_name
                break
        if topic != "general":
            break

    if "metadata" in record:
        record["metadata"]["topic"] = topic
        record["metadata"]["file_path"] = str(file_path)

    if "tags" in record:
        if topic not in record["tags"]:
            record["tags"].append(topic)
    else:
        record["tags"] = [topic]

    return record

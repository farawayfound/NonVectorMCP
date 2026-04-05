# -*- coding: utf-8 -*-
"""
Topic metadata utilities for VPO RAG processing
"""

import sys
from pathlib import Path
from typing import Dict

# Add indexers directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

def add_topic_metadata(record: Dict, file_path: Path) -> Dict:
    """Add topic-based metadata for better organization using config profiles"""
    path_parts = file_path.parts
    topic = "general"
    
    # Check path parts against all DOC_PROFILES dynamically
    for part in path_parts:
        part_lower = part.lower()
        for profile_name, keywords in config.DOC_PROFILES.items():
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
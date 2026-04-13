# -*- coding: utf-8 -*-
"""Shared data models for Library research jobs."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    QUEUED = "queued"
    CRAWLING = "crawling"
    SYNTHESIZING = "synthesizing"
    REVIEW = "review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ResearchJob:
    """Serializable job payload pushed onto the queue."""
    job_id: str
    user_id: str
    prompt: str
    max_sources: int = 10
    focus_keywords: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "user_id": self.user_id,
            "prompt": self.prompt,
            "max_sources": self.max_sources,
            "focus_keywords": self.focus_keywords,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResearchJob:
        return cls(
            job_id=data["job_id"],
            user_id=data["user_id"],
            prompt=data["prompt"],
            max_sources=int(data.get("max_sources", 10)),
            focus_keywords=data.get("focus_keywords") or [],
            created_at=data.get("created_at", ""),
        )


@dataclass
class StatusUpdate:
    """Progress update published by the worker."""
    job_id: str
    status: str
    message: str = ""
    progress: float = 0.0
    sources_found: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "message": self.message,
            "progress": self.progress,
            "sources_found": self.sources_found,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StatusUpdate:
        return cls(
            job_id=data["job_id"],
            status=data["status"],
            message=data.get("message", ""),
            progress=float(data.get("progress", 0)),
            sources_found=int(data.get("sources_found", 0)),
            timestamp=data.get("timestamp", ""),
        )


def new_job_id() -> str:
    return uuid.uuid4().hex[:16]

# -*- coding: utf-8 -*-
"""Library feature — isolated tests (no Redis, no running server)."""
from __future__ import annotations

import sqlite3

import pytest

from backend.library.models import ResearchJob, TaskStatus
from backend.library import service as library_service


class _FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[ResearchJob] = []

    async def enqueue(self, job: ResearchJob) -> str:
        self.enqueued.append(job)
        return "0-test"


@pytest.fixture
def library_env(tmp_path, monkeypatch):
    """Fresh DATA_DIR, DB, and test user; clears Settings cache."""
    data = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("NANOBOT_API_KEY", "test-nano-key")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-tests")

    from backend.config import get_settings

    get_settings.cache_clear()

    from backend.database import init_db_sync

    init_db_sync()

    db_path = data / "db" / "chunkylink.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO users (id, github_username, display_name, avatar_url, role) "
        "VALUES (?, ?, ?, ?, ?)",
        ("u-test", None, "Tester", None, "recruiter"),
    )
    conn.commit()
    conn.close()

    fake = _FakeQueue()
    monkeypatch.setattr(library_service, "get_queue", lambda: fake)

    yield {"data": data, "fake": fake}

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_submit_research_enqueues_and_persists(library_env):
    res = await library_service.submit_research(
        user_id="u-test",
        prompt="Compile a short note on graph RAG for integration testing purposes.",
        max_sources=3,
        focus_keywords=["graph", "rag"],
    )
    assert "job_id" in res
    assert res["status"] == TaskStatus.QUEUED

    fake: _FakeQueue = library_env["fake"]
    assert len(fake.enqueued) == 1
    job = fake.enqueued[0]
    assert job.user_id == "u-test"
    assert job.max_sources == 3
    assert "graph" in job.focus_keywords

    rows = await library_service.get_tasks("u-test")
    assert len(rows) == 1
    assert rows[0]["id"] == res["job_id"]
    assert rows[0]["status"] == "queued"


@pytest.mark.asyncio
async def test_receive_result_then_task_in_review(library_env):
    res = await library_service.submit_research(
        user_id="u-test",
        prompt="Local simulation topic about retrieval augmented generation systems.",
    )
    job_id = res["job_id"]

    md = (
        "# Report\n\n"
        "This synthesized markdown meets the minimum word count and structure "
        "for the quality gate used in library approval. "
        "Graph RAG links entities and relations for multi-hop question answering.\n\n"
        "## Sources\n\n- https://example.com\n"
    )
    out = await library_service.receive_result(
        job_id,
        md,
        [{"url": "https://example.com", "title": "Example"}],
        summary="Test summary.",
    )
    assert out["status"] == "review"

    task = await library_service.get_task("u-test", job_id)
    assert task is not None
    assert task["status"] == "review"
    assert task["sources_found"] == 1

    artifact = await library_service.get_task_artifact("u-test", job_id)
    assert artifact is not None
    assert "Graph RAG" in artifact


@pytest.mark.asyncio
async def test_approve_writes_upload_and_marks_approved(library_env):
    pytest.importorskip("spacy")
    res = await library_service.submit_research(
        user_id="u-test",
        prompt="Unique local test topic alpha bravo charlie delta echo foxtrot.",
    )
    job_id = res["job_id"]
    md = (
        "# Unique research doc for approve test\n\n"
        "Paragraph one explains that this content is only for pytest and must not "
        "duplicate existing knowledge base material in unpredictable ways.\n\n"
        "Paragraph two adds retrieval augmented generation and vector embeddings "
        "so the text remains substantive and passes structural quality checks.\n\n"
        "## Sources\n\n- https://example.org/test\n"
    )
    await library_service.receive_result(job_id, md, [{"url": "https://example.org/test", "title": "T"}])

    appr = await library_service.approve_task("u-test", job_id)
    assert appr["status"] == "approved"
    assert appr["filename"].startswith("library_")

    from backend.storage import get_user_upload_dir

    upload_dir = get_user_upload_dir("u-test")
    assert (upload_dir / appr["filename"]).exists()

    task = await library_service.get_task("u-test", job_id)
    assert task["status"] == "approved"

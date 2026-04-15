# -*- coding: utf-8 -*-
"""Chat routes — RAG-powered Q&A endpoints with streaming."""
import asyncio
import json
import logging
import random
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse

from backend.config import get_settings
from backend.auth.middleware import get_current_user
from backend.chat.chat_service import ask_stream_events, ask_with_history_stream_events
from backend.chat.ollama_client import health_check, list_models
from backend.chat.suggestions import load_saved_suggestions
from backend.database import get_db
from backend.storage import get_user_index_dir, get_user_agent_config
from backend.logger import log_event

router = APIRouter()

# ── In-memory IP rate tracking for AMA questions ───────────────────────────────
_ip_question_log: dict[str, list[float]] = {}


def _check_rate_limit(ip: str) -> tuple[int, bool]:
    """Check and record a question for the given IP.

    Returns (questions_used, is_blocked).
    Authenticated users bypass the check — call this only for anonymous users.
    """
    settings = get_settings()
    now = time.time()
    window = settings.AMA_RATE_WINDOW
    limit = settings.AMA_RATE_LIMIT

    timestamps = _ip_question_log.get(ip, [])
    # Prune entries outside the window
    timestamps = [t for t in timestamps if now - t < window]
    count = len(timestamps)

    if count >= limit:
        _ip_question_log[ip] = timestamps
        return count, True

    # Record this question
    timestamps.append(now)
    _ip_question_log[ip] = timestamps
    return count + 1, False

# ── Question templates for dynamic suggestion generation ──────────────────────
_ORG_TEMPLATES = [
    "What was your role at {}?",
    "Tell me about your work at {}",
    "What did you accomplish at {}?",
]
_PRODUCT_TEMPLATES = [
    "What is your experience with {}?",
    "How have you used {} in your work?",
]
_TOPIC_TEMPLATES = [
    "Tell me about your experience with {}",
    "What can you share about {}?",
]
_CATEGORY_QUESTIONS: dict[str, list[str]] = {
    "experience": [
        "Walk me through your career journey",
        "What are your most significant professional accomplishments?",
        "Describe a challenging project you've worked on",
        "What leadership roles have you held?",
        "How do you approach problem-solving in your work?",
    ],
    "skills": [
        "What are your strongest technical skills?",
        "What programming languages and frameworks do you use?",
        "What cloud platforms have you worked with?",
        "What development tools and workflows do you prefer?",
        "How do you stay current with new technologies?",
    ],
    "education": [
        "Tell me about your educational background",
        "What certifications do you hold?",
        "How has your education shaped your career?",
    ],
    "achievements": [
        "What are your biggest career achievements?",
        "Can you share some measurable impacts you've made?",
        "What project are you most proud of?",
    ],
    "general": [
        "Give me an overview of your professional background",
        "What makes you stand out as a candidate?",
        "What are you passionate about in technology?",
        "What kind of team environments do you thrive in?",
        "What are your career goals?",
    ],
}

_PERF_ROLLING_WINDOW = 100


async def _write_perf_log(
    *,
    user_id: str | None,
    user_name: str | None,
    prompt: str,
    mode: str,
    perf: dict,
    user_ttft_ms: int | None,
    thoughts: str | None,
    response: str | None,
) -> None:
    """Persist one chat perf record; trims the rolling window to 100 rows."""
    try:
        db = await get_db()
        try:
            await db.execute(
                """INSERT INTO chat_perf_log
                   (user_id, user_name, prompt, mode,
                    search_ms, prompt_build_ms, ollama_connect_ms,
                    ttft_ms, user_ttft_ms, stream_total_ms,
                    thoughts, response, refused)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user_id,
                    user_name,
                    prompt,
                    mode,
                    perf.get("search_ms"),
                    perf.get("prompt_build_ms"),
                    perf.get("ollama_connect_ms"),
                    perf.get("ttft_ms"),
                    user_ttft_ms,
                    perf.get("stream_total_ms"),
                    thoughts or None,
                    response or None,
                    1 if perf.get("refused") else 0,
                ),
            )
            await db.commit()
            # Rolling window: keep only the latest N rows
            await db.execute(
                f"DELETE FROM chat_perf_log WHERE id NOT IN "
                f"(SELECT id FROM chat_perf_log ORDER BY id DESC LIMIT {_PERF_ROLLING_WINDOW})"
            )
            await db.commit()
        finally:
            await db.close()
    except Exception:
        logging.warning("chat: failed to write perf log", exc_info=True)


@router.get("/quota")
async def chat_quota(request: Request):
    """Return how many AMA questions this IP has remaining."""
    user = await get_current_user(request)
    settings = get_settings()
    if user:
        return {"unlimited": True, "questions_used": 0, "limit": settings.AMA_RATE_LIMIT}

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    timestamps = _ip_question_log.get(client_ip, [])
    timestamps = [t for t in timestamps if now - t < settings.AMA_RATE_WINDOW]
    return {
        "unlimited": False,
        "questions_used": len(timestamps),
        "limit": settings.AMA_RATE_LIMIT,
        "remaining": max(0, settings.AMA_RATE_LIMIT - len(timestamps)),
    }


@router.get("/health")
async def chat_health():
    """Check Ollama connectivity and model availability."""
    status = await health_check()
    models = await list_models()
    settings = get_settings()
    return {
        "ollama": status,
        "configured_model": settings.OLLAMA_MODEL,
        "available_models": [m.get("name", "") for m in models],
    }


@router.post("/ask")
async def chat_ask(request: Request):
    """Ask Me Anything — RAG chat against demo/resume content.

    Body: {"query": "...", "model": null, "level": null}
    Returns: Server-Sent Events stream.
    """
    body = await request.json()
    query = body.get("query", "").strip()
    if not query:
        return {"error": "query is required"}

    user = await get_current_user(request)

    # Rate limit anonymous users
    if not user:
        client_ip = request.client.host if request.client else "unknown"
        questions_used, blocked = _check_rate_limit(client_ip)
        if blocked:
            return JSONResponse(
                {
                    "error": "rate_limited",
                    "message": "You've reached the question limit. Request access to continue.",
                    "questions_used": questions_used,
                    "limit": get_settings().AMA_RATE_LIMIT,
                },
                status_code=429,
            )

    model = body.get("model")
    settings = get_settings()
    level = body.get("level") or settings.CHAT_SEARCH_LEVEL
    kb_dir = settings.INDEXES_DIR / "demo"

    async def event_stream():
        t0 = time.monotonic()
        perf: dict = {}
        thoughts_parts: list[str] = []
        response_parts: list[str] = []
        user_ttft_ms: int | None = None

        try:
            yield ": stream-open\n\n"
            async for ev in ask_stream_events(
                query=query,
                kb_dir=kb_dir,
                mode="ama",
                model=model,
                level=level,
                perf_out=perf,
            ):
                if "thinking" in ev:
                    thoughts_parts.append(ev["thinking"])
                elif "text" in ev:
                    if user_ttft_ms is None:
                        user_ttft_ms = round((time.monotonic() - t0) * 1000)
                    response_parts.append(ev["text"])
                if ev.get("phase") == "search":
                    yield ": kb-search\n\n"
                elif ev.get("phase") == "generate":
                    yield ": llm-generate\n\n"
                yield f"data: {json.dumps(ev)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            logging.warning("chat/ask stream error: %s", exc, exc_info=True)
            err_ev = {"text": f"Sorry, the AI is unavailable right now. ({type(exc).__name__}: {exc})"}
            yield f"data: {json.dumps(err_ev)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            user_id = user["user_id"] if user else None
            user_name = (user.get("display_name") or user.get("github_username")) if user else None
            try:
                asyncio.create_task(_write_perf_log(
                    user_id=user_id,
                    user_name=user_name,
                    prompt=query,
                    mode="ama",
                    perf=perf,
                    user_ttft_ms=user_ttft_ms,
                    thoughts="".join(thoughts_parts) or None,
                    response="".join(response_parts) or None,
                ))
            except Exception:
                logging.warning("chat: could not schedule perf log write", exc_info=True)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/documents")
async def chat_documents(request: Request):
    """Chat against user's own uploaded and indexed documents.

    Requires authentication.
    Body: {"query": "...", "messages": [...], "model": null, "level": null}
    """
    user = await get_current_user(request)
    if not user:
        return {"error": "authentication required"}

    body = await request.json()
    query = body.get("query", "").strip()
    messages = body.get("messages", [])
    model = body.get("model")
    settings = get_settings()
    level = body.get("level") or settings.CHAT_SEARCH_LEVEL

    if not query and not messages:
        return {"error": "query or messages required"}

    kb_dir = get_user_index_dir(user["user_id"])
    if not kb_dir.exists():
        return {"error": "No indexed documents found. Upload and index documents first."}

    # Load per-user agent config (system prompt override). System rules are admin-only.
    agent_cfg = get_user_agent_config(user["user_id"])
    user_prompt = agent_cfg.get("system_prompt") or None

    user_id = user["user_id"]
    user_name = user.get("display_name") or user.get("github_username")
    prompt_text = query or (messages[-1].get("content", "") if messages else "")

    async def event_stream():
        t0 = time.monotonic()
        perf: dict = {}
        thoughts_parts: list[str] = []
        response_parts: list[str] = []
        user_ttft_ms: int | None = None

        try:
            yield ": stream-open\n\n"
            if messages:
                msgs = list(messages)
                if query:
                    msgs.append({"role": "user", "content": query})
                ev_iter = ask_with_history_stream_events(
                    messages=msgs,
                    kb_dir=kb_dir,
                    mode="documents",
                    model=model,
                    level=level,
                    perf_out=perf,
                    user_prompt=user_prompt,
                    user_rules=None,
                )
            else:
                ev_iter = ask_stream_events(
                    query=query,
                    kb_dir=kb_dir,
                    mode="documents",
                    model=model,
                    level=level,
                    perf_out=perf,
                    user_prompt=user_prompt,
                    user_rules=None,
                )
            async for ev in ev_iter:
                if "thinking" in ev:
                    thoughts_parts.append(ev["thinking"])
                elif "text" in ev:
                    if user_ttft_ms is None:
                        user_ttft_ms = round((time.monotonic() - t0) * 1000)
                    response_parts.append(ev["text"])
                if ev.get("phase") == "search":
                    yield ": kb-search\n\n"
                elif ev.get("phase") == "generate":
                    yield ": llm-generate\n\n"
                yield f"data: {json.dumps(ev)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            logging.warning("chat/documents stream error: %s", exc, exc_info=True)
            err_ev = {"text": f"Sorry, the AI is unavailable right now. ({type(exc).__name__}: {exc})"}
            yield f"data: {json.dumps(err_ev)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            try:
                asyncio.create_task(_write_perf_log(
                    user_id=user_id,
                    user_name=user_name,
                    prompt=prompt_text,
                    mode="documents",
                    perf=perf,
                    user_ttft_ms=user_ttft_ms,
                    thoughts="".join(thoughts_parts) or None,
                    response="".join(response_parts) or None,
                ))
            except Exception:
                logging.warning("chat: could not schedule perf log write", exc_info=True)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/search")
async def chat_search(request: Request):
    """Direct search endpoint — returns ranked chunks without LLM generation.

    Body: {"query": "...", "level": "Quick"|..., "page": 1, "page_size": 20}
    """
    user = await get_current_user(request)
    body = await request.json()
    settings = get_settings()
    query = body.get("query", "").strip()
    if not query:
        return {"error": "query is required"}

    level = body.get("level") or settings.CHAT_SEARCH_LEVEL
    page = body.get("page", 1)
    page_size = body.get("page_size", 20)
    scope = body.get("scope", "demo")

    from backend.search.search_kb import search
    from backend.chat.chat_service import _extract_terms

    terms = _extract_terms(query)

    if scope == "documents" and user:
        kb_dir = get_user_index_dir(user["user_id"])
    else:
        kb_dir = settings.INDEXES_DIR / "demo"

    results = await search(
        terms=terms,
        query=query,
        level=level,
        kb_dir=kb_dir,
        page=page,
        page_size=page_size,
    )
    return results


@router.get("/suggestions")
async def chat_suggestions():
    """Return suggested questions — prefers LLM-generated, falls back to templates."""
    settings = get_settings()
    kb_dir = settings.INDEXES_DIR / "demo"

    saved = load_saved_suggestions(kb_dir)
    if saved:
        shuffled = list(saved)
        random.shuffle(shuffled)
        return {"suggestions": shuffled[:15]}

    chunks_file = kb_dir / "detail" / "chunks.jsonl"

    if not chunks_file.exists():
        return {"suggestions": _CATEGORY_QUESTIONS.get("general", [])[:4]}

    chunks = []
    with open(chunks_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    chunks.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not chunks:
        return {"suggestions": _CATEGORY_QUESTIONS.get("general", [])[:4]}

    orgs: set[str] = set()
    products: set[str] = set()
    topics: set[str] = set()
    categories: set[str] = set()

    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        nlp_entities = metadata.get("nlp_entities", {})
        for org in nlp_entities.get("ORG", []):
            if 3 < len(org) < 40:
                orgs.add(org)
        for prod in nlp_entities.get("PRODUCT", []):
            if 2 < len(prod) < 30:
                products.add(prod)
        for phrase in metadata.get("key_phrases", []):
            if 4 < len(phrase) < 40:
                topics.add(phrase)
        cat = metadata.get("nlp_category", "general")
        if cat != "general":
            categories.add(cat)

    questions: list[str] = []

    for org in list(orgs)[:6]:
        questions.append(random.choice(_ORG_TEMPLATES).format(org))
    for prod in list(products)[:4]:
        questions.append(random.choice(_PRODUCT_TEMPLATES).format(prod))
    for topic in list(topics)[:4]:
        questions.append(random.choice(_TOPIC_TEMPLATES).format(topic))

    for cat in categories:
        cat_qs = _CATEGORY_QUESTIONS.get(cat, [])
        questions.extend(cat_qs)
    questions.extend(_CATEGORY_QUESTIONS.get("general", []))

    seen: set[str] = set()
    unique: list[str] = []
    for q in questions:
        if q not in seen:
            seen.add(q)
            unique.append(q)

    random.shuffle(unique)
    return {"suggestions": unique[:15]}

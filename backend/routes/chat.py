# -*- coding: utf-8 -*-
"""Chat routes — RAG-powered Q&A endpoints with streaming."""
import json
import random
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.config import get_settings
from backend.auth.middleware import get_current_user
from backend.chat.chat_service import ask, ask_with_history
from backend.chat.ollama_client import health_check, list_models
from backend.storage import get_user_index_dir
from backend.logger import log_event

router = APIRouter()

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

    Body: {"query": "...", "model": null, "level": "Standard"}
    Returns: Server-Sent Events stream of text chunks.
    """
    body = await request.json()
    query = body.get("query", "").strip()
    if not query:
        return {"error": "query is required"}

    model = body.get("model")
    level = body.get("level", "Standard")

    settings = get_settings()
    kb_dir = settings.INDEXES_DIR / "demo"

    stream = await ask(
        query=query,
        kb_dir=kb_dir,
        mode="ama",
        model=model,
        level=level,
        stream=True,
    )

    async def event_stream():
        async for chunk in stream:
            yield f"data: {json.dumps({'text': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/documents")
async def chat_documents(request: Request):
    """Chat against user's own uploaded and indexed documents.

    Requires authentication.
    Body: {"query": "...", "messages": [...], "model": null, "level": "Standard"}
    """
    user = await get_current_user(request)
    if not user:
        return {"error": "authentication required"}

    body = await request.json()
    query = body.get("query", "").strip()
    messages = body.get("messages", [])
    model = body.get("model")
    level = body.get("level", "Standard")

    if not query and not messages:
        return {"error": "query or messages required"}

    kb_dir = get_user_index_dir(user["user_id"])
    if not kb_dir.exists():
        return {"error": "No indexed documents found. Upload and index documents first."}

    if messages:
        # Multi-turn conversation
        if query:
            messages.append({"role": "user", "content": query})
        stream = await ask_with_history(
            messages=messages,
            kb_dir=kb_dir,
            mode="documents",
            model=model,
            level=level,
        )
    else:
        stream = await ask(
            query=query,
            kb_dir=kb_dir,
            mode="documents",
            model=model,
            level=level,
            stream=True,
        )

    async def event_stream():
        async for chunk in stream:
            yield f"data: {json.dumps({'text': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/search")
async def chat_search(request: Request):
    """Direct search endpoint — returns ranked chunks without LLM generation.

    Body: {"query": "...", "level": "Standard", "page": 1, "page_size": 20}
    """
    user = await get_current_user(request)
    body = await request.json()
    query = body.get("query", "").strip()
    if not query:
        return {"error": "query is required"}

    level = body.get("level", "Standard")
    page = body.get("page", 1)
    page_size = body.get("page_size", 20)
    scope = body.get("scope", "demo")

    from backend.search.search_kb import search
    from backend.chat.chat_service import _extract_terms

    terms = _extract_terms(query)

    if scope == "documents" and user:
        kb_dir = get_user_index_dir(user["user_id"])
    else:
        kb_dir = get_settings().INDEXES_DIR / "demo"

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
    """Generate dynamic suggested questions from the demo KB index.

    Extracts entities, tags, and categories from indexed chunks
    and builds a pool of relevant questions.
    """
    settings = get_settings()
    kb_dir = settings.INDEXES_DIR / "demo"
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

    # Extract entities and categories from indexed chunks
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

    # Generate questions from extracted entities
    for org in list(orgs)[:6]:
        questions.append(random.choice(_ORG_TEMPLATES).format(org))
    for prod in list(products)[:4]:
        questions.append(random.choice(_PRODUCT_TEMPLATES).format(prod))
    for topic in list(topics)[:4]:
        questions.append(random.choice(_TOPIC_TEMPLATES).format(topic))

    # Add category-based questions
    for cat in categories:
        cat_qs = _CATEGORY_QUESTIONS.get(cat, [])
        questions.extend(cat_qs)
    questions.extend(_CATEGORY_QUESTIONS.get("general", []))

    # Deduplicate and shuffle
    seen: set[str] = set()
    unique: list[str] = []
    for q in questions:
        if q not in seen:
            seen.add(q)
            unique.append(q)

    random.shuffle(unique)
    return {"suggestions": unique[:15]}

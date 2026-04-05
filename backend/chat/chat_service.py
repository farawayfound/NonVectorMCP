# -*- coding: utf-8 -*-
"""RAG pipeline: query -> search -> relevance check -> context -> Ollama -> stream."""
import logging
import re
from pathlib import Path
from typing import Any, AsyncIterator

from backend.config import get_settings
from backend.search.search_kb import search
from backend.chat.ollama_client import generate_stream, chat_stream
from backend.chat.safeguard import (
    get_system_prompt, format_context, build_prompt, check_relevance,
)
from backend.logger import log_event


def _extract_terms(query: str) -> list[str]:
    """Extract search terms from a natural language query."""
    stop = {
        "what", "is", "are", "how", "do", "does", "can", "could", "would",
        "the", "a", "an", "in", "on", "at", "to", "for", "of", "with",
        "and", "or", "but", "not", "this", "that", "my", "your", "about",
        "from", "by", "as", "it", "me", "you", "we", "they", "i", "be",
    }
    words = re.findall(r'[a-zA-Z0-9][\w\-]*', query.lower())
    terms = [w for w in words if w not in stop and len(w) >= 2]
    return terms or words[:5]


def _effective_level(level: str | None) -> str:
    settings = get_settings()
    return level if level is not None else settings.CHAT_SEARCH_LEVEL


async def ask_stream_events(
    query: str,
    kb_dir: str | Path | None = None,
    mode: str = "ama",
    model: str | None = None,
    level: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """RAG pipeline yielding SSE-friendly dicts: {"phase": "search"|"generate"}, {"text": "..."}."""
    settings = get_settings()
    if kb_dir is None:
        kb_dir = settings.INDEXES_DIR / "demo"
    kb_dir = Path(kb_dir)
    eff_level = _effective_level(level)

    terms = _extract_terms(query)
    log_event("chat_ask", query=query, mode=mode, terms=terms)

    yield {"phase": "search"}

    search_results = await search(
        terms=terms,
        query=query,
        level=eff_level,
        kb_dir=kb_dir,
        max_results=20,
    )

    should_proceed, refusal = check_relevance(search_results)
    if not should_proceed:
        log_event("chat_refused", query=query, reason="low_relevance")
        yield {"text": refusal}
        return

    yield {"phase": "generate"}

    system = get_system_prompt(mode)
    context = format_context(search_results.get("results", []))
    prompt = build_prompt(query, context)

    log_event("chat_generate", query=query, context_chunks=len(search_results.get("results", [])),
              top_score=search_results["results"][0].get("RelevanceScore", 0) if search_results.get("results") else 0)

    temperature = settings.CHAT_TEMPERATURE
    max_tokens = settings.CHAT_MAX_TOKENS
    async for chunk in generate_stream(
        prompt=prompt, system=system, model=model,
        temperature=temperature, max_tokens=max_tokens,
    ):
        yield {"text": chunk}


async def ask(
    query: str,
    kb_dir: str | Path | None = None,
    mode: str = "ama",
    model: str | None = None,
    level: str | None = None,
    stream: bool = True,
) -> AsyncIterator[str] | str:
    """Full RAG pipeline: search -> gate -> generate.

    Args:
        query: User's question.
        kb_dir: Knowledge base directory. Defaults to demo index.
        mode: 'ama' for Ask Me Anything, 'documents' for user docs.
        model: Ollama model override.
        level: Search depth level (defaults to CHAT_SEARCH_LEVEL).
        stream: If True, returns async iterator of text chunks.

    Returns:
        Async iterator of text chunks (stream=True) or complete string.
    """
    if not stream:
        parts: list[str] = []
        async for ev in ask_stream_events(
            query=query, kb_dir=kb_dir, mode=mode, model=model, level=level,
        ):
            if "text" in ev:
                parts.append(ev["text"])
        return "".join(parts)

    async def _text_only() -> AsyncIterator[str]:
        async for ev in ask_stream_events(
            query=query, kb_dir=kb_dir, mode=mode, model=model, level=level,
        ):
            if "text" in ev:
                yield ev["text"]

    return _text_only()


async def ask_with_history_stream_events(
    messages: list[dict],
    kb_dir: str | Path | None = None,
    mode: str = "ama",
    model: str | None = None,
    level: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """RAG with history; yields phase events and text chunks (same shape as ask_stream_events)."""
    settings = get_settings()
    if kb_dir is None:
        kb_dir = settings.INDEXES_DIR / "demo"
    kb_dir = Path(kb_dir)
    eff_level = _effective_level(level)

    query = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            query = msg.get("content", "")
            break
    if not query:
        yield {"text": "Please ask a question."}
        return

    terms = _extract_terms(query)

    yield {"phase": "search"}

    search_results = await search(
        terms=terms,
        query=query,
        kb_dir=kb_dir,
        level=eff_level,
        max_results=20,
    )

    should_proceed, refusal = check_relevance(search_results)
    if not should_proceed:
        yield {"text": refusal}
        return

    yield {"phase": "generate"}

    system = get_system_prompt(mode)
    context = format_context(search_results.get("results", []))

    chat_messages = [{"role": "system", "content": system}]
    if context:
        chat_messages.append({
            "role": "system",
            "content": f"Relevant context from indexed documents:\n\n{context}",
        })

    for msg in messages[-20:]:
        if msg.get("role") in ("user", "assistant"):
            chat_messages.append({"role": msg["role"], "content": msg["content"]})

    settings = get_settings()
    async for chunk in chat_stream(
        messages=chat_messages, model=model,
        temperature=settings.CHAT_TEMPERATURE, max_tokens=settings.CHAT_MAX_TOKENS,
    ):
        yield {"text": chunk}


async def ask_with_history(
    messages: list[dict],
    kb_dir: str | Path | None = None,
    mode: str = "ama",
    model: str | None = None,
    level: str | None = None,
) -> AsyncIterator[str]:
    """RAG pipeline with conversation history support.

    The last user message is used as the search query.
    Context is injected as a system message.
    """

    async def _text_only() -> AsyncIterator[str]:
        async for ev in ask_with_history_stream_events(
            messages=messages, kb_dir=kb_dir, mode=mode, model=model, level=level,
        ):
            if "text" in ev:
                yield ev["text"]

    return _text_only()

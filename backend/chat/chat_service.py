# -*- coding: utf-8 -*-
"""RAG pipeline: query -> search -> relevance check -> context -> Ollama -> stream."""
import logging
import re
import time
from pathlib import Path
from typing import AsyncIterator

from backend.agent_debug_log import agent_debug_log
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


async def ask(
    query: str,
    kb_dir: str | Path | None = None,
    mode: str = "ama",
    model: str | None = None,
    level: str = "Standard",
    stream: bool = True,
) -> AsyncIterator[str] | str:
    """Full RAG pipeline: search -> gate -> generate.

    Args:
        query: User's question.
        kb_dir: Knowledge base directory. Defaults to demo index.
        mode: 'ama' for Ask Me Anything, 'documents' for user docs.
        model: Ollama model override.
        level: Search depth level.
        stream: If True, returns async iterator of text chunks.

    Returns:
        Async iterator of text chunks (stream=True) or complete string.
    """
    settings = get_settings()
    if kb_dir is None:
        kb_dir = settings.INDEXES_DIR / "demo"
    kb_dir = Path(kb_dir)

    terms = _extract_terms(query)
    log_event("chat_ask", query=query, mode=mode, terms=terms)

    # region agent log
    _t_ask0 = time.monotonic()
    agent_debug_log("H1", "chat_service.py:ask", "ask_start", {"kb": kb_dir.name})
    # endregion

    # Search
    search_results = await search(
        terms=terms,
        query=query,
        level=level,
        kb_dir=kb_dir,
        max_results=20,
    )

    # region agent log
    agent_debug_log("H1", "chat_service.py:ask", "after_search", {
        "elapsed_ms": round((time.monotonic() - _t_ask0) * 1000),
        "n_results": len(search_results.get("results", [])),
        "level": level,
    })
    # endregion

    # Relevance gate
    should_proceed, refusal = check_relevance(search_results)
    if not should_proceed:
        log_event("chat_refused", query=query, reason="low_relevance")
        if stream:
            async def _refuse():
                yield refusal
            return _refuse()
        return refusal

    # Build prompt
    system = get_system_prompt(mode)
    context = format_context(search_results.get("results", []))
    prompt = build_prompt(query, context)

    log_event("chat_generate", query=query, context_chunks=len(search_results.get("results", [])),
              top_score=search_results["results"][0].get("RelevanceScore", 0) if search_results.get("results") else 0)

    # region agent log
    agent_debug_log("H2", "chat_service.py:ask", "before_llm_stream", {
        "elapsed_since_ask_ms": round((time.monotonic() - _t_ask0) * 1000),
        "prompt_chars": len(prompt),
        "system_chars": len(system),
        "num_ctx": settings.OLLAMA_NUM_CTX,
    })
    # endregion

    # Generate
    temperature = settings.CHAT_TEMPERATURE
    max_tokens = settings.CHAT_MAX_TOKENS
    if stream:
        return generate_stream(prompt=prompt, system=system, model=model,
                               temperature=temperature, max_tokens=max_tokens)
    else:
        parts = []
        async for chunk in generate_stream(prompt=prompt, system=system, model=model,
                                           temperature=temperature, max_tokens=max_tokens):
            parts.append(chunk)
        return "".join(parts)


async def ask_with_history(
    messages: list[dict],
    kb_dir: str | Path | None = None,
    mode: str = "ama",
    model: str | None = None,
    level: str = "Standard",
) -> AsyncIterator[str]:
    """RAG pipeline with conversation history support.

    The last user message is used as the search query.
    Context is injected as a system message.
    """
    settings = get_settings()
    if kb_dir is None:
        kb_dir = settings.INDEXES_DIR / "demo"
    kb_dir = Path(kb_dir)

    # Extract query from last user message
    query = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            query = msg.get("content", "")
            break
    if not query:
        async def _empty():
            yield "Please ask a question."
        return _empty()

    terms = _extract_terms(query)

    # region agent log
    _t_hist0 = time.monotonic()
    agent_debug_log("H1", "chat_service.py:ask_with_history", "ask_start", {"kb": kb_dir.name})
    # endregion

    search_results = await search(
        terms=terms,
        query=query,
        kb_dir=kb_dir,
        level=level,
        max_results=20,
    )

    # region agent log
    agent_debug_log("H1", "chat_service.py:ask_with_history", "after_search", {
        "elapsed_ms": round((time.monotonic() - _t_hist0) * 1000),
        "n_results": len(search_results.get("results", [])),
        "level": level,
    })
    # endregion

    should_proceed, refusal = check_relevance(search_results)
    if not should_proceed:
        async def _refuse():
            yield refusal
        return _refuse()

    # Build messages with context
    system = get_system_prompt(mode)
    context = format_context(search_results.get("results", []))

    chat_messages = [{"role": "system", "content": system}]
    if context:
        chat_messages.append({
            "role": "system",
            "content": f"Relevant context from indexed documents:\n\n{context}",
        })

    # Include conversation history (limit to last 10 exchanges)
    for msg in messages[-20:]:
        if msg.get("role") in ("user", "assistant"):
            chat_messages.append({"role": msg["role"], "content": msg["content"]})

    settings = get_settings()
    # region agent log
    _msg_chars = sum(len(m.get("content") or "") for m in chat_messages)
    agent_debug_log("H2", "chat_service.py:ask_with_history", "before_llm_stream", {
        "elapsed_since_ask_ms": round((time.monotonic() - _t_hist0) * 1000),
        "chat_messages_chars": _msg_chars,
        "num_ctx": settings.OLLAMA_NUM_CTX,
    })
    # endregion
    return chat_stream(messages=chat_messages, model=model,
                       temperature=settings.CHAT_TEMPERATURE, max_tokens=settings.CHAT_MAX_TOKENS)

# -*- coding: utf-8 -*-
"""Chat safeguarding — system prompts, relevance gating, refusal logic."""
from backend.config import get_settings


def get_system_prompt(mode: str = "ama") -> str:
    """Return the system prompt for a given chat mode.

    Modes:
        ama       — Ask Me Anything (demo/resume content)
        documents — User's own uploaded documents
    """
    settings = get_settings()
    owner = settings.OWNER_NAME or "the document author"

    if mode == "ama":
        return (
            f"You are a helpful assistant answering questions about {owner}'s "
            f"professional background, skills, and projects. You have access to "
            f"indexed documents containing {owner}'s resume, project descriptions, "
            f"and technical write-ups.\n\n"
            f"RULES:\n"
            f"1. Only answer based on the provided context. Do not make up information.\n"
            f"2. If the context does not contain enough information to answer, say so clearly.\n"
            f"3. Be concise and professional.\n"
            f"4. When referencing specific projects or experiences, cite the source document.\n"
            f"5. Do not discuss topics unrelated to {owner}'s professional profile.\n"
        )
    else:
        return (
            "You are a helpful assistant answering questions based on the user's "
            "uploaded documents. You have access to indexed content from their files.\n\n"
            "RULES:\n"
            "1. Only answer based on the provided context. Do not make up information.\n"
            "2. If the context does not contain enough information to answer, say so clearly.\n"
            "3. Be concise and direct.\n"
            "4. Reference specific documents or sections when possible.\n"
        )


def format_context(results: list[dict], max_chunks: int | None = None) -> str:
    """Format search results into a context block for the LLM prompt.

    Each chunk is truncated to MAX_CONTEXT_CHUNK_CHARS to keep prompt_eval
    fast on CPU inference.  Total context is bounded by both max_chunks and
    per-chunk truncation.
    """
    if not results:
        return ""

    settings = get_settings()
    if max_chunks is None:
        max_chunks = settings.MAX_CONTEXT_CHUNKS
    max_chars = settings.MAX_CONTEXT_CHUNK_CHARS

    parts = []
    for i, chunk in enumerate(results[:max_chunks], 1):
        text = chunk.get("text", "").strip()
        if len(text) > max_chars:
            # Truncate on a word boundary when possible
            cut = text[:max_chars].rfind(" ")
            text = text[: cut if cut > max_chars // 2 else max_chars] + " …"
        doc_id = chunk.get("metadata", {}).get("doc_id", "unknown")
        score = chunk.get("RelevanceScore", 0)
        parts.append(f"[Source {i} | {doc_id} | score={score}]\n{text}")

    return "\n\n---\n\n".join(parts)


def build_prompt(query: str, context: str) -> str:
    """Build the user prompt with context and question."""
    if not context:
        return query

    return (
        f"Context from indexed documents:\n\n"
        f"{context}\n\n"
        f"---\n\n"
        f"Question: {query}\n\n"
        f"Answer based only on the context above."
    )


def check_relevance(search_results: dict) -> tuple[bool, str]:
    """Check if search results are relevant enough to proceed with generation.

    Returns (should_proceed, refusal_message).
    """
    threshold = get_settings().RELEVANCE_THRESHOLD
    results = search_results.get("results", [])
    if not results:
        return False, "I couldn't find any relevant information in the indexed documents to answer your question."

    top_score = max(r.get("RelevanceScore", 0) for r in results)
    if top_score < threshold:
        return False, (
            "I found some documents but they don't seem closely related to your question. "
            "Could you rephrase or ask about a topic covered in the indexed documents?"
        )

    return True, ""

# -*- coding: utf-8 -*-
"""System prompts and templates for the synthesis pipeline."""

SYNTHESIS_SYSTEM = """\
You are a research assistant that produces well-structured Markdown reports.
Given a set of web sources and their extracted content, synthesize the
information into a single, comprehensive, factual document.

Rules:
- Write in clear, professional prose.
- Use Markdown headings (##, ###) to organise sections.
- Include inline citations like [Source 1], [Source 2] referencing the
  numbered source list provided.
- If sources conflict, note the discrepancy.
- Do NOT fabricate information beyond what the sources contain.
- End with a "## Sources" section listing each URL with its title.
"""

SYNTHESIS_USER_TEMPLATE = """\
# Research Topic
{prompt}

# Sources
{sources_block}

---
Synthesize the above sources into a comprehensive Markdown report on the topic.
Include a "## Sources" section at the end with numbered references.
"""

QUERY_GENERATION_SYSTEM = """\
You are a search-query generator. Given a research topic, output 3-5 concise
DuckDuckGo search queries (one per line, no numbering, no explanation).
Focus on different angles of the topic to get diverse results.
"""


def build_synthesis_prompt(prompt: str, sources: list[dict]) -> str:
    """Build the user message for synthesis from scraped source data."""
    blocks: list[str] = []
    for i, src in enumerate(sources, 1):
        title = src.get("title", "Untitled")
        url = src.get("url", "")
        content = src.get("content", "")
        # Truncate very long pages to keep within context window
        if len(content) > 6000:
            content = content[:6000] + "\n[...truncated]"
        blocks.append(f"### [Source {i}] {title}\nURL: {url}\n\n{content}")

    sources_block = "\n\n".join(blocks)
    return SYNTHESIS_USER_TEMPLATE.format(prompt=prompt, sources_block=sources_block)

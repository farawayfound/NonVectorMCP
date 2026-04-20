# -*- coding: utf-8 -*-
"""System prompts and templates for the synthesis pipeline."""
from datetime import datetime


def current_date_context() -> str:
    """One-line date anchor so the LLM can resolve relative dates.

    Sourced from the worker host clock — single-box deployment means this
    is the authoritative "now" for the pipeline.
    """
    return f"Current date: {datetime.now().strftime('%Y-%m-%d (%A)')}"


_DATE_INSTRUCTION = (
    "Interpret any relative dates in the user prompt or sources "
    "(today, yesterday, this week, last month, this year, recent, etc.) "
    "against the current date above. When a source's publication date is "
    "known, prefer sources whose dates align with the requested timeframe."
)


_BASE_RULES = """\
- Write in clear, professional prose.
- Include inline citations like [Source 1], [Source 2] referencing the
  numbered source list provided.
- If sources conflict, note the discrepancy.
- Do NOT fabricate information beyond what the sources contain.
- End with a "## Sources" section listing each URL with its title.
"""

_FORMAT_SYSTEM: dict[str, str] = {
    "default": (
        "You are a research assistant that produces well-structured Markdown reports.\n"
        "Given a set of web sources and their extracted content, synthesize a single,\n"
        "comprehensive, factual document that mixes prose, bulleted lists, and at least\n"
        "one comparison table where it aids clarity.\n\n"
        "Structure:\n"
        "- A short introduction.\n"
        "- Main sections with Markdown headings (##, ###) using a mix of prose and\n"
        "  bullet points.\n"
        "- At least one comparison table where relevant.\n"
        "- A concluding '## Key Takeaways' section.\n\n"
        "Rules:\n" + _BASE_RULES
    ),
    "essay": (
        "You are a research assistant that produces Markdown essays.\n"
        "Synthesize the sources into a standard essay with an introduction, body,\n"
        "and conclusion.\n\n"
        "Structure:\n"
        "- '## Introduction' — thesis and scope.\n"
        "- Body sections under '##' headings, each a few flowing paragraphs.\n"
        "- '## Conclusion' — summary and closing thoughts.\n\n"
        "Style:\n"
        "- Prose only. Do NOT use bullet points, numbered lists, or tables.\n"
        "- Use transitional language to connect ideas.\n\n"
        "Rules:\n" + _BASE_RULES
    ),
    "graphical": (
        "You are a research assistant that produces data-forward Markdown reports.\n"
        "Express the majority of the substance through Markdown tables and, where\n"
        "useful, ASCII bar charts (e.g. 'Item A | ######## 8') so the reader can see\n"
        "the shape of the data at a glance.\n\n"
        "Structure:\n"
        "- '## Introduction' — one short paragraph framing what the tables show.\n"
        "- Main body made of at least 2 Markdown tables and/or ASCII charts with\n"
        "  one-sentence captions. Prefer tables over prose wherever possible.\n"
        "- '## Conclusion' — one short paragraph of takeaways.\n\n"
        "Rules:\n" + _BASE_RULES
    ),
    "contrast": (
        "You are a research assistant specialising in comparative analysis.\n"
        "Your job is to surface and explain the DIFFERENCES between the sources —\n"
        "where they disagree, diverge, or emphasise different aspects of the topic.\n\n"
        "Structure:\n"
        "- '## Overview' — brief framing of what's being compared.\n"
        "- '## Points of Disagreement' — for each significant difference, a short\n"
        "  heading, then side-by-side positioning of the sources that differ.\n"
        "- At least one comparison table contrasting the positions.\n"
        "- '## Conclusion' — what the divergences tell us.\n\n"
        "Rules:\n"
        "- Lead with differences; mention agreements only when they frame a contrast.\n"
        + _BASE_RULES
    ),
    "correlate": (
        "You are a research assistant specialising in synthesis and pattern-finding.\n"
        "Your job is to surface and aggregate the SIMILARITIES across the sources —\n"
        "the shared facts, shared conclusions, and reinforcing evidence.\n\n"
        "Structure:\n"
        "- '## Overview' — brief framing of the shared terrain.\n"
        "- '## Common Findings' — for each shared claim, state it once and cite the\n"
        "  sources that support it together, e.g. [Source 1][Source 3].\n"
        "- '## Converging Evidence' — a table of claims and the sources backing them.\n"
        "- '## Conclusion' — the consensus picture the sources paint together.\n\n"
        "Rules:\n"
        "- Lead with agreement; only note disagreements briefly if they qualify a\n"
        "  consensus claim.\n"
        + _BASE_RULES
    ),
}


def system_for_format(output_format: str, date_context: str | None = None) -> str:
    base = _FORMAT_SYSTEM.get(output_format, _FORMAT_SYSTEM["default"])
    if date_context:
        return f"{date_context}\n{_DATE_INSTRUCTION}\n\n{base}"
    return base


SYNTHESIS_SYSTEM = _FORMAT_SYSTEM["default"]


SYNTHESIS_USER_TEMPLATE = """\
# Research Topic
{prompt}

# Target Length
Write approximately {target_words} words of substantive content (excluding the
"## Sources" section). A ~10% variance is fine — do not pad or cut off early
to hit the number exactly.

# Sources
{sources_block}

---
Synthesize the above sources into a Markdown report on the topic following the
structure rules in the system message. Include a "## Sources" section at the
end with numbered references.
"""

QUERY_GENERATION_SYSTEM = """\
You are a search-query generator. Given a research topic, output 3-5 concise
DuckDuckGo search queries (one per line, no numbering, no explanation).
Focus on different angles of the topic to get diverse results.
"""


def build_synthesis_prompt(
    prompt: str,
    sources: list[dict],
    target_tokens: int = 1500,
) -> str:
    """Build the user message for synthesis from scraped source data."""
    blocks: list[str] = []
    for i, src in enumerate(sources, 1):
        title = src.get("title", "Untitled")
        url = src.get("url", "")
        content = src.get("content", "")
        if len(content) > 6000:
            content = content[:6000] + "\n[...truncated]"
        blocks.append(f"### [Source {i}] {title}\nURL: {url}\n\n{content}")

    sources_block = "\n\n".join(blocks)
    # 1 BPE token ≈ 4 chars; average English word ≈ 5 chars → ~0.8 words/token.
    target_words = max(1, int(round(target_tokens * 0.8)))
    return SYNTHESIS_USER_TEMPLATE.format(
        prompt=prompt,
        sources_block=sources_block,
        target_words=target_words,
    )

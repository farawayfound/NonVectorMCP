# -*- coding: utf-8 -*-
"""NLP-based content classification and tagging for ChunkyLink."""
import re
import logging
from typing import List, Dict, Any

try:
    import spacy
    from spacy.matcher import PhraseMatcher
    nlp = spacy.load("en_core_web_md")
    _HAS_SPACY = True
except (ImportError, OSError):
    nlp = None
    PhraseMatcher = None
    _HAS_SPACY = False
    logging.warning(
        "nlp_classifier: spaCy/en_core_web_md unavailable — "
        "NLP classification disabled. Run: pip install spacy && python -m spacy download en_core_web_md"
    )


def _build_matchers(content_tags: dict) -> dict:
    if not _HAS_SPACY:
        return {}
    matchers = {}
    for tag, keywords in content_tags.items():
        matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
        patterns = [nlp.make_doc(kw) for kw in keywords]
        matcher.add(tag, patterns)
        matchers[tag] = matcher
    return matchers


def _get_config():
    from backend.config import get_settings
    return get_settings()


def classify_content_nlp(text: str, max_chars: int = 5000, auto_classify: bool = True, auto_tag: bool = True) -> Dict[str, Any]:
    if not _HAS_SPACY:
        return {"category": "general", "tags": [], "entities": {}, "key_phrases": []}
    settings = _get_config()
    doc = nlp(text[:max_chars])

    entities = {}
    for ent in doc.ents:
        entities.setdefault(ent.label_, set()).add(ent.text)
    entities = {k: list(v)[:10] for k, v in entities.items()}

    noun_chunks = [chunk.text.lower() for chunk in doc.noun_chunks if len(chunk.text) > 3][:20]

    if auto_tag:
        tags = _generate_automatic_tags(doc, entities, noun_chunks)
    else:
        matchers = _build_matchers(settings.CONTENT_TAGS)
        tags = set()
        for tag, matcher in matchers.items():
            if matcher(doc):
                tags.add(tag)

    tags = list(tags)[:settings.MAX_TAGS_PER_CHUNK]

    if auto_classify:
        category = _determine_category_automatic(doc, entities, noun_chunks)
    else:
        category = _determine_category(entities, tags, noun_chunks)

    return {
        "category": category,
        "tags": tags,
        "entities": entities,
        "key_phrases": noun_chunks,
    }


def _normalize_tag(tag: str) -> str:
    tag = tag.lower().strip()
    tag = re.sub(r'[\n\r]+', ' ', tag)
    tag = re.sub(r'\s+', '-', tag)
    tag = re.sub(r'[^\w\-]', '', tag)
    tag = re.sub(r'\-{2,}', '-', tag)
    tag = tag.strip('-')
    return tag[:50]


def _generate_automatic_tags(doc, entities: Dict, noun_chunks: List[str]) -> set:
    tags = set()
    exclusions = {"thing", "way", "use", "make", "get", "go", "come", "take", "give",
                  "know", "think", "see", "want", "look", "need", "try", "work", "call"}

    acronym_freq = {}
    for token in doc:
        if token.text.isupper() and 2 <= len(token.text) <= 7 and token.is_alpha:
            acronym_freq[token.text] = acronym_freq.get(token.text, 0) + 1
    for acronym, freq in acronym_freq.items():
        if freq >= 2:
            tags.add(acronym)

    noun_freq = {}
    for token in doc:
        if (token.pos_ in ["NOUN", "PROPN"] and not token.is_stop
                and len(token.text) >= 4 and token.lemma_.lower() not in exclusions):
            noun_freq[token.lemma_.lower()] = noun_freq.get(token.lemma_.lower(), 0) + 1
    for noun, freq in sorted(noun_freq.items(), key=lambda x: x[1], reverse=True)[:5]:
        if freq >= 2:
            tags.add(noun)

    for org in entities.get("ORG", [])[:3]:
        if len(org) < 30:
            tags.add(_normalize_tag(org))
    for product in entities.get("PRODUCT", [])[:3]:
        if len(product) < 30:
            tags.add(_normalize_tag(product))

    verb_freq = {}
    for token in doc:
        if (token.pos_ == "VERB" and not token.is_stop
                and len(token.text) >= 4 and token.lemma_.lower() not in exclusions):
            verb_freq[token.lemma_.lower()] = verb_freq.get(token.lemma_.lower(), 0) + 1
    for verb, freq in sorted(verb_freq.items(), key=lambda x: x[1], reverse=True)[:3]:
        if freq >= 2:
            tags.add(f"action-{verb}")

    return {_normalize_tag(t) for t in tags if len(_normalize_tag(t)) >= 3}


def _determine_category_automatic(doc, entities: Dict, noun_chunks: List[str]) -> str:
    """Determine category using NLP entity recognition, POS tagging, and structural analysis."""
    text_lower = doc.text.lower()

    # Count entity types from the spaCy doc
    ent_counts: Dict[str, int] = {}
    for ent in doc.ents:
        ent_counts[ent.label_] = ent_counts.get(ent.label_, 0) + 1

    # Structural patterns
    numbered_items = len(re.findall(r'^\s*\d+[.)]\s', doc.text, re.MULTILINE))
    bullet_items = len(re.findall(r'[•●▪\-\*]\s+\w', doc.text))
    glossary_lines = len(re.findall(r'^[A-Z][^:\n]{2,40}:\s+\w', doc.text, re.MULTILINE))
    comma_lists = len(re.findall(r'(?:\w+,\s*){2,}\w+', doc.text))

    # Verb analysis — past tense action verbs signal experience
    past_verbs = sum(1 for t in doc if t.pos_ == "VERB" and "Past" in str(t.morph.get("Tense")))
    action_verbs = sum(1 for t in doc if t.pos_ == "VERB" and not t.is_stop and len(t.text) >= 4)

    # Noun chunk topic detection
    edu_signal = sum(1 for nc in noun_chunks if any(w in nc for w in
        ("university", "college", "degree", "bachelor", "master",
         "gpa", "coursework", "school", "certification", "diploma", "graduate")))
    skill_signal = sum(1 for nc in noun_chunks if any(w in nc for w in
        ("skill", "tool", "platform", "framework", "language",
         "technology", "proficien", "expertise", "stack")))
    overview_signal = sum(1 for nc in noun_chunks if any(w in nc for w in
        ("summary", "overview", "profile", "introduction", "background", "objective")))

    scores: Dict[str, float] = {}

    # Experience: organizations + dates + action/past verbs + bullet points
    scores["experience"] = (
        ent_counts.get("ORG", 0) * 3 +
        ent_counts.get("DATE", 0) * 2 +
        past_verbs * 1.5 +
        min(bullet_items, 6) * 1.5
    )

    # Skills: technology-like entities, comma-separated lists, skill noun chunks
    scores["skills"] = (
        ent_counts.get("PRODUCT", 0) * 3 +
        skill_signal * 4 +
        comma_lists * 2
    )

    # Education: education noun chunks + ORG entities (universities are ORGs)
    scores["education"] = edu_signal * 5

    # Achievements: numeric entities (CARDINAL, PERCENT, MONEY, QUANTITY)
    scores["achievements"] = (
        ent_counts.get("CARDINAL", 0) * 1.5 +
        ent_counts.get("PERCENT", 0) * 4 +
        ent_counts.get("MONEY", 0) * 3 +
        ent_counts.get("QUANTITY", 0) * 2
    )

    # Procedures: numbered/ordered lists, imperative verbs
    scores["procedures"] = numbered_items * 4

    # Overview: summary-like noun chunks, short text, few entities
    scores["overview"] = overview_signal * 5

    # Glossary: term:definition structure
    scores["glossary"] = glossary_lines * 4

    # Technical: code patterns, technical entities
    code_chars = sum(1 for c in doc.text if c in "{}[]<>=|;")
    scores["technical"] = (
        min(code_chars, 10) +
        ent_counts.get("PRODUCT", 0) * 1.5
    )

    # Require minimum evidence to assign a specific category
    best_cat = max(scores, key=scores.get)
    return best_cat if scores[best_cat] >= 4 else "general"


def _determine_category(entities: Dict, tags: List[str], noun_chunks: List[str]) -> str:
    """Fallback category detection when auto-classification is disabled."""
    tag_set = set(tags)
    if "experience" in tag_set or "ORG" in entities:
        return "experience"
    if "education" in tag_set:
        return "education"
    if "skills" in tag_set or "PRODUCT" in entities:
        return "skills"
    return "general"


def enrich_record_with_nlp(record: Dict, text_sample: str, auto_classify: bool = None, auto_tag: bool = None) -> Dict:
    try:
        settings = _get_config()
        if auto_classify is None:
            auto_classify = settings.ENABLE_AUTO_CLASSIFICATION
        if auto_tag is None:
            auto_tag = settings.ENABLE_AUTO_TAGGING

        nlp_data = classify_content_nlp(text_sample, auto_classify=auto_classify, auto_tag=auto_tag)

        if "metadata" in record:
            record["metadata"]["nlp_category"] = nlp_data["category"]
            record["metadata"]["nlp_entities"] = nlp_data["entities"]
            record["metadata"]["key_phrases"] = nlp_data["key_phrases"]

        if auto_tag:
            record["tags"] = nlp_data["tags"]
        else:
            existing_tags = set(record.get("tags", []))
            existing_tags.update(nlp_data["tags"])
            record["tags"] = list(existing_tags)

        # Apply CONTENT_TAGS phrase matching on top
        matchers = _build_matchers(settings.CONTENT_TAGS)
        if matchers:
            doc = nlp(text_sample[:5000])
            domain_tags = set(record.get("tags", []))
            for tag, matcher in matchers.items():
                if matcher(doc):
                    domain_tags.add(tag)
            record["tags"] = list(domain_tags)

        if auto_classify and "tags" in record:
            record["tags"] = [nlp_data["category"]] + [t for t in record["tags"] if t != nlp_data["category"]]
        record["tags"] = record["tags"][:settings.MAX_TAGS_PER_CHUNK]

    except Exception as e:
        logging.warning(f"NLP enrichment failed: {e}")

    return record

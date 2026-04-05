# -*- coding: utf-8 -*-
"""
NLP-based content classification and tagging
"""

import sys, logging, re
from pathlib import Path
from typing import List, Dict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

try:
    import spacy
    from spacy.matcher import PhraseMatcher
except ImportError:
    raise SystemExit("Please install spaCy: pip install spacy && python -m spacy download en_core_web_sm")

# Load model once at module level
try:
    nlp = spacy.load("en_core_web_md")
except OSError:
    raise SystemExit("Please download spaCy model: python -m spacy download en_core_web_md")

# Build phrase matchers from config
def _build_matchers():
    matchers = {}
    for tag, keywords in config.CONTENT_TAGS.items():
        matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
        patterns = [nlp.make_doc(kw) for kw in keywords]
        matcher.add(tag, patterns)
        matchers[tag] = matcher
    return matchers

MATCHERS = _build_matchers()

def classify_content_nlp(text: str, max_chars: int = 5000, auto_classify: bool = True, auto_tag: bool = True) -> Dict[str, Any]:
    """NLP-based content classification with entity extraction and topic modeling"""
    doc = nlp(text[:max_chars])
    
    # Extract entities
    entities = {}
    for ent in doc.ents:
        ent_type = ent.label_
        entities.setdefault(ent_type, set()).add(ent.text)
    
    # Convert sets to lists for JSON serialization
    entities = {k: list(v)[:10] for k, v in entities.items()}
    
    # Extract key noun chunks for additional context
    noun_chunks = [chunk.text.lower() for chunk in doc.noun_chunks if len(chunk.text) > 3][:20]
    
    # Automatic tagging
    if auto_tag:
        tags = _generate_automatic_tags(doc, entities, noun_chunks)
    else:
        # Use config-based phrase matching
        tags = set()
        for tag, matcher in MATCHERS.items():
            matches = matcher(doc)
            if matches:
                tags.add(tag)
    
    # Limit tags to max count
    max_tags = getattr(config, 'MAX_TAGS_PER_CHUNK', 10)
    tags = list(tags)[:max_tags]
    
    # Automatic classification
    if auto_classify:
        category = _determine_category_automatic(doc, entities, noun_chunks)
    else:
        category = _determine_category(entities, tags, noun_chunks)
    
    return {
        "category": category,
        "tags": tags,
        "entities": entities,
        "key_phrases": noun_chunks
    }

def _normalize_tag(tag: str) -> str:
    """Normalize tags for consistency"""
    tag = tag.lower().strip()
    tag = re.sub(r'[\n\r]+', ' ', tag)
    tag = re.sub(r'\s+', '-', tag)
    tag = re.sub(r'[^\w\-]', '', tag)
    tag = re.sub(r'\-{2,}', '-', tag)
    tag = tag.strip('-')
    return tag[:50]

def _generate_automatic_tags(doc, entities: Dict, noun_chunks: List[str]) -> set:
    """Generate tags automatically from content analysis without preset keywords"""
    tags = set()
    
    exclusions = {"thing", "way", "use", "make", "get", "go", "come", "take", "give", 
                  "know", "think", "see", "want", "look", "need", "try", "work", "call"}
    
    # Extract acronyms (all caps, 2-7 characters)
    acronym_freq = {}
    for token in doc:
        if token.text.isupper() and 2 <= len(token.text) <= 7 and token.is_alpha:
            acronym_freq[token.text] = acronym_freq.get(token.text, 0) + 1
    
    for acronym, freq in acronym_freq.items():
        if freq >= 2:
            tags.add(acronym)
    
    # Extract substantive nouns
    noun_freq = {}
    for token in doc:
        if (token.pos_ in ["NOUN", "PROPN"] and 
            not token.is_stop and 
            len(token.text) >= 4 and
            token.lemma_.lower() not in exclusions):
            lemma = token.lemma_.lower()
            noun_freq[lemma] = noun_freq.get(lemma, 0) + 1
    
    top_nouns = sorted(noun_freq.items(), key=lambda x: x[1], reverse=True)[:5]
    for noun, freq in top_nouns:
        if freq >= 2:
            tags.add(noun)
    
    # Extract organization names (normalized)
    for org in entities.get("ORG", [])[:3]:
        if len(org) < 30:
            tags.add(_normalize_tag(org))
    
    # Extract product names (normalized)
    for product in entities.get("PRODUCT", [])[:3]:
        if len(product) < 30:
            tags.add(_normalize_tag(product))
    
    # Extract substantive action verbs
    verb_freq = {}
    for token in doc:
        if (token.pos_ == "VERB" and 
            not token.is_stop and 
            len(token.text) >= 4 and
            token.lemma_.lower() not in exclusions):
            lemma = token.lemma_.lower()
            verb_freq[lemma] = verb_freq.get(lemma, 0) + 1
    
    top_verbs = sorted(verb_freq.items(), key=lambda x: x[1], reverse=True)[:3]
    for verb, freq in top_verbs:
        if freq >= 2:
            tags.add(f"action-{verb}")
    
    # Normalize and filter all tags
    return {_normalize_tag(t) for t in tags if len(_normalize_tag(t)) >= 3}

# Keyword sets for category scoring
# NOTE: all pipe-prefixed keywords use word-boundary anchors in _score_keywords
# to avoid matching markdown table pipes (| Task: | Steps: |)
_QUERY_KEYWORDS = {
    "index=", "sourcetype=", "source=",
    "| stats ", "| rex ", "| eval ", "| search ", "| where ",
    "| dedup ", "| sort ", "| head ", "| tail ", "| join ",
    "| timechart ", "| transaction ", "| spath ",
    "index=aws", "opensearch",
    # 'kibana' removed — appears in prose too frequently
    # pipe keywords now require trailing space so '| Status |' won't match '| stats '
}
_TROUBLESHOOT_KEYWORDS = {
    "error", "fail", "failure", "issue", "problem", "troubleshoot", "debug",
    "not working", "unavailable", "outage", "degraded", "symptom", "root cause",
    "resolution", "workaround", "escalat", "incident", "alert", "alarm",
    "3802", "error code", "exception", "timeout", "unreachable",
}
_SOP_KEYWORDS = {
    "step ", "steps", "procedure", "how to", "navigate to", "click ", "select ",
    "open ", "go to", "log in", "log out", "configure", "set up", "setup",
    "workflow", "process", "instructions", "follow", "complete the",
}
_REFERENCE_KEYWORDS = {
    "contact", "email", "phone", "escalat", "team", "group", "channel",
    "slack", "jira", "ticket", "oncall", "on-call", "pagerduty", "runbook",
    "sme", "poc", "point of contact", "distribution list",
}
_GLOSSARY_KEYWORDS = {
    "acronym", "abbreviation", "definition", "glossary", "stands for",
    "refers to", "is defined as", "meaning", "terminology",
}
_MANUAL_KEYWORDS = {
    "overview", "introduction", "description", "feature", "capability",
    "architecture", "component", "specification", "requirement", "design",
    "playbook", "guide", "documentation", "manual",
}

def _score_keywords(text_lower: str, keywords: set) -> int:
    return sum(1 for kw in keywords if kw in text_lower)

# Compiled once at module level — used in _determine_category_automatic
# Requires trailing space/= on pipe commands to avoid matching markdown table pipes
_QUERY_SYNTAX = re.compile(
    r'index=\w|sourcetype=\w'
    r'|\| stats |\| eval |\| rex |\| dedup |\| timechart |\| transaction |\| spath '
    r'|field\.\w+\s*:|OV-TUNE-FAIL|ov-tune-fail'
)

def _determine_category_automatic(doc, entities: Dict, noun_chunks: List[str]) -> str:
    """Automatically determine category from keyword signals"""
    text_lower = doc.text.lower()
    
    scores = {
        "queries":         _score_keywords(text_lower, _QUERY_KEYWORDS) * 4,
        "troubleshooting": _score_keywords(text_lower, _TROUBLESHOOT_KEYWORDS) * 3,
        "sop":             _score_keywords(text_lower, _SOP_KEYWORDS) * 3,
        "reference":       _score_keywords(text_lower, _REFERENCE_KEYWORDS) * 3,
        "glossary":        _score_keywords(text_lower, _GLOSSARY_KEYWORDS) * 5,
        "manual":          _score_keywords(text_lower, _MANUAL_KEYWORDS) * 2,
    }
    
    # Boost queries for SPL pipe density — only when real query syntax is present.
    # Markdown table pipes (| col | col |) would otherwise inflate this score
    # for every table chunk in playbook/SOP documents.
    if _QUERY_SYNTAX.search(doc.text):
        pipe_count = text_lower.count(" | ")
        scores["queries"] += pipe_count * 3
    else:
        # Penalise queries classification when no actual query syntax is present.
        # Chunks from tool-access docs get tagged 'queries' via CONTENT_TAGS but
        # contain no SPL/DQL/Kibana syntax — this penalty pushes them to sop/manual.
        scores["queries"] = max(0, scores["queries"] - 8)
    
    # Boost glossary for colon-definition patterns
    scores["glossary"] += len(re.findall(r'^[A-Z][^:\n]{2,40}:\s+\w', doc.text, re.MULTILINE)) * 4
    
    # Boost sop for numbered steps
    scores["sop"] += len(re.findall(r'^\s*\d+\.\s', doc.text, re.MULTILINE)) * 2
    
    best_cat = max(scores, key=scores.get)
    return best_cat if scores[best_cat] >= 3 else "general"

def _determine_category(entities: Dict, tags: List[str], noun_chunks: List[str]) -> str:
    """Determine primary category from NLP analysis (config-based)"""
    
    # Convert tags to set for checking
    tag_set = set(tags)
    
    # Priority-based categorization using config tags
    if "queries" in tag_set or "splunk" in tag_set or "kibana" in tag_set:
        return "queries"
    
    if "troubleshooting" in tag_set:
        return "troubleshooting"
    
    if "procedures" in tag_set:
        return "sop"
    
    if "tickets" in tag_set or "ORG" in entities:
        return "reference"
    
    # Check for technical entities
    if "PRODUCT" in entities:
        return "manual"
    
    # Fallback
    return "general"

def enrich_record_with_nlp(record: Dict, text_sample: str, auto_classify: bool = None, auto_tag: bool = None) -> Dict:
    """Enrich a record with NLP-derived metadata"""
    try:
        # Use config defaults if not specified
        if auto_classify is None:
            auto_classify = getattr(config, 'ENABLE_AUTO_CLASSIFICATION', False)
        if auto_tag is None:
            auto_tag = getattr(config, 'ENABLE_AUTO_TAGGING', False)
        
        nlp_data = classify_content_nlp(text_sample, auto_classify=auto_classify, auto_tag=auto_tag)
        
        # Add to metadata
        if "metadata" in record:
            record["metadata"]["nlp_category"] = nlp_data["category"]
            record["metadata"]["nlp_entities"] = nlp_data["entities"]
            record["metadata"]["key_phrases"] = nlp_data["key_phrases"]
        
        # Handle tags based on auto_tag setting
        if auto_tag:
            record["tags"] = nlp_data["tags"]
        else:
            if "tags" in record:
                existing_tags = set(record["tags"])
                existing_tags.update(nlp_data["tags"])
                record["tags"] = list(existing_tags)
            else:
                record["tags"] = nlp_data["tags"]

        # Always apply CONTENT_TAGS phrase matching on top of auto-generated tags
        # so domain-specific tool/platform tags are never missed regardless of auto_tag flag
        if MATCHERS:
            doc = nlp(text_sample[:5000])
            domain_tags = set(record.get("tags", []))
            for tag, matcher in MATCHERS.items():
                if matcher(doc):
                    domain_tags.add(tag)
            record["tags"] = list(domain_tags)

        # Promote NLP category to first tag position, then apply cap
        # Cap is applied last so category promotion never displaces a domain tag
        if auto_classify and "tags" in record:
            record["tags"] = [nlp_data["category"]] + [t for t in record["tags"] if t != nlp_data["category"]]
        max_tags = getattr(config, 'MAX_TAGS_PER_CHUNK', 25)
        record["tags"] = record["tags"][:max_tags]
        
    except Exception as e:
        logging.warning(f"NLP enrichment failed: {e}")
    
    return record

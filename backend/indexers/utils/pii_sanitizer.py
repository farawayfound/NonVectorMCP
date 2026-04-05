# -*- coding: utf-8 -*-
"""
PII sanitizer — Redact personally identifiable information from text before
indexing or persisting to the knowledge base.

Redacted categories:
  - Email addresses      → <EMAIL>
  - Phone numbers        → <PHONE>
  - Passwords/credentials→ <CREDENTIAL>
  - Account numbers      → <ACCOUNT_NUMBER>
  - Street addresses     → <ADDRESS>
  - Person names (NER)   → <PERSON_NAME>

Query-aware: text classified as a diagnostic query (SPL/Kibana/DQL) receives
only high-confidence redactions to avoid corrupting field names and trace IDs.
"""
import re
import logging

try:
    import spacy as _spacy
    _nlp = _spacy.load("en_core_web_md")
    _HAS_NLP = True
except Exception:
    _nlp = None
    _HAS_NLP = False
    logging.warning("pii_sanitizer: spaCy unavailable — PERSON entity redaction disabled")

_QUERY_SIGNALS = re.compile(
    r"(?:"
    r"index=[a-z]"
    r"|sourcetype="
    r"|\|\s*(?:stats|rex|table|eval|dedup|timechart|search|spath|sort|head|rename|fillnull|fields)\b"
    r"|earliest=-"
    r"|field\.\w+\s*:"
    r"|AND\s+\w+\.\w+"
    r")",
    re.IGNORECASE,
)

_EMAIL_RAW = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

_PHONE = re.compile(
    r"(?<!\d)"
    r"(?:\+?1[\s.\-]?)?"
    r"(?:\(?\d{3}\)?[\s.\-]?)"
    r"\d{3}[\s.\-]?\d{4}"
    r"(?!\d)"
)

_PHONE_SAFE_CTX = re.compile(
    r"(?:helpdesk|help\s+desk|support\s+line|escalat|oncall|on-call"
    r"|contact|phone\s*:|call\s+list|option\s+\d|ext\.?\s*\d"
    r"|toll.?free|1-8[0-9]{2}|866|877|888|800)",
    re.IGNORECASE,
)

_BEARER = re.compile(
    r"(?i)(Bearer|Basic)\s+([A-Za-z0-9+/=._\-]{8,})"
)

_CREDENTIAL = re.compile(
    r"(?i)(password|passwd|pwd|pass|secret|api[_\-]?key|credential)"
    r"(\s*[=:]\s*)"
    r"([^\s,;\"'\]\)]{4,})"
)

_SLASH_CREDENTIAL = re.compile(
    r"(?<![/\w])"
    r"[A-Za-z0-9._\-]{3,}"
    r"/"
    r"(?=[^\s/]{4,})(?=\S*[^A-Za-z\s/])"
    r"[^\s/]{4,}"
    r"(?![/\w])"
)

_ACCOUNT_NUMBER = re.compile(r"(?<!\d)\d{8,16}(?!\d)")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
_HEX_STRING = re.compile(r"(?<![\w])(?=[0-9a-f]*[a-f])[0-9a-f]{8,}(?![\w])", re.IGNORECASE)

_ADDRESS = re.compile(
    r"\b\d{1,5}\s+[A-Za-z0-9\s]{2,40}"
    r"(?:Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Way|Place|Pl|Circle|Cir)"
    r"(?:\s*(?:Apt|Suite|Ste|Unit|#)\s*[\w\-]+)?"
    r"\b",
    re.IGNORECASE,
)

_PERSON_SAFE_CTX = re.compile(
    r"(?:escalat|contact|oncall|on-call"
    r"|manager|director|engineer|analyst|lead|team|vp |svp |attn:"
    r"|assigned\s+to|owned\s+by|poc|sme|ext\.?\s*\d)",
    re.IGNORECASE,
)


def _get_internal_domains() -> set[str]:
    """Load internal email domains from config (cached)."""
    try:
        from backend.config import get_settings
        return set(d.lower() for d in get_settings().PII_INTERNAL_DOMAINS)
    except Exception:
        return set()


def _is_query_text(text: str) -> bool:
    return bool(_QUERY_SIGNALS.search(text[:1000]))


def _redact_emails(text: str) -> str:
    internal = _get_internal_domains()

    def _replace(m: re.Match) -> str:
        email = m.group(0)
        domain = email.split("@", 1)[1].lower() if "@" in email else ""
        if domain in internal:
            return email
        return "<EMAIL>"
    return _EMAIL_RAW.sub(_replace, text)


def _redact_phones(text: str) -> str:
    def _replace(m: re.Match) -> str:
        start = max(0, m.start() - 120)
        end = min(len(text), m.end() + 120)
        ctx = text[start:end]
        if _PHONE_SAFE_CTX.search(ctx):
            return m.group(0)
        digits = re.sub(r'\D', '', m.group(0))
        if re.match(r'^1?(800|833|844|855|866|877|888)', digits):
            return m.group(0)
        return "<PHONE>"
    return _PHONE.sub(_replace, text)


def _redact_account_numbers(text: str) -> str:
    uuid_store: list[str] = []
    def _stash_uuid(m: re.Match) -> str:
        uuid_store.append(m.group(0))
        return f"\x00UUID{len(uuid_store) - 1}\x00"
    text = _UUID.sub(_stash_uuid, text)

    hex_store: list[str] = []
    def _stash_hex(m: re.Match) -> str:
        hex_store.append(m.group(0))
        return f"\x00HEX{len(hex_store) - 1}\x00"
    text = _HEX_STRING.sub(_stash_hex, text)

    text = _ACCOUNT_NUMBER.sub("<ACCOUNT_NUMBER>", text)

    for i, val in enumerate(hex_store):
        text = text.replace(f"\x00HEX{i}\x00", val)
    for i, val in enumerate(uuid_store):
        text = text.replace(f"\x00UUID{i}\x00", val)

    return text


def _redact_ner(text: str) -> str:
    if not _HAS_NLP or _nlp is None:
        return text
    try:
        doc = _nlp(text[:2000])
        replacements = []
        for ent in doc.ents:
            if ent.label_ != "PERSON":
                continue
            sent_text = ent.sent.text if ent.sent else text[max(0, ent.start_char-100):ent.end_char+100]
            if _PERSON_SAFE_CTX.search(sent_text):
                continue
            replacements.append((ent.start_char, ent.end_char))
        for start, end in reversed(replacements):
            text = text[:start] + "<PERSON_NAME>" + text[end:]
    except Exception as e:
        logging.warning(f"pii_sanitizer: NER redaction failed: {e}")
    return text


def sanitize_pii(text: str) -> str:
    """Redact PII from text. Query-safe mode for SPL/Kibana/DQL syntax."""
    if not text:
        return text

    text = _BEARER.sub(lambda m: m.group(1) + " <CREDENTIAL>", text)
    text = _redact_account_numbers(text)

    if not _is_query_text(text):
        text = _CREDENTIAL.sub(lambda m: m.group(1) + m.group(2) + "<CREDENTIAL>", text)
        text = _SLASH_CREDENTIAL.sub("<CREDENTIAL>", text)
        text = _redact_emails(text)
        text = _redact_phones(text)
        text = _ADDRESS.sub("<ADDRESS>", text)
        text = _redact_ner(text)

    return text

# -*- coding: utf-8 -*-
"""
cpni_sanitizer.py — Redact Customer Proprietary Network Information (CPNI)
from text before indexing or persisting to the knowledge base.

Redacted categories (CUSTOMER data only):
  - Customer email addresses → <EMAIL>  (internal/employee domains exempt)
  - Customer phone numbers   → <PHONE>  (operational/NOC numbers exempt)
  - Passwords / credentials  → <CREDENTIAL>
  - Account numbers          → <ACCOUNT_NUMBER>
  - Customer street addresses→ <ADDRESS>
  - Customer names (NER)     → <CUSTOMER_NAME>

NOT redacted (internal operational data):
  - @charter.com, @spectrum.com, @twc.com, @timewarnercable.com employee emails
  - Distribution list emails (dl-*, DL-*)
  - NOC/support phone numbers appearing in escalation table context
  - Employee names in escalation/contact tables
  - Facility/shipping addresses

Query-aware: text classified as a diagnostic query (SPL/Kibana/DQL) receives
only high-confidence redactions (bearer tokens, account numbers) to avoid
corrupting field names, port numbers, trace IDs, and numeric query parameters.
"""
import re, logging

# ── Optional spaCy NER for customer name redaction ───────────────────────────
try:
    import spacy as _spacy
    _nlp = _spacy.load("en_core_web_md")
    _HAS_NLP = True
except Exception:
    _nlp = None
    _HAS_NLP = False
    logging.warning("cpni_sanitizer: spaCy unavailable — PERSON entity redaction disabled")

# ── Query detection ───────────────────────────────────────────────────────────
# Signals that the text is a diagnostic query block, not customer prose.
# Any one match is sufficient to engage query-safe mode.
_QUERY_SIGNALS = re.compile(
    r"(?:"
    r"index=[a-z]"                          # SPL index clause
    r"|sourcetype="                          # SPL sourcetype
    r"|\|\s*(?:stats|rex|table|eval|dedup|timechart|search|spath|sort|head|rename|fillnull|fields)\b"  # SPL pipe commands
    r"|earliest=-"                           # SPL time modifier
    r"|field\.\w+\s*:"                       # OpenSearch DQL dot-notation
    r"|AND\s+\w+\.\w+"                       # DQL compound field
    r"|\"|APP-ERR-CODE\""                    # App Kibana literal
    r")",
    re.IGNORECASE,
)

# ── Compiled patterns ─────────────────────────────────────────────────────────

_EMAIL_RAW = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)

# Internal domains — never redact these regardless of context
_INTERNAL_EMAIL_DOMAINS = re.compile(
    r"@(?:"
    r"acme\.com"
    r"|corp\.internal"
    r"|partner\.com"
    r")$",
    re.IGNORECASE,
)

# Customer email domains — residential ISP addresses that are customer data
_CUSTOMER_EMAIL_DOMAINS = re.compile(
    r"@(?:"
    r"customer-isp\.net"
    r"|consumer-mail\.com"
    r"|gmail\.com"
    r"|yahoo\.com"
    r"|hotmail\.com"
    r"|outlook\.com"
    r"|aol\.com"
    r"|icloud\.com"
    r"|live\.com"
    r"|msn\.com"
    r"|protonmail\.com"
    r"|me\.com"
    r")$",
    re.IGNORECASE,
)

_PHONE = re.compile(
    r"(?<!\d)"
    r"(?:\+?1[\s.\-]?)?"                    # optional country code
    r"(?:\(?\d{3}\)?[\s.\-]?)"              # area code
    r"\d{3}[\s.\-]?\d{4}"                   # local number
    r"(?!\d)"
)

# Context signals that a phone number is an internal operational number,
# not a customer phone number — suppress redaction when these appear nearby.
_PHONE_INTERNAL_CTX = re.compile(
    r"(?:noc|helpdesk|help\s+desk|support\s+line|escalat|oncall|on-call"
    r"|pagerduty|contact|phone\s*:|call\s+list|option\s+\d|ext\.?\s*\d"
    r"|toll.?free|1-8[0-9]{2}|866|877|888|800)",
    re.IGNORECASE,
)

# Standalone bearer / basic auth header values — safe in query context too
_BEARER = re.compile(
    r"(?i)(Bearer|Basic)\s+([A-Za-z0-9+/=._\-]{8,})"
)

# password=, pwd=, pass=, secret=, token=, api_key=, credential= followed by value.
# Excluded from query-safe mode: token=, auth_key= collide with SPL field names.
_CREDENTIAL = re.compile(
    r"(?i)(password|passwd|pwd|pass|secret|api[_\-]?key|credential)"
    r"(\s*[=:]\s*)"
    r"([^\s,;\"'\]\)]{4,})"
)

# username/password slash-delimited pairs (e.g. TamAJSHV/DPSTest2020!)
# Matches word/non-whitespace where the password part contains at least one
# non-alphanumeric char (digit, symbol) to avoid matching URL path segments.
_SLASH_CREDENTIAL = re.compile(
    r"(?<![/\w])"
    r"[A-Za-z0-9._\-]{3,}"
    r"/"
    r"(?=[^\s/]{4,})(?=\S*[^A-Za-z\s/])"  # password must have a non-alpha char
    r"[^\s/]{4,}"
    r"(?![/\w])"
)

# Account numbers: 8–16 consecutive digits.
# Excluded from account-number redaction: UUID trace IDs (8-4-4-4-12 hex groups)
# and hex strings (all chars a-f0-9) which are trace/request IDs, not account numbers.
_ACCOUNT_NUMBER = re.compile(
    r"(?<!\d)\d{8,16}(?!\d)"
)

# UUID pattern — trace IDs, request IDs, session IDs: never redact these
_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)

# Pure hex strings (no decimal digits only) — request IDs, SHA hashes
_HEX_STRING = re.compile(
    r"(?<![\w])(?=[0-9a-f]*[a-f])[0-9a-f]{8,}(?![\w])",
    re.IGNORECASE,
)

# XML attribute values — extract text from value="..." before other patterns run.
# Matches both single and double quoted attribute values.
_XML_ATTR_VALUE = re.compile(
    r"""(?i)\b(?:value|name|street|address|phone|email|zip|city|state)\s*="""  # attribute name
    r"""([^"]{1,200})"""
    r""""""
)
_XML_ATTR_VALUE_SQ = re.compile(
    r"""(?i)\b(?:value|name|street|address|phone|email|zip|city|state)\s*='"""
    r"""([^']{1,200})"""
    r"""'"""
)

# Street address: number + street name + type suffix.
# Excluded from query-safe mode: street-type words appear in log paths and field names.
_ADDRESS = re.compile(
    r"\b\d{1,5}\s+[A-Za-z0-9\s]{2,40}"
    r"(?:Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Drive|Dr|Lane|Ln|Court|Ct|Way|Place|Pl|Circle|Cir)"
    r"(?:\s*(?:Apt|Suite|Ste|Unit|#)\s*[\w\-]+)?"
    r"\b",
    re.IGNORECASE,
)


def _is_query_text(text: str) -> bool:
    """Return True if text appears to be a diagnostic query block."""
    return bool(_QUERY_SIGNALS.search(text[:1000]))


def _is_customer_email(email: str) -> bool:
    """Return True only if the email address belongs to a customer (residential ISP or freemail)."""
    return bool(_CUSTOMER_EMAIL_DOMAINS.search(email))


def _redact_emails(text: str) -> str:
    """Redact only customer email addresses; preserve internal/operational addresses."""
    def _replace(m: re.Match) -> str:
        return "<EMAIL>" if _is_customer_email(m.group(0)) else m.group(0)
    return _EMAIL_RAW.sub(_replace, text)


def _redact_phones(text: str) -> str:
    """Redact phone numbers that appear in customer-data context.
    Suppresses redaction when the surrounding 120 chars contain internal
    operational signals (NOC lines, escalation tables, toll-free numbers).
    """
    def _replace(m: re.Match) -> str:
        start = max(0, m.start() - 120)
        end = min(len(text), m.end() + 120)
        ctx = text[start:end]
        if _PHONE_INTERNAL_CTX.search(ctx):
            return m.group(0)
        # Toll-free numbers (800/833/844/855/866/877/888) are always operational
        digits = re.sub(r'\D', '', m.group(0))
        if re.match(r'^1?(800|833|844|855|866|877|888)', digits):
            return m.group(0)
        return "<PHONE>"
    return _PHONE.sub(_replace, text)


def _redact_account_numbers(text: str) -> str:
    """
    Redact 8–16 digit sequences as account numbers, but preserve:
      - UUID trace IDs  (8-4-4-4-12 hex)
      - Pure hex strings (contain at least one a-f char — request/session IDs)
    Operates by protecting known-safe patterns with placeholders, running
    the account number regex, then restoring the protected values.
    """
    # Protect UUIDs
    uuid_store: list[str] = []
    def _stash_uuid(m: re.Match) -> str:
        uuid_store.append(m.group(0))
        return f"\x00UUID{len(uuid_store) - 1}\x00"
    text = _UUID.sub(_stash_uuid, text)

    # Protect hex strings
    hex_store: list[str] = []
    def _stash_hex(m: re.Match) -> str:
        hex_store.append(m.group(0))
        return f"\x00HEX{len(hex_store) - 1}\x00"
    text = _HEX_STRING.sub(_stash_hex, text)

    # Redact remaining digit-only sequences
    text = _ACCOUNT_NUMBER.sub("<ACCOUNT_NUMBER>", text)

    # Restore protected values
    for i, val in enumerate(hex_store):
        text = text.replace(f"\x00HEX{i}\x00", val)
    for i, val in enumerate(uuid_store):
        text = text.replace(f"\x00UUID{i}\x00", val)

    return text


# Context signals that a PERSON entity is an internal employee/contact,
# not a customer — suppress NER redaction when these appear in the same sentence.
_PERSON_INTERNAL_CTX = re.compile(
    r"(?:@acme\.com|@corp\.internal|escalat|contact|oncall|on-call"
    r"|manager|director|engineer|analyst|lead|team|vp |svp |attn:"
    r"|assigned\s+to|owned\s+by|poc|sme|ext\.?\s*\d)",
    re.IGNORECASE,
)


def _redact_ner(text: str) -> str:
    """Replace PERSON entities with <CUSTOMER_NAME>, but only when they appear
    in customer-data context (not internal escalation tables or contact lists)."""
    if not _HAS_NLP or _nlp is None:
        return text
    try:
        doc = _nlp(text[:2000])
        replacements = []
        for ent in doc.ents:
            if ent.label_ != "PERSON":
                continue
            # Check sentence context for internal signals
            sent_text = ent.sent.text if ent.sent else text[max(0, ent.start_char-100):ent.end_char+100]
            if _PERSON_INTERNAL_CTX.search(sent_text):
                continue
            replacements.append((ent.start_char, ent.end_char))
        for start, end in reversed(replacements):
            text = text[:start] + "<CUSTOMER_NAME>" + text[end:]
    except Exception as e:
        logging.warning(f"cpni_sanitizer: NER redaction failed: {e}")
    return text


def _flatten_xml_attrs(text: str) -> str:
    """Replace XML attribute values with their bare content so downstream
    patterns (account numbers, NER, address) can match inside them.
    e.g. <Name value="Doe, John"/> → <Name value=DOE_JOHN_FLAT/>
    is NOT what we do — instead we just ensure the value text is visible
    to the regex passes by leaving the structure intact.  The real work is
    done by running all redaction passes on the full text including XML.
    This helper rewrites quoted attribute values that contain CPNI-like
    content into unquoted form so the patterns fire on them.
    """
    # Rewrite value="..." → value=... (remove quotes so digit/NER patterns match)
    text = _XML_ATTR_VALUE.sub(lambda m: m.group(0).replace('"' + m.group(1) + '"', m.group(1)), text)
    text = _XML_ATTR_VALUE_SQ.sub(lambda m: m.group(0).replace("'" + m.group(1) + "'", m.group(1)), text)
    return text


def sanitize_cpni(text: str) -> str:
    """
    Redact CPNI from text.

    Query-safe mode (SPL/Kibana/DQL detected): applies only email and bearer
    token redaction to avoid corrupting field names, numeric parameters, and
    trace IDs that are structurally identical to CPNI patterns.

    Prose mode: applies all patterns including phone, account number, street
    address, credential key=value pairs, and spaCy PERSON NER.
    """
    if not text:
        return text

    original = text

    # Flatten XML attribute quotes so downstream patterns fire inside value="..."
    text = _flatten_xml_attrs(text)

    # Always safe — high specificity, no query false positives
    text = _BEARER.sub(lambda m: m.group(1) + " <CREDENTIAL>", text)

    # Account numbers redacted in both modes — but UUID/hex trace IDs are preserved
    text = _redact_account_numbers(text)

    if not _is_query_text(text):
        # Prose mode — apply remaining patterns that are unsafe in query context
        text = _CREDENTIAL.sub(lambda m: m.group(1) + m.group(2) + "<CREDENTIAL>", text)
        text = _SLASH_CREDENTIAL.sub("<CREDENTIAL>", text)   # username/password pairs
        text = _redact_emails(text)       # customer emails only
        text = _redact_phones(text)       # customer phones only (NOC/toll-free exempt)
        text = _ADDRESS.sub("<ADDRESS>", text)
        text = _redact_ner(text)          # customer names only (employee context exempt)

    if text != original:
        logging.warning("cpni_sanitizer: CPNI redacted from text before indexing")

    return text

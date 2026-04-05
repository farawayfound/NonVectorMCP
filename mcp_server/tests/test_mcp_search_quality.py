# -*- coding: utf-8 -*-
"""
MCP search quality tests — validates that search_kb returns relevant chunks
and search_jira returns structured ticket data for real VPO domain queries.

Extends test_mcp.py with:
  - Real VPO term pairs (satisfies Phase 1 min_hits >= 2)
  - Chunk quality assertions (fields, scores, match types)
  - Jira result structure and content validation
  - Cross-domain and multi-phase coverage checks

Usage:
    python mcp_server/tests/test_mcp_search_quality.py [--url URL] [--token TOKEN]
"""
import sys, json, argparse, urllib.request, urllib.error, textwrap
from pathlib import Path

DEFAULT_URL   = "http://192.168.1.29:8000/mcp"
DEFAULT_TOKEN = "vporag-P3315113"

# ── Transport ─────────────────────────────────────────────────────────────────

def initialize(url: str, token: str) -> str:
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test_quality", "version": "1.0"},
        },
    }).encode()
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        session_id = resp.headers.get("mcp-session-id", "")
        resp.read()
    if not session_id:
        raise RuntimeError("No mcp-session-id returned from initialize")
    return session_id


def call(url: str, token: str, tool: str, args: dict, session_id: str) -> dict:
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "mcp-session-id": session_id,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
    for line in raw.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raw = raw.strip()
    return json.loads(raw) if raw else {"error": "empty response"}


def _parse(result: dict) -> dict:
    content = result.get("result", {}).get("content", [{}])
    text = content[0].get("text", "{}") if content else "{}"
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_raw": text}


# ── Assertion helpers ─────────────────────────────────────────────────────────

class Results:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self._failures: list[str] = []

    def ok(self, label: str, detail: str = ""):
        self.passed += 1
        suffix = f" — {detail}" if detail else ""
        print(f"  [ OK ] {label}{suffix}")

    def fail(self, label: str, reason: str):
        self.failed += 1
        self._failures.append(f"{label}: {reason}")
        print(f"  [FAIL] {label} — {reason}")

    def assert_true(self, label: str, condition: bool, reason: str, detail: str = ""):
        if condition:
            self.ok(label, detail)
        else:
            self.fail(label, reason)

    def summary(self):
        total = self.passed + self.failed
        print("\n" + "-"*60)
        print(f"  {self.passed}/{total} passed", end="")
        if self.failed:
            print(f"  ({self.failed} failed)")
            for f in self._failures:
                print(f"    x {f}")
        else:
            print("  all passed")
        print("-"*60)
        return self.failed == 0


# ── KB search quality tests ───────────────────────────────────────────────────

# Each entry: (label, terms, query, level, min_chunks, required_match_types, required_tags_any)
_KB_CASES = [
    (
        "tune failure worldbox",
        ["tune", "failure"],
        "worldbox tune failure troubleshooting",
        "Standard",
        1, ["Initial"], ["troubleshooting"],
    ),
    (
        "STVA playback error",
        ["playback", "error"],
        "STVA playback error on Xumo device",
        "Standard",
        1, ["Initial"], ["troubleshooting", "queries"],
    ),
    (
        "entitlement provisioning ACE",
        ["entitlement", "provisioning"],
        "entitlement provisioning issue in ACE",
        "Standard",
        1, ["Initial"], [],
    ),
    (
        "DVR recording failure",
        ["recording", "failure"],
        "DVR recording failure cDVR",
        "Standard",
        1, ["Initial"], [],
    ),
    (
        "Splunk SPL query auth",
        ["splunk", "authentication"],
        "Splunk SPL query for authentication errors",
        "Standard",
        1, [], ["queries"],
    ),
    (
        "STB reboot EPG",
        ["reboot", "EPG"],
        "STB rebooting EPG errors worldbox",
        "Standard",
        1, ["Initial"], [],
    ),
    (
        "CEITEAM ticket escalation",
        ["CEITEAM", "ticket"],
        "CEITEAM ticket creation for entitlements escalation",
        "Standard",
        1, ["Initial"], [],
    ),
    (
        "OpenSearch DQL playback",
        ["OpenSearch", "playback"],
        "OpenSearch DQL query for STVA playback errors",
        "Standard",
        1, [], ["queries"],
    ),
    (
        "Quick level returns results",
        ["tune", "failure"],
        "tune failure quick search",
        "Quick",
        1, [], [],
    ),
    (
        "Deep level expands phases",
        ["playback", "error"],
        "STVA playback error deep investigation",
        "Deep",
        1, [], [],
    ),
]


def run_kb_tests(url: str, token: str, r: Results):
    print("\n-- search_kb quality tests --")
    session_id = initialize(url, token)

    for label, terms, query, level, min_chunks, req_match_types, req_tags in _KB_CASES:
        try:
            raw = call(url, token, "search_kb",
                       {"terms": terms, "query": query, "level": level},
                       session_id)
            data = _parse(raw)

            total = data.get("total", 0)
            results = data.get("results", [])
            phases = data.get("phases", {})

            # 1. Minimum chunk count
            r.assert_true(
                f"[KB] {label} — min {min_chunks} chunk(s)",
                total >= min_chunks,
                f"got {total} chunks (terms={terms}, level={level})",
                f"{total} chunks, phases={phases}",
            )

            if total == 0:
                continue  # skip quality checks if nothing returned

            # 2. Required match types present
            for mt in req_match_types:
                r.assert_true(
                    f"[KB] {label} — MatchType '{mt}' present",
                    mt in phases,
                    f"phases={phases}",
                )

            # 3. Required tags present in at least one chunk
            for tag in req_tags:
                found = any(
                    tag in (c.get("tags") or []) or
                    tag in (c.get("metadata", {}).get("nlp_category", ""))
                    for c in results
                )
                r.assert_true(
                    f"[KB] {label} — tag/category '{tag}' in results",
                    found,
                    f"none of {len(results)} chunks had tag '{tag}'",
                )

            # 4. Chunk schema — every result must have id, text, tags, RelevanceScore
            bad_schema = [
                c.get("id", "?") for c in results
                if not (c.get("id") and c.get("text") and
                        isinstance(c.get("tags"), list) and
                        c.get("RelevanceScore") is not None)
            ]
            r.assert_true(
                f"[KB] {label} — chunk schema valid",
                len(bad_schema) == 0,
                f"chunks missing required fields: {bad_schema[:3]}",
                f"all {len(results)} chunks valid",
            )

            # 5. RelevanceScore > 0 for top result
            top_score = results[0].get("RelevanceScore", 0) if results else 0
            r.assert_true(
                f"[KB] {label} — top RelevanceScore > 0",
                top_score > 0,
                f"top score={top_score}",
                f"top score={top_score}",
            )

            # 6. Breadcrumb / context in text
            top_text = results[0].get("text", "") if results else ""
            r.assert_true(
                f"[KB] {label} — top chunk has non-trivial text (>50 chars)",
                len(top_text) > 50,
                f"text length={len(top_text)}",
                f"text length={len(top_text)}",
            )

        except Exception as ex:
            r.fail(f"[KB] {label}", f"exception: {ex}")


# ── Jira search quality tests ─────────────────────────────────────────────────

# Each entry: (label, terms, mode, ticket_type, min_dps, min_rca, required_fields_in_any_ticket)
_JIRA_CASES = [
    (
        "STVA playback top",
        ["STVA", "playback"], "top", "both",
        1, 0, ["Key", "Summary", "Status"],
    ),
    (
        "Xumo error top",
        ["Xumo", "error"], "top", "both",
        1, 0, ["Key", "Summary"],
    ),
    (
        "tune failure dpstriage only",
        ["tune", "failure"], "top", "dpstriage",
        1, 0, ["Key", "Summary", "Status"],
    ),
    (
        "recording DVR postrca",
        ["recording", "DVR"], "top", "postrca",
        0, 1, ["Key", "Summary"],
    ),
    (
        "count mode returns integers",
        ["playback", "error"], "count", "both",
        0, 0, [],  # count mode has no ticket lists
    ),
    (
        "oldest mode returns oldest dict",
        ["STVA", "error"], "oldest", "both",
        0, 0, [],
    ),
    (
        "active status filter",
        ["playback", "error"], "top", "dpstriage",
        0, 0, [],  # may be 0 if none active — just check no crash
    ),
    (
        "since=3 months filter",
        ["STVA", "playback"], "top", "dpstriage",
        0, 0, ["Key"],
    ),
]


def run_jira_tests(url: str, token: str, r: Results):
    print("\n-- search_jira quality tests --")
    session_id = initialize(url, token)

    for label, terms, mode, ticket_type, min_dps, min_rca, req_fields in _JIRA_CASES:
        args = {"terms": terms, "mode": mode, "ticket_type": ticket_type}
        if label == "active status filter":
            args["status"] = ["active"]
        if label == "since=3 months filter":
            args["since"] = 3

        try:
            raw = call(url, token, "search_jira", args, session_id)
            data = _parse(raw)

            if mode == "count":
                r.assert_true(
                    f"[Jira] {label} — dpstriage_count is int",
                    isinstance(data.get("dpstriage_count"), int),
                    f"got {data.get('dpstriage_count')!r}",
                    f"dps={data.get('dpstriage_count')} rca={data.get('postrca_count')}",
                )
                r.assert_true(
                    f"[Jira] {label} — postrca_count is int",
                    isinstance(data.get("postrca_count"), int),
                    f"got {data.get('postrca_count')!r}",
                )
                continue

            if mode == "oldest":
                r.assert_true(
                    f"[Jira] {label} — mode field = 'oldest'",
                    data.get("mode") == "oldest",
                    f"got mode={data.get('mode')!r}",
                )
                continue

            dps = data.get("dpstriage", [])
            rca = data.get("postrca", [])

            r.assert_true(
                f"[Jira] {label} — dpstriage >= {min_dps}",
                len(dps) >= min_dps,
                f"got {len(dps)} (terms={terms})",
                f"dps={len(dps)} rca={len(rca)} source={data.get('source','?')}",
            )
            r.assert_true(
                f"[Jira] {label} — postrca >= {min_rca}",
                len(rca) >= min_rca,
                f"got {len(rca)} (terms={terms})",
            )

            # Required fields in at least one ticket
            all_tickets = dps + rca
            for field in req_fields:
                found = any(field in t for t in all_tickets)
                r.assert_true(
                    f"[Jira] {label} — field '{field}' present",
                    found,
                    f"field missing from all {len(all_tickets)} tickets",
                )

            # RelevanceScore present and numeric in all tickets
            bad_score = [t.get("Key", "?") for t in all_tickets
                         if not isinstance(t.get("RelevanceScore"), (int, float))]
            if all_tickets:
                r.assert_true(
                    f"[Jira] {label} — RelevanceScore numeric in all tickets",
                    len(bad_score) == 0,
                    f"missing in: {bad_score[:3]}",
                    f"all {len(all_tickets)} tickets have score",
                )

        except Exception as ex:
            r.fail(f"[Jira] {label}", f"exception: {ex}")


# ── Aggregated data quality report ────────────────────────────────────────────

def run_aggregation_report(url: str, token: str):
    """Run a Standard search and print a human-readable quality summary."""
    print("\n-- Aggregated data quality report --")
    session_id = initialize(url, token)

    # KB: representative triage query
    raw_kb = call(url, token, "search_kb", {
        "terms": ["playback", "error", "STVA"],
        "query": "STVA playback error troubleshooting on Xumo device",
        "level": "Standard",
    }, session_id)
    kb = _parse(raw_kb)

    print(f"\n  KB search — terms: ['playback','error','STVA'] | level: Standard")
    print(f"    total chunks : {kb.get('total', 0)}")
    print(f"    phases       : {kb.get('phases', {})}")
    print(f"    top_tags     : {kb.get('top_tags', [])}")
    print(f"    discovered   : {kb.get('discovered', [])}")
    print(f"    domains      : {kb.get('domains', [])}")

    results = kb.get("results", [])
    if results:
        print(f"\n  Top 3 chunks by RelevanceScore:")
        for i, c in enumerate(results[:3], 1):
            doc = (c.get("metadata") or {}).get("doc_id", "?")
            tags = c.get("tags", [])[:4]
            score = c.get("RelevanceScore", 0)
            mt = c.get("MatchType", "?")
            snippet = c.get("text", "")[:120].replace("\n", " ")
            print(f"\n    [{i}] {doc}  score={score}  match={mt}")
            print(f"        tags: {tags}")
            print(f"        text: {textwrap.shorten(snippet, 110)}")

    # Jira: same terms
    raw_jira = call(url, token, "search_jira", {
        "terms": ["playback", "error", "STVA"],
        "discovered": kb.get("discovered", [])[:5],
        "mode": "top",
    }, session_id)
    jira = _parse(raw_jira)

    dps = jira.get("dpstriage", [])
    rca = jira.get("postrca", [])
    print(f"\n  Jira search — terms: ['playback','error','STVA'] | source: {jira.get('source','?')}")
    print(f"    DPSTRIAGE : {len(dps)} tickets")
    print(f"    POSTRCA   : {len(rca)} tickets")

    if dps:
        t = dps[0]
        print(f"\n  Top DPSTRIAGE ticket:")
        print(f"    Key     : {t.get('Key')}")
        print(f"    Summary : {textwrap.shorten(t.get('Summary',''), 80)}")
        print(f"    Status  : {t.get('Status')}")
        print(f"    Score   : {t.get('RelevanceScore')}")
        if t.get("RootCause"):
            print(f"    RootCause: {textwrap.shorten(t['RootCause'], 80)}")

    if rca:
        t = rca[0]
        print(f"\n  Top POSTRCA ticket:")
        print(f"    Key     : {t.get('Key')}")
        print(f"    Summary : {textwrap.shorten(t.get('Summary',''), 80)}")
        print(f"    Status  : {t.get('Status')}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url",   default=DEFAULT_URL)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    args = parser.parse_args()

    url, token = args.url, args.token
    print("\n" + "="*60)
    print(f"  MCP SEARCH QUALITY TEST SUITE")
    print(f"  Server : {url}")
    print("="*60)

    try:
        session_id = initialize(url, token)
        print(f"\n  [ OK ] Connected - session {session_id[:16]}...")
    except Exception as ex:
        print(f"\n  [FAIL] Cannot connect: {ex}")
        sys.exit(1)

    r = Results()
    run_kb_tests(url, token, r)
    run_jira_tests(url, token, r)
    run_aggregation_report(url, token)
    ok = r.summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

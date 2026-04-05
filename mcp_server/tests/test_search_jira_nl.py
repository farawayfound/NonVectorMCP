# -*- coding: utf-8 -*-
"""
Tests for search_jira NL question parser (_parse_question).

Deliberately difficult cases: ambiguous phrasing, compound intents,
negations, time expressions, mixed signals, edge cases.

Run: python mcp_server/tests/test_search_jira_nl.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

from tools.search_jira import _parse_question

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def check(label: str, question: str, expected: dict) -> bool:
    result = _parse_question(question)
    ok = True
    failures = []
    for k, v in expected.items():
        actual = result.get(k)
        if actual != v:
            ok = False
            failures.append(f"  {k}: expected={v!r}  got={actual!r}")
    status = PASS if ok else FAIL
    print(f"[{status}] {label}")
    if not ok:
        for f in failures:
            print(f)
    return ok


# ── Test cases ────────────────────────────────────────────────────────────────

cases = [

    # ── COUNT ─────────────────────────────────────────────────────────────────
    ("count: plain 'how many'",
     "How many tickets are there for pixelation?",
     {"mode": "count"}),

    ("count: 'total number of'",
     "What is the total number of issues related to DVR failures?",
     {"mode": "count"}),

    ("count: 'how often does X happen'",
     "How often does the STB reboot after a firmware update?",
     {"mode": "count"}),

    ("count: frequency synonym",
     "What is the frequency of login failures this year?",
     {"mode": "count", "since": 12}),

    # ── OLDEST ────────────────────────────────────────────────────────────────
    ("oldest: plain",
     "What is the oldest ticket for streaming errors?",
     {"mode": "oldest"}),

    ("oldest: 'first reported'",
     "When was this first reported in DPSTRIAGE?",
     {"mode": "oldest", "ticket_type": "dpstriage"}),

    ("oldest: 'going back'",
     "How far back does this problem go?",
     {"mode": "oldest"}),

    ("oldest: 'when did X start'",
     "When did the Smart TV playback issue first start appearing?",
     {"mode": "oldest"}),

    # ── ALL / FULL LIST ───────────────────────────────────────────────────────
    ("all: 'all tickets'",
     "Show me all tickets related to authentication failures",
     {"mode": "custom", "limit": 200}),

    ("all: 'every issue'",
     "List every issue we've had with the lineup service",
     {"mode": "custom", "limit": 200}),

    ("all: 'full list' + postrca",
     "Give me the full list of POSTRCA tickets for DVR",
     {"mode": "custom", "limit": 200, "ticket_type": "postrca"}),

    # ── MOST COMMON / AGGREGATION ─────────────────────────────────────────────
    ("most common: root cause",
     "What is the most common root cause for STB reboots?",
     {"mode": "custom", "limit": 100}),

    ("most common: breakdown by category",
     "Give me a breakdown by resolution category for playback errors",
     {"mode": "custom", "limit": 100}),

    ("most common: grouped by team + time",
     "Show tickets grouped by responsible team for the last 3 months",
     {"mode": "custom", "limit": 100, "since": 3}),

    ("most common: distribution",
     "What is the distribution of ticket statuses for DVR issues?",
     {"mode": "custom", "limit": 100}),

    # ── TREND / TIME ──────────────────────────────────────────────────────────
    ("trend: plain",
     "Is there a trend in pixelation tickets over the last 6 months?",
     {"mode": "count", "since": 6}),

    ("trend: spike",
     "Was there a spike in reboot tickets recently?",
     {"mode": "count"}),

    ("trend: 'over the last N weeks'",
     "How many DVR failures occurred over the last 4 weeks?",
     {"mode": "count", "since": 1}),

    ("trend: 'last 2 years'",
     "Show me the trend in authentication errors over the last 2 years",
     {"mode": "count", "since": 24}),

    # ── TOP-N ─────────────────────────────────────────────────────────────────
    ("top-n: explicit",
     "Show me the top 20 tickets for streaming failures",
     {"mode": "top", "limit": 20}),

    ("top-n: top 5 with status hint",
     "What are the top 5 open tickets for Smart TV playback?",
     {"mode": "top", "limit": 5}),

    # ── STATUS FILTERS ────────────────────────────────────────────────────────
    ("status: active",
     "What active tickets exist for EPG errors?",
     {"status": ["Triage In Progress", "Pending Mitigation", "More Info Needed", "Blocked"]}),

    ("status: resolved",
     "Show me resolved tickets for DVR scheduling failures",
     {"status": ["Closed", "Pending Verification", "Routed to POST-RCA"]}),

    # ── TICKET TYPE ───────────────────────────────────────────────────────────
    ("ticket_type: postrca explicit",
     "How many POSTRCA tickets exist for authentication?",
     {"mode": "count", "ticket_type": "postrca"}),

    ("ticket_type: dpstriage explicit",
     "Show all DPSTRIAGE tickets for Mobile App freezing",
     {"mode": "custom", "limit": 200, "ticket_type": "dpstriage"}),

    # ── DIFFICULT / COMPOUND ──────────────────────────────────────────────────
    ("difficult: count + time + type",
     "How many Post-RCA tickets were created in the last 3 months for DVR?",
     {"mode": "count", "since": 3, "ticket_type": "postrca"}),

    ("difficult: most common + time window",
     "What are the most common issues in the last 6 months?",
     {"mode": "custom", "limit": 100, "since": 6}),

    ("difficult: trend phrased as 'how many' + this year",
     "How many reboot tickets have we seen this year?",
     {"mode": "count", "since": 12}),

    ("difficult: oldest + ticket type from context",
     "When was the first POSTRCA filed for streaming errors?",
     {"mode": "oldest", "ticket_type": "postrca"}),

    ("difficult: top-N + resolved + dpstriage",
     "What are the top 10 resolved DPSTRIAGE tickets for authentication?",
     {"mode": "top", "limit": 10, "ticket_type": "dpstriage",
      "status": ["Closed", "Pending Verification", "Routed to POST-RCA"]}),

    ("difficult: 'how many' + 'this week'",
     "How many tickets were opened this week for Smart TV?",
     {"mode": "count", "since": 1}),

    ("difficult: breakdown + by root cause + last year",
     "Give me a breakdown by root cause for the last year",
     {"mode": "custom", "limit": 100, "since": 12}),

    ("difficult: passive voice count + past N months",
     "How many cases have been reported for EPG failures in the past 2 months?",
     {"mode": "count", "since": 2}),

    ("difficult: oldest + since conflict — oldest wins for mode, since still set",
     "How far back do DVR tickets go, looking at the last 6 months?",
     {"mode": "oldest", "since": 6}),

    # 'open' = not-closed = default behaviour — no status filter set, default exclusions apply
    ("difficult: 'all open' — open means not-closed, no status filter (default handles it)",
     "Show me all open tickets for pixelation",
     {"mode": "custom", "limit": 200}),

    ("difficult: count + 'number of' phrasing variant",
     "What's the number of cases opened for Mobile App freezing this month?",
     {"mode": "count", "since": 1}),

    ("difficult: 'most frequent' + postrca + time",
     "What are the most frequent root causes in POSTRCA over the last year?",
     {"mode": "custom", "limit": 100, "since": 12, "ticket_type": "postrca"}),

    # ── EDGE CASES ────────────────────────────────────────────────────────────
    ("edge: vague 'tell me about' — no mode signal",
     "Tell me about DVR issues",
     {}),

    ("edge: negation phrasing — no false positive",
     "Show tickets that are not resolved for STB reboots",
     {}),

    ("edge: empty string",
     "",
     {}),

    ("edge: whitespace only",
     "   ",
     {}),

    ("edge: unrelated sentence",
     "The weather is nice today",
     {}),

    ("edge: 'open' alone — no status filter set",
     "Show me open tickets for DVR",
     {}),

    ("edge: SQL injection attempt — parses count, no crash",
     "How many tickets'; DROP TABLE dpstriage; --",
     {"mode": "count"}),
]


# ── Runner ────────────────────────────────────────────────────────────────────

def main():
    passed = 0
    failed = 0
    for label, question, expected in cases:
        if check(label, question, expected):
            passed += 1
        else:
            failed += 1

    total = passed + failed
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
    else:
        print("  \033[92mAll tests passed\033[0m")
    print("=" * 60)
    return failed


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""
End-to-end MCP tool tests — run from any machine that can reach the server.
Usage: python mcp_server/tests/test_mcp.py [--url http://host:8000] [--token TOKEN]
"""
import sys, json, argparse, urllib.request, urllib.error

DEFAULT_URL   = "http://192.168.1.29:8000/mcp"
DEFAULT_TOKEN = ""

def call(url: str, token: str, tool: str, args: dict, session_id: str) -> dict:
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args}
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
    # SSE envelope: lines starting with "data: " contain the JSON payload
    for line in raw.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    # Plain JSON fallback (e.g. session errors, validation errors)
    raw = raw.strip()
    return json.loads(raw) if raw else {"error": "empty response"}


def initialize(url: str, token: str) -> str:
    """Perform MCP initialize handshake and return the session ID."""
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test_mcp", "version": "1.0"}
        }
    }).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        session_id = resp.headers.get("mcp-session-id", "")
        resp.read()  # drain body
    if not session_id:
        raise RuntimeError("No mcp-session-id returned from initialize")
    return session_id


def check(label: str, result: dict, assertions: list[tuple]):
    errors = []
    content = result.get("result", {}).get("content", [{}])
    data = json.loads(content[0].get("text", "{}")) if content else {}

    for key, check_fn, msg in assertions:
        val = data
        for part in key.split("."):
            val = val.get(part, None) if isinstance(val, dict) else None
        if not check_fn(val):
            errors.append(f"  FAIL {key}: {msg} (got {val!r})")

    if errors:
        print(f"[FAIL] {label}")
        for e in errors:
            print(e)
    else:
        print(f"[ OK ] {label}")
    return len(errors) == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url",   default=DEFAULT_URL)
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    args = parser.parse_args()

    url, token = args.url, args.token
    passed = failed = 0

    print(f"\nTesting MCP server at {url}\n{'-'*50}")

    try:
        session_id = initialize(url, token)
        print(f"[ OK ] initialize — session {session_id[:16]}...")
        passed += 1
    except Exception as ex:
        print(f"[FAIL] initialize — {ex}")
        print("Cannot continue without a session ID.")
        sys.exit(1)

    def c(tool, a): return call(url, token, tool, a, session_id)

    # ── Test 1: search_kb Quick ───────────────────────────────────────────────
    try:
        r = c("search_kb", {"terms": ["error"], "level": "Quick"})
        ok = check("search_kb Quick — returns results dict", r, [
            ("total",  lambda v: isinstance(v, int),  "should be int"),
            ("level",  lambda v: v == "Quick",         "should be 'Quick'"),
            ("phases", lambda v: isinstance(v, dict), "should be dict"),
        ])
        passed += ok; failed += not ok
    except Exception as ex:
        print(f"[FAIL] search_kb Quick — exception: {ex}"); failed += 1

    # ── Test 2: search_kb Standard with query ─────────────────────────────────
    try:
        r = c("search_kb", {"terms": ["tune", "fail"], "query": "tune failure on worldbox", "level": "Standard"})
        ok = check("search_kb Standard — domain auto-detect", r, [
            ("total",   lambda v: isinstance(v, int),  "should be int"),
            ("domains", lambda v: isinstance(v, list), "should be list"),
        ])
        passed += ok; failed += not ok
    except Exception as ex:
        print(f"[FAIL] search_kb Standard — exception: {ex}"); failed += 1

    # ── Test 3: search_kb invalid level falls back gracefully ─────────────────
    try:
        r = c("search_kb", {"terms": ["test"], "level": "Bogus"})
        ok = check("search_kb — invalid level falls back gracefully", r, [
            ("total", lambda v: isinstance(v, int), "should be int"),
        ])
        passed += ok; failed += not ok
    except Exception as ex:
        print(f"[FAIL] search_kb invalid level — exception: {ex}"); failed += 1

    # -- Test 4: search_kb missing terms returns error -------------------------
    try:
        session_id = initialize(url, token)
        def c(tool, a): return call(url, token, tool, a, session_id)  # noqa: F811
    except Exception:
        pass
    try:
        r = c("search_kb", {})
        content = r.get("result", {}).get("content", [])
        text = content[0].get("text", "") if content else ""
        ok = "error" in text.lower() or "required" in text.lower()
        print(f"[ OK ] search_kb -- missing terms returns error" if ok
              else "[FAIL] search_kb -- missing terms should return error")
        passed += ok; failed += not ok
    except Exception as ex:
        print(f"[FAIL] search_kb missing terms -- exception: {ex}"); failed += 1

    # ── Test 5: search_jira top mode ─────────────────────────────────────────
    try:
        r = c("search_jira", {"terms": ["error"], "mode": "top"})
        ok = check("search_jira top — returns dpstriage + postrca lists", r, [
            ("dpstriage", lambda v: isinstance(v, list), "should be list"),
            ("postrca",   lambda v: isinstance(v, list), "should be list"),
            ("mode",      lambda v: v == "top",          "should be 'top'"),
        ])
        passed += ok; failed += not ok
    except Exception as ex:
        print(f"[FAIL] search_jira top — exception: {ex}"); failed += 1

    # ── Test 6: search_jira count mode ───────────────────────────────────────
    try:
        r = c("search_jira", {"terms": ["fail"], "mode": "count"})
        ok = check("search_jira count — returns integer counts", r, [
            ("dpstriage_count", lambda v: isinstance(v, int), "should be int"),
            ("postrca_count",   lambda v: isinstance(v, int), "should be int"),
        ])
        passed += ok; failed += not ok
    except Exception as ex:
        print(f"[FAIL] search_jira count — exception: {ex}"); failed += 1

    # ── Test 7: search_jira oldest mode ──────────────────────────────────────
    try:
        r = c("search_jira", {"terms": ["error"], "mode": "oldest"})
        ok = check("search_jira oldest — returns oldest dict or None", r, [
            ("mode", lambda v: v == "oldest", "should be 'oldest'"),
        ])
        passed += ok; failed += not ok
    except Exception as ex:
        print(f"[FAIL] search_jira oldest — exception: {ex}"); failed += 1

    # -- Test 8: search_jira missing terms returns error -----------------------
    try:
        session_id = initialize(url, token)
        def c(tool, a): return call(url, token, tool, a, session_id)  # noqa: F811
    except Exception:
        pass
    try:
        r = c("search_jira", {})
        content = r.get("result", {}).get("content", [])
        text = content[0].get("text", "") if content else ""
        ok = "error" in text.lower() or "required" in text.lower()
        print(f"[ OK ] search_jira -- missing terms returns error" if ok
              else "[FAIL] search_jira -- missing terms should return error")
        passed += ok; failed += not ok
    except Exception as ex:
        print(f"[FAIL] search_jira missing terms -- exception: {ex}"); failed += 1

    # ── Test 9: build_index — callable, returns status dict ──────────────────
    try:
        r = c("build_index", {"force_full": False})
        content = r.get("result", {}).get("content", [{}])
        data = json.loads(content[0].get("text", "{}")) if content else {}
        ok = "status" in data
        print(f"[ OK ] build_index — returns status dict" if ok
              else "[FAIL] build_index — expected 'status' key in response")
        passed += ok; failed += not ok
    except Exception as ex:
        print(f"[FAIL] build_index — exception: {ex}"); failed += 1

    print(f"\n{'-'*50}")
    print(f"Results: {passed} passed, {failed} failed\n")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

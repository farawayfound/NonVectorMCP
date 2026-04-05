# vpoRAG MCP Server — Client Setup

## Server Details

| | |
|---|---|
| Host | `127.0.0.1` |
| Port | `8000` |
| MCP endpoint | `http://127.0.0.1:8000/mcp` |
| Auth | Per-user Bearer token — see [User Identity Setup](#user-identity-setup) below |

---

## VS Code Configuration

The MCP server is configured in Amazon Q's agent config file:
```
C:\Users\<you>\.aws\amazonq\agents\default.json
```

Add the `vpoMac` entry under `mcpServers`:

```json
{
  "mcpServers": {
    "vpoMac": {
      "url": "http://127.0.0.1:8000/mcp",
      "disabled": false,
      "timeout": 0,
      "headers": {
        "Authorization": "Bearer vporag-<EMP_ID>"
      }
    }
  }
}
```

Replace `<PID>` with your 7-digit Windows PID (e.g. `vporag-P3315113` for user `P3315113`).

> **Note:** The `headers` block can also be set via the Amazon Q UI. In VS Code, open the
> Amazon Q panel → click **Configure MCP** → select the `vpoMac` server → add a header with
> Key: `Authorization` and Value: `Bearer vporag-P<7digits>` (replace with your actual PID).

After saving, restart VS Code. Amazon Q will automatically discover and call `search_kb`,
`search_jira`, and `build_index` tools during triage sessions.

---

## User Identity Setup

No admin action is required to add new users. Tokens matching the pattern `vporag-P<7digits>`
(e.g. `vporag-P3315113`) are **auto-registered on first use** — the server derives the display
name from the token, persists it to `auth_tokens.json` on the server, and logs a `user_registered`
event. The engineer only needs to set their header once in VS Code.

### Engineer setup (one-time)

Open the Amazon Q panel in VS Code → click **Configure MCP** → select the `vpoMac` server.
Add a header:

| Key | Value |
|-----|-------|
| `Authorization` | `Bearer vporag-<PID>` |

Replace `<PID>` with your 7-digit Windows PID (e.g. `P3315113` → value is `Bearer vporag-P3315113`).

Alternatively, edit `C:\Users\<you>\.aws\amazonq\agents\default.json` directly:
```json
"headers": { "Authorization": "Bearer vporag-P3315113" }
```

On the next tool call, the server auto-registers the token and all subsequent requests appear
in the access log and MCP Dashboard under your identity.

### Token rules
- Pattern: `vporag-P` followed by exactly 7 digits (case-insensitive on input, stored as uppercase)
- Tokens not matching this pattern are ignored and the request is logged as `anonymous`
- No token or non-matching token = **401 Unauthorized** — requests are blocked (`REQUIRE_AUTH = True`)
- Auto-registered tokens persist in `mcp_server/auth_tokens.json` (gitignored) and survive server restarts

### Admin: pre-seeding or overriding tokens

To pre-seed a token or override a display name, add it to `AUTH_TOKENS` in
`/srv/vpo_rag/mcp_server/config.py` — static entries take precedence over auto-registered ones:
```python
AUTH_TOKENS = {
    "vporag-P3315113": "P3315113",  # optional override
}
```
To disable enforcement (allow anonymous access), set `REQUIRE_AUTH = False` and restart the service.

---

## Available Tools

### `search_kb`
Searches the centralized JSONL knowledge base. Replaces `Search-DomainAware.ps1`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `terms` | `list[str]` | required | Search terms |
| `query` | `str` | `""` | Natural language query for domain auto-detection |
| `level` | `str` | `"Standard"` | `Quick` / `Standard` / `Deep` / `Exhaustive` |
| `domains` | `list[str]` | `[]` | Override domain list (auto-detected if empty) |
| `max_results` | `int` | `0` | Cap on chunks returned (0 = level default) |

### `search_jira`
Searches Jira tickets via MySQL with CSV fallback. Replaces `Search-JiraTickets.ps1`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `terms` | `list[str]` | required | Search terms |
| `discovered` | `list[str]` | `[]` | Additional terms from KB search |
| `mode` | `str` | `"top"` | `top` / `count` / `oldest` / `custom` |
| `limit` | `int` | `0` | Max results per ticket type (0 = mode default) |
| `since` | `int` | `0` | Months back to search (0 = no limit) |
| `ticket_type` | `str` | `"both"` | `both` / `dpstriage` / `postrca` |
| `status` | `list[str]` | `[]` | Filter by status (or preset: `active` / `resolved`) |
| `client` | `str` | `""` | Filter by client name (partial match) |

### `build_index`
Triggers a KB rebuild on the server.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `force_full` | `bool` | `false` | Delete processing state before build (full rebuild) |

---

## Quick Connectivity Test

Run from your Windows machine to verify the server is reachable:

```powershell
# Step 1: Initialize session (required before any tool call)
$init = @{ jsonrpc="2.0"; id=0; method="initialize"; params=@{ protocolVersion="2024-11-05"; capabilities=@{}; clientInfo=@{ name="test"; version="1.0" } } } | ConvertTo-Json -Depth 5
$resp = Invoke-WebRequest -Uri "http://192.168.1.29:8000/mcp" -Method POST `
    -ContentType "application/json" -Headers @{ Accept="application/json, text/event-stream" } `
    -Body $init
$sessionId = $resp.Headers["mcp-session-id"]
Write-Host "Session: $sessionId"

# Step 2: Call search_kb (replace <PID> with your PID, e.g. p3315113)
$body = '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_kb","arguments":{"terms":["test"],"level":"Quick"}}}'
$result = Invoke-WebRequest -Uri "http://192.168.1.29:8000/mcp" -Method POST `
    -ContentType "application/json" `
    -Headers @{ Accept="application/json, text/event-stream"; "mcp-session-id"=$sessionId; Authorization="Bearer vporag-<PID>" } `
    -Body $body
# Parse SSE response (lines starting with "data: ")
($result.Content -split "`n" | Where-Object { $_ -match '^data: ' }) -replace '^data: ' | ConvertFrom-Json | ConvertTo-Json -Depth 5
```

Or use the Python test script (handles the session handshake automatically):

```bash
python mcp_server/scripts/test_mcp.py
```

---

## CSV Drop Workflow

Engineers export Jira CSVs and drop them into the Samba share. The `vporag-csv-sync` service
detects each new file automatically and processes it without any manual steps.

### Folder structure (per ticket type)

```
/srv/samba/share/dpstriageCSV/
├── <latest>.csv          ← drop new exports here
├── archive/
│   └── <name>_20250601_143022.csv   ← previous exports (timestamped)
└── invalid/
    └── <name>_20250601_143022.csv   ← rejected files (timestamped)
```

Same structure applies to `postrcaCSV/`.

### What happens on drop

| Step | Action |
|------|--------|
| 1 | `csv_watcher.py` detects the new file via `inotify` |
| 2 | **Validate** — checks UTF-8 encoding, required columns (`Issue key`, `Status`, `Summary`, `Created`, `Updated`), and at least one data row |
| 3a | **Invalid** → moved to `invalid/<name>_<timestamp>.csv`, warning logged, no DB changes |
| 3b | **Valid** → ingest script runs (`ingest_jira_csv.py` or `ingest_postrca_csv.py`) |
| 4 | Ingest upserts rows into MySQL (skips rows where `Updated` is not newer) |
| 5 | All older CSVs in the drop folder are moved to `archive/<name>_<timestamp>.csv` |
| 6 | If ingest fails (non-zero exit) → file moved to `invalid/` to prevent retry loops |

### Validation rules

A CSV is rejected if any of the following are true:
- File cannot be decoded as UTF-8 (or UTF-8-BOM)
- Missing any of: `Issue key`, `Status`, `Summary`, `Created`, `Updated`
- Zero data rows (header-only file)

### Config keys (`config.py`)

| Key | Default | Purpose |
|-----|---------|--------|
| `DPSTRIAGE_CSV_DIR` | `/srv/samba/share/dpstriageCSV` | DPSTRIAGE drop folder |
| `POSTRCA_CSV_DIR` | `/srv/samba/share/postrcaCSV` | POSTRCA drop folder |
| `CSV_WATCHER_LOG` | `/srv/samba/share/csv_watcher.log` | Watcher log file |
| `PYTHON_BIN` | `/srv/vpo_rag/venv/bin/python` | Python interpreter for ingest scripts |

---


When the MCP server is unreachable, the existing PowerShell scripts work unchanged:

```powershell
powershell -Command "& 'Searches\Scripts\Search-DomainAware.ps1' -Terms 'term1','term2' -Query 'full query'"
powershell -Command "& 'Searches\Scripts\Search-JiraTickets.ps1' -Terms 'term1','term2'"
```

Requires `Searches/config.ps1` with `$JSON_KB_DIR` pointing to a local JSONL copy (via `git pull`).

---

## Initial MySQL Setup (one-time)

Run `mcp_server/scripts/setup_remote_mysql_schema.sql` once in MySQL Workbench on the MCP server to create the `jira_db` database and its tables (`dpstriage`, `postrca`, `csv_imports`, `sync_log`). Required before `sync_local_db.py` can pull data.

```bash
# Or from the server CLI:
mysql -u root -p < /srv/vpo_rag/mcp_server/scripts/setup_remote_mysql_schema.sql
```

---

## Deploying Server-Side Changes

MCP server files are owned by `vporag`. To deploy updates from your Windows machine:

**One-time setup** (run once on the server as root to grant passwordless deploy access):
```bash
ssh vpomac@192.168.1.29
sudo python3 /srv/vpo_rag/Setup/Remote/setup_deploy_sudo.py
```

**Deploy updated tool files** (from Windows, after one-time setup):
```powershell
powershell -File Setup\Deploy-MCPServer.ps1
# Deploy specific files only:
powershell -File Setup\Deploy-MCPServer.ps1 -Files search_kb,search_jira
```

---

## Server Management (SSH)

```bash
ssh vpomac@192.168.1.29

# MCP server
sudo systemctl status vporag-mcp
sudo systemctl restart vporag-mcp
sudo journalctl -u vporag-mcp -f

# CSV watcher
sudo systemctl status vporag-csv-sync
sudo systemctl restart vporag-csv-sync
sudo journalctl -u vporag-csv-sync -f
tail -f /srv/samba/share/csv_watcher.log   # watcher + ingest combined log

# Access logs (structured JSONL — one record per event)
tail -f /srv/vpo_rag/JSON/logs/mcp_access.log
# Rotated daily, 30 days retained: mcp_access.log.YYYY-MM-DD

# Trigger index rebuild via SSH
sudo -u vporag /srv/vpo_rag/venv/bin/python /srv/vpo_rag/mcp_server/scripts/run_build.sh
```

---

## Access Logging

All tool calls are logged to `/srv/vpo_rag/JSON/logs/mcp_access.log` in JSONL format (one JSON record per line). Rotated daily at UTC midnight, 30 days retained.

### Event types

| `event` | When | Key fields |
|---------|------|------------|
| `request_start` | Every HTTP request received | `method`, `path`, `client_ip`, `client_port`, `user_agent`, `mcp_session_id` |
| `request_end` | Request completed normally | `http_status`, `duration_ms` |
| `request_error` | Unhandled exception in middleware | `error_type`, `error`, `duration_ms` |
| `search_kb` | KB search completed | `terms`, `query`, `level`, `domains`, `chunks_returned`, `phase_counts`, `duration_ms` |
| `search_jira` | Jira search completed | `terms`, `mode`, `ticket_type`, `source`, `dps_rows`, `rca_rows`, `sql_error`, `duration_ms` |
| `build_index` | Index build completed | `force_full`, `exit_code`, `duration_ms` |
| `tool_error` | Exception inside a tool function | `tool`, `error_type`, `error`, `duration_ms` |
| `user_registered` | First-time auto-registration of a valid token | `token`, `user_id`, `client_ip` |

All records also include: `timestamp` (UTC ISO-8601), `pid`, `request_id`, `client_ip`, `client_port`, `user_agent`, `mcp_session_id`, `user_id`.

### Example record
```json
{"timestamp": "2026-03-18T11:55:01Z", "event": "search_kb", "pid": 96747, "request_id": "a3f9c1d2e4b5", "client_ip": "192.168.1.65", "client_port": 63174, "user_agent": "node", "mcp_session_id": "d49a78d6398346078a06b19cab474e05", "user_id": "P3315113", "terms": ["xumo", "auth"], "level": "Standard", "chunks_returned": 142, "phase_counts": {"Initial": 45, "Related": 55, "Query": 42}, "duration_ms": 312}
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `Connection refused` on port 8000 | `sudo systemctl status vporag-mcp` — service may be down |
| `401 Unauthorized` | No token or wrong format — `Authorization` header must be `Bearer vporag-P<7digits>` |
| Showing as `anonymous` in logs | Should not occur with enforcement on — if seen, token bypassed pattern check |
| `search_kb` returns 0 results | JSONL files may not exist yet — run `build_index(force_full=True)` |
| `search_jira` returns CSV warning | MySQL is down or credentials missing — CSV fallback is active |
| Build tool returns `"status": "busy"` | Another build is running — wait and retry |
| Dropped CSV not ingested | Check `csv_watcher.log` — file may be in `invalid/` (validation failed) or ingest errored |
| CSV in `invalid/` folder | Open the file — check for non-UTF-8 encoding or missing `Issue key`/`Status`/`Summary`/`Created`/`Updated` columns |
| `vporag-csv-sync` not running | `sudo systemctl start vporag-csv-sync` — check `DPSTRIAGE_CSV_DIR`/`POSTRCA_CSV_DIR` exist on disk |
| Tool errors not surfacing | Check `mcp_access.log` for `tool_error` events — exceptions are caught and logged there |

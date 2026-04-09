# -*- coding: utf-8 -*-
"""
Server-side paths and settings for the MCP server.
Copy to config.py and adjust for your environment.
config.py is gitignored — never commit it.
"""
import os

JSON_KB_DIR      = "/srv/vpo_rag/JSON"
JIRA_CSV_DIR     = "/srv/vpo_rag/mcp_server/data/JiraCSVexport/current"
JIRA_CSV_ARCHIVE = "/srv/vpo_rag/mcp_server/data/JiraCSVexport/archive"
REPO_DIR         = "/srv/vpo_rag"
INDEXER_SCRIPT   = "/srv/vpo_rag/indexers/build_index.py"

# CSV drop-folder watcher (csv_watcher.py / vporag-csv-sync.service)
# Engineers drop new Jira CSV exports into these folders via Samba.
# archive/ and invalid/ subdirectories are created automatically.
DPSTRIAGE_CSV_DIR = "/srv/samba/share/dpstriageCSV"
POSTRCA_CSV_DIR   = "/srv/samba/share/postrcaCSV"
CSV_WATCHER_LOG   = "/srv/samba/share/csv_watcher.log"
PYTHON_BIN        = "/srv/vpo_rag/venv/bin/python"

# Search result cache TTL (seconds); 0 = LRU only
SEARCH_RESULT_CACHE_TTL_SEC = float(os.environ.get("SEARCH_RESULT_CACHE_TTL_SEC", "300"))

# Per-user bearer tokens for identity logging.
# Tokens matching the pattern "vporag-P<7digits>" are auto-registered on first use
# and persisted to auth_tokens.json (sidecar file, gitignored) — no admin action needed.
# Add entries here only to pre-seed tokens or override a display name.
# REQUIRE_AUTH = True blocks requests with no valid token (returns 401).
# Set to False to allow anonymous access (soft mode — logs identity when present).
AUTH_TOKENS = {
    # "vporag-P3315113": "P3315113",  # pre-seeded example
}
REQUIRE_AUTH = True

# Jira SQL connection (ODBC Driver 18 on Ubuntu 24.04)
JIRA_SQL_SERVER   = r"VM0PWVPTSPL000"
JIRA_SQL_DATABASE = "VIDPROD_MAIN"
JIRA_SQL_DRIVER   = "ODBC Driver 18 for SQL Server"

# Keyring backend for headless Linux
KEYRING_BACKEND = "keyrings.alt.file.PlaintextKeyring"

# MySQL local database (primary Jira source on server)
MYSQL_HOST = "localhost"
MYSQL_PORT = 3306
MYSQL_DB   = "jira_db"
MYSQL_USER = "jira_user"
MYSQL_PASS = os.environ.get("MYSQL_PASS", "")  # Injected from /etc/vporag/mcp.env

# Jira source strategy
# "mysql"  — server-side MySQL jira_db (fastest, requires ingest_jira_csv.py to have run)
# "sql"    — query VIDPROD_MAIN directly via pyodbc (requires network access to SQL server)
# "csv"    — read CSV files from JIRA_CSV_DIR (always available as fallback)
JIRA_PRIMARY_SOURCE      = "mysql"
JIRA_SEARCH_BOTH_SOURCES = False  # True = merge primary + CSV results

# MCP output cap — hard ceiling on chunks returned per search_kb call.
# Amazon Q enforces a 100K character limit on MCP tool output.
# Measured output sizes (Quick, 3 representative queries):
#   worst-case: 66,609 chars at 15 chunks (auth/entitlement, p90 chunk = 6,030 chars)
#   headroom at 15 chunks: 33,391 chars = ~5 extra chunks at p90
# 20 chunks worst-case ≈ 96,759 chars — within limit with ~3K headroom.
# text_raw, key_phrases, nlp_entities are stripped from output to achieve this size.
# This value overrides the level's Total if lower. Set to 0 to disable.
MCP_MAX_RESULTS = 20

# -*- coding: utf-8 -*-
"""Server-side paths and settings for the MCP server."""
import os

JSON_KB_DIR      = "/srv/vpo_rag/JSON"
JIRA_CSV_DIR     = "/srv/vpo_rag/mcp_server/data/JiraCSVexport/current"
JIRA_CSV_ARCHIVE = "/srv/vpo_rag/mcp_server/data/JiraCSVexport/archive"
REPO_DIR         = "/srv/vpo_rag"
INDEXER_SCRIPT   = "/srv/vpo_rag/indexers/build_index.py"
AUTH_TOKEN       = ""  # Set to a shared secret for local-network auth

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

# Jira source strategy — mirrors $JIRA_PRIMARY_SOURCE / $JIRA_SEARCH_BOTH_SOURCES in config.ps1
JIRA_PRIMARY_SOURCE      = "mysql"  # "mysql" | "sql" (SSMS/remote) | "csv"
JIRA_SEARCH_BOTH_SOURCES = False    # True = merge primary + CSV results

# CSV drop-folder watcher (csv_watcher.py / vporag-csv-sync.service)
DPSTRIAGE_CSV_DIR = "/srv/samba/share/dpstriageCSV"
POSTRCA_CSV_DIR   = "/srv/samba/share/postrcaCSV"
CSV_WATCHER_LOG   = "/srv/samba/share/csv_watcher.log"
PYTHON_BIN        = "/srv/vpo_rag/venv/bin/python"

# Search result cache TTL (seconds); 0 = LRU only, no expiry
SEARCH_RESULT_CACHE_TTL_SEC = float(os.environ.get("SEARCH_RESULT_CACHE_TTL_SEC", "300"))

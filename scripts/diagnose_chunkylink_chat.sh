#!/usr/bin/env bash
# ChunkyPotato chat / Ollama diagnostics for a nanobot-style Linux host.
# Run on the server: bash scripts/diagnose_chunkylink_chat.sh
set -euo pipefail

CHUNKYLINK_URL="${CHUNKYLINK_URL:-http://127.0.0.1:8000}"

echo "=== systemd: chunkylink (last 40 lines) ==="
journalctl -u chunkylink -n 40 --no-pager 2>/dev/null || echo "(not available — run on host with systemd)"

echo
echo "=== systemd: ollama (last 30 lines) ==="
journalctl -u ollama -n 30 --no-pager 2>/dev/null || echo "(not available)"

echo
echo "=== GET $CHUNKYLINK_URL/api/chat/health ==="
curl -sS "${CHUNKYLINK_URL}/api/chat/health" | head -c 2000 || echo "curl failed"

echo
echo
echo "=== ollama list (local) ==="
if command -v ollama >/dev/null 2>&1; then
  ollama list 2>/dev/null || true
  echo
  echo "=== ollama ps ==="
  ollama ps 2>/dev/null || true
else
  echo "ollama CLI not in PATH"
fi

echo
echo "Done. For nginx timeouts, check: grep -i timeout /var/log/nginx/error.log"

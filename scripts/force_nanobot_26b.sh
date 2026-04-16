#!/usr/bin/env bash
set -euo pipefail

echo "==> pre-check /api/ps"
curl -sS -m 10 http://127.0.0.1:11434/api/ps || true
echo

echo "==> try unload e4b (best-effort)"
ollama stop gemma4:e4b >/dev/null 2>&1 || true

echo "==> generate with gemma4:26b num_ctx=32000"
curl -sS -m 300 http://127.0.0.1:11434/api/generate \
  -H "Content-Type: application/json" \
  --data-binary @- <<'JSON'
{"model":"gemma4:26b","prompt":"Reply exactly: OK","stream":false,"options":{"num_ctx":32000},"keep_alive":"24h"}
JSON
echo
echo "==> probe lower num_ctx values (find workable floor)"
for CTX in 65536 32768 24576 16384 12288 8192; do
  echo "CTX=${CTX}"
  curl -sS -m 180 http://127.0.0.1:11434/api/generate \
    -H "Content-Type: application/json" \
    --data-binary @- <<JSON
{"model":"gemma4:26b","prompt":"OK","stream":false,"options":{"num_ctx":${CTX}},"keep_alive":"30m"}
JSON
  echo
done
echo "==> post-check /api/ps"
curl -sS -m 10 http://127.0.0.1:11434/api/ps || true
echo

#!/usr/bin/env bash
# Apply gemma4:26b + 128k worker defaults on nanobot: updated compose (Ollama env + memory limit),
# patch .env.nanobot, stop duplicate host ollama, recreate stack, pull model.
#
# Run ON nanobot as root (after copying this script + docker-compose.nanobot.yml from the repo), e.g.:
#   sudo bash ~/nanobot-fix/apply_nanobot_ollama_fix.sh
#
set -euo pipefail

[[ "${EUID:-0}" -eq 0 ]] || { echo "Run as root: sudo bash $0"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${CHUNKYLINK_REPO:-/srv/chunkylink/repo}"
COMPOSE_REL="docker/docker-compose.nanobot.yml"
COMPOSE_ABS="${REPO}/${COMPOSE_REL}"
SRC_COMPOSE="${SCRIPT_DIR}/docker-compose.nanobot.yml"

if [[ ! -f "$SRC_COMPOSE" ]]; then
  echo "ERROR: ${SRC_COMPOSE} not found (copy docker-compose.nanobot.yml next to this script)."
  exit 1
fi
if [[ ! -d "$REPO" ]]; then
  echo "ERROR: ${REPO} not found."
  exit 1
fi

_ts="$(date +%s)"
cp -a "$COMPOSE_ABS" "${COMPOSE_ABS}.bak.${_ts}" 2>/dev/null || true
cp -a "${REPO}/.env.nanobot" "${REPO}/.env.nanobot.bak.${_ts}" 2>/dev/null || true

install -m 0644 "$SRC_COMPOSE" "$COMPOSE_ABS"
chown chunkylink:chunkylink "$COMPOSE_ABS" 2>/dev/null || true

ENV_FILE="${REPO}/.env.nanobot"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: ${ENV_FILE} missing."
  exit 1
fi
if grep -q '^OLLAMA_MODEL=' "$ENV_FILE"; then
  sed -i 's/^OLLAMA_MODEL=.*/OLLAMA_MODEL=gemma4:26b/' "$ENV_FILE"
else
  echo 'OLLAMA_MODEL=gemma4:26b' >> "$ENV_FILE"
fi
if grep -q '^OLLAMA_NUM_CTX=' "$ENV_FILE"; then
  sed -i 's/^OLLAMA_NUM_CTX=.*/OLLAMA_NUM_CTX=131072/' "$ENV_FILE"
else
  echo 'OLLAMA_NUM_CTX=131072' >> "$ENV_FILE"
fi
chown chunkylink:chunkylink "$ENV_FILE" 2>/dev/null || true

# Free port 11434 for Docker only; avoid two Ollama servers.
if systemctl is-active --quiet ollama 2>/dev/null; then
  echo "==> stopping host ollama service (Docker owns 11434)"
  systemctl stop ollama
fi

_nanobot_docker() {
  if command -v docker >/dev/null 2>&1; then command -v docker; return 0; fi
  for c in /usr/bin/docker /usr/local/bin/docker /snap/bin/docker; do
    [[ -x "$c" ]] && { echo "$c"; return 0; }
  done
  return 1
}

DOCKER_BIN="$(_nanobot_docker)" || { echo "ERROR: docker not found"; exit 1; }
cd "$REPO"
echo "==> docker compose up (${DOCKER_BIN})"
"${DOCKER_BIN}" compose -f "${COMPOSE_REL}" up -d

echo "==> ollama pull gemma4:26b (inside container)"
"${DOCKER_BIN}" compose -f "${COMPOSE_REL}" exec -T ollama ollama pull gemma4:26b

echo "==> done. Check: docker compose -f ${COMPOSE_REL} exec ollama ollama ps"
echo "    Worker num_ctx is pushed from M1 backend Redis; ensure WORKER_OLLAMA_NUM_CTX=131072 in backend .env or Admin."

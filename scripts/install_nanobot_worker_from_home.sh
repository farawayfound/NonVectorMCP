#!/usr/bin/env bash
# Install worker bundle from david's home into /srv/chunkylink/repo and start stack.
# Run on nanobot as root:
#   sudo bash ~/chunkylink-nanobot-staging/install_nanobot_worker_from_home.sh
#
set -euo pipefail

# When run via `sudo`, HOME is root — use the invoking user's home for the staging dir.
if [[ -n "${SUDO_USER:-}" ]]; then
  STAGE="/home/${SUDO_USER}/chunkylink-nanobot-staging"
else
  STAGE="${HOME}/chunkylink-nanobot-staging"
fi
REPO="${CHUNKYLINK_REPO:-/srv/chunkylink/repo}"

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Run with sudo."
  exit 1
fi

# sudo uses a minimal PATH — Docker is often in /usr/local/bin or snap.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH="${PATH}:/snap/bin:/var/lib/snapd/snap/bin"

_nanobot_docker() {
  if command -v docker >/dev/null 2>&1; then
    command -v docker
    return 0
  fi
  local c
  for c in /usr/bin/docker /usr/local/bin/docker /snap/bin/docker; do
    [[ -x "$c" ]] && { echo "$c"; return 0; }
  done
  return 1
}

if [[ ! -d "$STAGE/worker" ]]; then
  echo "ERROR: $STAGE/worker not found. Run Sync-NanobotWorker.ps1 from your dev machine first."
  exit 1
fi

mkdir -p "${REPO}/docker" "${REPO}/worker" "${REPO}/scripts"

echo "==> Copy worker + compose into ${REPO}"
cp -a "${STAGE}/worker/." "${REPO}/worker/"
cp -a "${STAGE}/docker/docker-compose.nanobot.yml" "${REPO}/docker/"
install -m 0755 "${STAGE}/deploy_nanobot_worker.sh" "${REPO}/scripts/deploy_nanobot_worker.sh"
cp -a "${STAGE}/.env.nanobot.example" "${REPO}/.env.nanobot.example"

if [[ ! -f "${REPO}/.env.nanobot" ]]; then
  echo ""
  echo "WARN: ${REPO}/.env.nanobot does not exist — creating from example (EDIT REDIS_URL, M1_BASE_URL, NANOBOT_API_KEY)."
  cp "${REPO}/.env.nanobot.example" "${REPO}/.env.nanobot"
  chown chunkylink:chunkylink "${REPO}/.env.nanobot" 2>/dev/null || true
else
  # NEVER overwrite existing .env.nanobot — it holds live tuned values (OLLAMA_NUM_CTX,
  # NANOBOT_API_KEY, M1_BASE_URL, etc.) and is intentionally preserved across deploys.
  echo "==> ${REPO}/.env.nanobot already exists — preserving (tuned values survive redeploy)"
fi

chown -R chunkylink:chunkylink "${REPO}/worker" "${REPO}/docker/docker-compose.nanobot.yml" \
  "${REPO}/scripts/deploy_nanobot_worker.sh" "${REPO}/.env.nanobot.example" 2>/dev/null || true

COMPOSE_REL="docker/docker-compose.nanobot.yml"
DOCKER_BIN="$(_nanobot_docker)" || {
  echo "ERROR: docker not found. Install Docker Engine on nanobot, e.g.:"
  echo "  curl -fsSL https://get.docker.com | sudo sh"
  exit 1
}
echo "==> docker compose up (using ${DOCKER_BIN})"
cd "${REPO}"
if "${DOCKER_BIN}" compose version >/dev/null 2>&1; then
  "${DOCKER_BIN}" compose -f "${COMPOSE_REL}" up -d --build
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose -f "${COMPOSE_REL}" up -d --build
else
  echo "ERROR: need 'docker compose' (plugin) or docker-compose v1."
  exit 1
fi

echo "==> status"
if "${DOCKER_BIN}" compose version >/dev/null 2>&1; then
  "${DOCKER_BIN}" compose -f "${COMPOSE_REL}" ps
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose -f "${COMPOSE_REL}" ps
fi
echo "Done. Ensure ${REPO}/.env.nanobot matches your M1 Redis and API key."

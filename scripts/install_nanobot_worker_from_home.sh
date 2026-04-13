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
fi

chown -R chunkylink:chunkylink "${REPO}/worker" "${REPO}/docker/docker-compose.nanobot.yml" \
  "${REPO}/scripts/deploy_nanobot_worker.sh" "${REPO}/.env.nanobot.example" 2>/dev/null || true

echo "==> docker compose up"
cd "${REPO}"
docker compose -f docker/docker-compose.nanobot.yml up -d --build

echo "==> status"
docker compose -f docker/docker-compose.nanobot.yml ps
echo "Done. Ensure ${REPO}/.env.nanobot matches your M1 Redis and API key."

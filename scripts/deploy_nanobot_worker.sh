#!/usr/bin/env bash
# Deploy / refresh the Library worker stack on nanobot (Ryzen).
#
# Run ON nanobot with privileges to update the git checkout and run Docker, e.g.:
#   ssh -t david@nanobot 'sudo bash /srv/chunkylink/repo/scripts/deploy_nanobot_worker.sh'
#
# Or after copying this file into the repo:
#   sudo bash scripts/deploy_nanobot_worker.sh
#
# Environment (optional):
#   CHUNKYLINK_REPO=/srv/chunkylink/repo
#
set -euo pipefail

REPO="${CHUNKYLINK_REPO:-/srv/chunkylink/repo}"
COMPOSE_REL="docker/docker-compose.nanobot.yml"

cd "${REPO}"

if [[ ! -f "${COMPOSE_REL}" ]]; then
  echo "ERROR: ${REPO}/${COMPOSE_REL} not found."
  echo "Pull the latest ChunkyLink (Library worker) or sync worker/ + docker/docker-compose.nanobot.yml."
  exit 1
fi

if [[ ! -f "${REPO}/.env.nanobot" ]]; then
  echo "ERROR: ${REPO}/.env.nanobot is missing."
  echo "Copy .env.nanobot.example to .env.nanobot and set REDIS_URL, M1_BASE_URL, NANOBOT_API_KEY."
  exit 1
fi

# Git pull as repo owner when invoked as root (david uses sudo).
if [[ "${EUID:-0}" -eq 0 ]] && id chunkylink &>/dev/null; then
  echo "==> git pull (as chunkylink)"
  sudo -u chunkylink git -C "${REPO}" pull --ff-only
else
  echo "==> git pull"
  git pull --ff-only
fi

echo "==> docker compose up (nanobot stack)"
cd "${REPO}"
docker compose -f "${COMPOSE_REL}" up -d --build

echo "==> done"
docker compose -f "${COMPOSE_REL}" ps

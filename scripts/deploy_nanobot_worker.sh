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
#   NANOBOT_WORKER_OLLAMA_MODEL — tag passed to ``ollama pull`` after compose (default: gemma4:26b).
#   NANOBOT_SKIP_OLLAMA_PULL=1 — skip the post-deploy pull (e.g. air-gapped or custom models only).
#
set -euo pipefail

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

DOCKER_BIN="$(_nanobot_docker)" || {
  echo "ERROR: docker not found. Install Docker Engine, e.g.: curl -fsSL https://get.docker.com | sudo sh"
  exit 1
}
echo "==> docker compose up (nanobot stack, ${DOCKER_BIN})"
cd "${REPO}"
if "${DOCKER_BIN}" compose version >/dev/null 2>&1; then
  "${DOCKER_BIN}" compose -f "${COMPOSE_REL}" up -d --build
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose -f "${COMPOSE_REL}" up -d --build
else
  echo "ERROR: need 'docker compose' or docker-compose."
  exit 1
fi

DEFAULT_WORKER_OLLAMA_MODEL="${NANOBOT_WORKER_OLLAMA_MODEL:-gemma4:26b}"
if [[ "${NANOBOT_SKIP_OLLAMA_PULL:-0}" != "1" ]]; then
  echo "==> ollama pull ${DEFAULT_WORKER_OLLAMA_MODEL} (nanobot stack; no-op if already present)"
  "${DOCKER_BIN}" compose -f "${COMPOSE_REL}" exec -T ollama ollama pull "${DEFAULT_WORKER_OLLAMA_MODEL}" || \
    echo "WARN: ollama pull failed. When Ollama is ready: ${DOCKER_BIN} compose -f ${COMPOSE_REL} exec ollama ollama pull ${DEFAULT_WORKER_OLLAMA_MODEL}"
fi

echo "==> done"
if "${DOCKER_BIN}" compose version >/dev/null 2>&1; then
  "${DOCKER_BIN}" compose -f "${COMPOSE_REL}" ps
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose -f "${COMPOSE_REL}" ps
fi

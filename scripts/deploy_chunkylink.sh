#!/bin/bash
# ChunkyLink — deploy / refresh on the server (e.g. nanobot).
#
# Prerequisite: /srv/chunkylink/repo is a git clone with .env present (not committed).
#
# Usage (SSH'd in as a user with sudo):
#   sudo bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh
#
# Optional environment:
#   CHUNKYLINK_REPO=/srv/chunkylink/repo   — app root (git top)
#   CHUNKYLINK_VENV=/srv/chunkylink/venv   — Python venv for the service
#   DEPLOY_SKIP_NPM=1                      — skip frontend build (backend-only change)
#   GIT_REF=origin/main                    — ref to merge (default: fast-forward current branch)
#
set -euo pipefail

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE 2>/dev/null || true

REPO_RAW="${CHUNKYLINK_REPO:-/srv/chunkylink/repo}"
VENV="${CHUNKYLINK_VENV:-/srv/chunkylink/venv}"
OWNER="${CHUNKYLINK_OWNER:-chunkylink}"

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Run with sudo, e.g.: sudo bash $0"
  exit 1
fi

if [[ ! -d "${REPO_RAW}" ]]; then
  echo "Directory does not exist: ${REPO_RAW}"
  exit 1
fi

REPO="$(realpath "${REPO_RAW}")"

# Git 2.35+: sudo (root) + repo owned by ${OWNER} requires an explicit safe path.
if ! command git config --global --get-all safe.directory 2>/dev/null | grep -qxF "${REPO}"; then
  command git config --global --add safe.directory "${REPO}"
fi

if [[ ! -d "${REPO}/.git" ]]; then
  echo "ERROR: ${REPO} is not a git repository."
  echo "One-time setup: clone your repo as root, then chown to ${OWNER}:"
  echo "  sudo git clone <your-remote-url> ${REPO}"
  echo "  sudo cp /path/to/prod/.env ${REPO}/.env"
  echo "  sudo chown -R ${OWNER}:${OWNER} ${REPO}"
  exit 1
fi

cd "${REPO}"

echo "==> git fetch"
git fetch --prune origin

if [[ -n "${GIT_REF:-}" ]]; then
  echo "==> git merge --ff-only ${GIT_REF}"
  git merge --ff-only "${GIT_REF}"
else
  echo "==> git pull --ff-only"
  git pull --ff-only || {
    echo "Pull failed (local commits or diverged branch?). Resolve on the server or set GIT_REF=origin/<branch>."
    exit 1
  }
fi

if [[ -x "${VENV}/bin/pip" ]]; then
  echo "==> pip install -r requirements.txt"
  "${VENV}/bin/pip" install -r "${REPO}/requirements.txt" -q
else
  echo "WARNING: no pip at ${VENV}/bin/pip — skipping Python deps."
fi

if [[ "${DEPLOY_SKIP_NPM:-0}" != "1" && -f "${REPO}/frontend/package.json" ]]; then
  NVM_SH=""
  if [[ -n "${SUDO_USER:-}" && -f "/home/${SUDO_USER}/.nvm/nvm.sh" ]]; then
    NVM_SH="/home/${SUDO_USER}/.nvm/nvm.sh"
  fi
  if [[ -n "${NVM_SH}" ]]; then
    echo "==> frontend npm ci && npm run build (via ${NVM_SH})"
    NVM_DIR="$(dirname "${NVM_SH}")"
    export NVM_DIR
    bash -c ". \"${NVM_SH}\" && cd \"${REPO}/frontend\" && npm ci && npm run build"
  else
    echo "WARNING: Node not found (install nvm under your admin user, e.g. ~/.nvm, or set DEPLOY_SKIP_NPM=1 and build dist elsewhere)."
  fi
else
  echo "==> skipping frontend build (DEPLOY_SKIP_NPM=${DEPLOY_SKIP_NPM:-0})"
fi

echo "==> chown ${OWNER}:${OWNER} ${REPO}"
chown -R "${OWNER}:${OWNER}" "${REPO}"

echo "==> systemctl restart chunkylink"
systemctl restart chunkylink
sleep 2
systemctl is-active chunkylink
echo "==> done. If NLP / categories changed: Admin → Demo KB → Build Index."

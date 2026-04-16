#!/bin/bash
# ChunkyPotato — deploy / refresh on the server (e.g. nanobot).
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
#   DEPLOY_RESET_HARD=1                    — after fetch, reset --hard to origin/<current branch>
#                                            (discards local commits & uncommitted tracked changes; .env safe if gitignored)
#
set -euo pipefail

# This script is designed for Linux (systemd).
# On macOS (the Mac Mini setup), use the dedicated updater instead:
#   cd ~/chunkylink && git pull && bash scripts/setup_macmini.sh
if [[ "$(uname)" == "Darwin" ]]; then
  echo "ERROR: This script is for Linux/systemd only."
  echo "On macOS, update with: cd ~/chunkylink && git pull && bash scripts/setup_macmini.sh"
  exit 1
fi

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
WORKER_MODEL="${DEPLOY_WORKER_OLLAMA_MODEL:-gemma4:26b}"
WORKER_CTX="${DEPLOY_WORKER_OLLAMA_NUM_CTX:-131072}"

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

if ! command git remote get-url origin &>/dev/null; then
  echo "ERROR: Git remote 'origin' is not configured."
  echo "Deploy pulls from origin. Add it once (use your real URL):"
  echo "  sudo bash ${REPO}/scripts/link_chunkylink_git_remote.sh 'git@github.com:YOUR_USER/YOUR_REPO.git'"
  echo "Or with HTTPS:"
  echo "  sudo bash ${REPO}/scripts/link_chunkylink_git_remote.sh 'https://github.com/YOUR_USER/YOUR_REPO.git'"
  echo "Then push from this server if the remote is still empty:"
  echo "  sudo git -C ${REPO} push -u origin main"
  exit 1
fi

echo "==> git fetch (origin: $(command git remote get-url origin))"
git fetch --prune origin

BR="$(git rev-parse --abbrev-ref HEAD)"
if [[ "${BR}" == "HEAD" ]]; then
  echo "ERROR: detached HEAD; checkout a branch (e.g. main) before deploy."
  exit 1
fi
UPSTREAM="origin/${BR}"

if [[ "${DEPLOY_RESET_HARD:-0}" == "1" ]]; then
  echo "==> DEPLOY_RESET_HARD=1: git reset --hard ${UPSTREAM}"
  echo "    (tracked files match remote; uncommitted edits and local commits on this branch are discarded)"
  git reset --hard "${UPSTREAM}"
elif [[ -n "${GIT_REF:-}" ]]; then
  echo "==> git merge --ff-only ${GIT_REF}"
  git merge --ff-only "${GIT_REF}"
else
  echo "==> git pull --ff-only"
  git pull --ff-only || {
    echo "Pull failed: uncommitted changes, local commits, or diverged branch."
    echo "If GitHub is the source of truth, discard server drift and redeploy:"
    echo "  sudo DEPLOY_RESET_HARD=1 bash ${REPO}/scripts/deploy_chunkylink.sh"
    echo "Or manually: sudo git -C ${REPO} reset --hard ${UPSTREAM}"
    exit 1
  }
fi

if [[ -x "${VENV}/bin/pip" ]]; then
  echo "==> pip install -r requirements.txt"
  "${VENV}/bin/pip" install -r "${REPO}/requirements.txt" -q
else
  echo "WARNING: no pip at ${VENV}/bin/pip — skipping Python deps."
fi

# ── Redis (required for the Library/research queue) ─────────────────────────
echo "==> ensuring redis-server is installed and running"
if ! command -v redis-server &>/dev/null; then
  if command -v apt-get &>/dev/null; then
    DEBIAN_FRONTEND=noninteractive apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q redis-server
  elif command -v dnf &>/dev/null; then
    dnf install -y redis
  elif command -v yum &>/dev/null; then
    yum install -y redis
  else
    echo "WARNING: no supported package manager found to install redis — install it manually."
  fi
fi
if command -v systemctl &>/dev/null; then
  # Debian/Ubuntu names it redis-server; RHEL/Fedora uses redis
  for unit in redis-server redis; do
    if systemctl list-unit-files 2>/dev/null | awk '{print $1}' | grep -qx "${unit}.service"; then
      systemctl enable --now "${unit}" || true
      if systemctl is-active --quiet "${unit}"; then
        echo "    ${unit} is active"
      else
        echo "WARNING: ${unit} is not active — 'systemctl status ${unit}' for details"
      fi
      break
    fi
  done
fi
if command -v redis-cli &>/dev/null; then
  if redis-cli ping 2>/dev/null | grep -q PONG; then
    echo "    redis PING → PONG"
  else
    echo "WARNING: redis-cli ping did not return PONG — Library research submit will fail until redis is reachable"
  fi
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
    bash -c ". \"${NVM_SH}\" && cd \"${REPO}/frontend\" && npm install && npm run build"
  else
    echo "WARNING: Node not found (install nvm under your admin user, e.g. ~/.nvm, or set DEPLOY_SKIP_NPM=1 and build dist elsewhere)."
  fi
else
  echo "==> skipping frontend build (DEPLOY_SKIP_NPM=${DEPLOY_SKIP_NPM:-0})"
fi

# ── Force worker LLM defaults to 26B / 128k on deploy ──────────────────────
_upsert_env_kv() {
  local file="$1"
  local key="$2"
  local value="$3"
  if [[ ! -f "$file" ]]; then
    return 0
  fi
  if grep -qE "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${value}|g" "$file"
  else
    echo "${key}=${value}" >> "$file"
  fi
}

echo "==> aligning Library worker model defaults (${WORKER_MODEL}, ctx=${WORKER_CTX})"
_upsert_env_kv "${REPO}/.env" "WORKER_OLLAMA_MODEL" "${WORKER_MODEL}"
_upsert_env_kv "${REPO}/.env" "WORKER_OLLAMA_NUM_CTX" "${WORKER_CTX}"
_upsert_env_kv "${REPO}/.env.nanobot" "OLLAMA_MODEL" "${WORKER_MODEL}"
_upsert_env_kv "${REPO}/.env.nanobot" "OLLAMA_NUM_CTX" "${WORKER_CTX}"

# Persist runtime admin overrides so startup cannot re-seed stale e4b/8k.
if [[ -x "${VENV}/bin/python" ]]; then
  "${VENV}/bin/python" - "${REPO}" "${WORKER_MODEL}" "${WORKER_CTX}" <<'PY'
import json
import pathlib
import sys

repo = pathlib.Path(sys.argv[1])
model = sys.argv[2]
ctx = int(sys.argv[3])
cfg = repo / "data" / "admin_config.json"
if cfg.exists():
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        data["worker_ollama_model"] = model
        data["worker_ollama_num_ctx"] = ctx
        data["worker_ollama_migrated_v2"] = True
        cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"    updated {cfg}")
    except Exception as exc:
        print(f"WARNING: failed to update {cfg}: {exc}")
PY
fi

echo "==> chown ${OWNER}:${OWNER} ${REPO}"
chown -R "${OWNER}:${OWNER}" "${REPO}"

echo "==> systemctl restart chunkylink"
systemctl restart chunkylink
sleep 2
systemctl is-active chunkylink
echo "==> done. If NLP / categories changed: Admin → Demo KB → Build Index."

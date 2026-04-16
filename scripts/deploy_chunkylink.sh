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
WORKER_CTX="${DEPLOY_WORKER_OLLAMA_NUM_CTX:-32000}"

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

# ── Force worker LLM defaults to 26B / 32k on deploy ──────────────────────
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
# If this host also runs chunkylink backend (common on nanobot), its startup
# keepalive will load OLLAMA_MODEL into localhost Ollama. Align it too so no
# background process re-loads legacy e4b after restart.
_upsert_env_kv "${REPO}/.env" "OLLAMA_MODEL" "${WORKER_MODEL}"
_upsert_env_kv "${REPO}/.env" "OLLAMA_NUM_CTX" "${WORKER_CTX}"
_upsert_env_kv "${REPO}/.env.nanobot" "OLLAMA_MODEL" "${WORKER_MODEL}"
_upsert_env_kv "${REPO}/.env.nanobot" "OLLAMA_NUM_CTX" "${WORKER_CTX}"
if [[ -f "${REPO}/.env" ]]; then
  echo "    .env model keys:"
  grep -E '^OLLAMA_MODEL=|^OLLAMA_NUM_CTX=|^WORKER_OLLAMA_MODEL=|^WORKER_OLLAMA_NUM_CTX=' "${REPO}/.env" || true
fi
if [[ -f "${REPO}/.env.nanobot" ]]; then
  echo "    .env.nanobot model keys:"
  grep -E '^OLLAMA_MODEL=|^OLLAMA_NUM_CTX=' "${REPO}/.env.nanobot" || true
fi

# Persist runtime admin overrides so startup cannot re-seed stale e4b/8k.
if [[ -x "${VENV}/bin/python" ]]; then
  "${VENV}/bin/python" - "${REPO}" "${WORKER_MODEL}" "${WORKER_CTX}" <<'PY'
import json
import pathlib
import sys
import re

repo = pathlib.Path(sys.argv[1])
model = sys.argv[2]
ctx = int(sys.argv[3])
env_file = repo / ".env"
data_dir = repo / "data"
if env_file.exists():
    try:
        txt = env_file.read_text(encoding="utf-8")
        m = re.search(r"(?m)^DATA_DIR=(.+)$", txt)
        if m:
            raw = m.group(1).strip().strip('"').strip("'")
            data_dir = pathlib.Path(raw)
            if not data_dir.is_absolute():
                data_dir = (repo / data_dir).resolve()
    except Exception:
        pass
cfg = data_dir / "admin_config.json"
if cfg.exists():
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        # Backend startup keepalive uses ``ollama_model``/``num_ctx``; if these
        # stay on legacy e4b/4k they will immediately reload e4b after restart.
        data["ollama_model"] = model
        data["num_ctx"] = ctx
        data["worker_ollama_model"] = model
        data["worker_ollama_num_ctx"] = ctx
        data["worker_ollama_migrated_v2"] = True
        cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"    updated {cfg}")
    except Exception as exc:
        print(f"WARNING: failed to update {cfg}: {exc}")
else:
    print(f"    no admin_config at {cfg} (skipped)")
PY
fi

echo "==> chown ${OWNER}:${OWNER} ${REPO}"
chown -R "${OWNER}:${OWNER}" "${REPO}"

echo "==> systemctl restart chunkylink"
systemctl restart chunkylink
sleep 2
systemctl is-active chunkylink

# ── Enforce a single Ollama runtime and target model ────────────────────────
# Nanobot can end up with both:
#   1) host systemd ollama.service
#   2) docker compose ollama container on :11434
# This causes model drift/conflicts (e.g. e4b keeps coming back).
if command -v systemctl &>/dev/null; then
  if systemctl list-unit-files 2>/dev/null | awk '{print $1}' | grep -qx 'ollama.service'; then
    echo "==> disabling host ollama.service (docker ollama is the only runtime)"
    systemctl stop ollama || true
    systemctl disable ollama || true
  fi
fi

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

COMPOSE_REL="docker/docker-compose.nanobot.yml"
DOCKER_BIN="$(_nanobot_docker || true)"
if [[ -n "${DOCKER_BIN}" && -f "${REPO}/${COMPOSE_REL}" ]]; then
  echo "==> enforcing Ollama runtime model in docker (${WORKER_MODEL}, ctx=${WORKER_CTX})"
  # Ensure stack is up and only containerized Ollama serves :11434.
  "${DOCKER_BIN}" compose -f "${COMPOSE_REL}" up -d >/dev/null 2>&1 || true
  # Best-effort unload legacy model, pull target.
  "${DOCKER_BIN}" compose -f "${COMPOSE_REL}" exec -T ollama ollama stop gemma4:e4b >/dev/null 2>&1 || true
  if ! "${DOCKER_BIN}" compose -f "${COMPOSE_REL}" exec -T ollama ollama pull "${WORKER_MODEL}"; then
    echo "WARNING: ollama pull ${WORKER_MODEL} failed — warm load may still work if the model is already present."
  fi
  # Wait until Ollama answers (compose returns before the server is always ready).
  echo "    waiting for Ollama HTTP on :11434..."
  _ollama_ready=0
  for _i in {1..60}; do
    if curl -sf -m 3 "http://127.0.0.1:11434/api/tags" >/dev/null 2>&1; then
      _ollama_ready=1
      break
    fi
    sleep 2
  done
  if [[ "${_ollama_ready}" -ne 1 ]]; then
    echo "ERROR: Ollama did not become reachable on http://127.0.0.1:11434 within ~120s."
    echo "    Check: ${DOCKER_BIN} compose -f ${COMPOSE_REL} ps && ${DOCKER_BIN} compose -f ${COMPOSE_REL} logs ollama --tail 80"
    exit 1
  fi
  # Try configured num_ctx first, then smaller values. Very large ctx (e.g. 131072)
  # often fails to allocate KV on real hardware; errors were previously hidden by >/dev/null.
  _PS_JSON=""
  _USED_CTX=""
  for TRY_CTX in "${WORKER_CTX}" 98304 65536 32000 32768 16384; do
    [[ -n "${_USED_CTX}" ]] && break
    echo "    warm load: model=${WORKER_MODEL} num_ctx=${TRY_CTX} (empty prompt, keep_alive=24h)..."
    _GEN_TMP="$(mktemp)"
    _HTTP_CODE="$(curl -sS -m 1200 -o "${_GEN_TMP}" -w "%{http_code}" "http://127.0.0.1:11434/api/generate" \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"${WORKER_MODEL}\",\"prompt\":\"\",\"stream\":false,\"think\":false,\"options\":{\"num_ctx\":${TRY_CTX}},\"keep_alive\":\"24h\"}" || true)"
    if [[ "${_HTTP_CODE}" != "200" ]]; then
      echo "WARNING: /api/generate HTTP ${_HTTP_CODE} for num_ctx=${TRY_CTX}; body:"
      head -c 2000 "${_GEN_TMP}" || true
      echo
      rm -f "${_GEN_TMP}"
      continue
    fi
    _GEN_ERR="$(python3 -c "import json,sys; p=sys.argv[1]; d=json.load(open(p,encoding='utf-8')); print(d.get('error') or '')" "${_GEN_TMP}" 2>/dev/null || true)"
    if [[ -n "${_GEN_ERR}" ]]; then
      echo "WARNING: Ollama returned error for num_ctx=${TRY_CTX}: ${_GEN_ERR}"
      rm -f "${_GEN_TMP}"
      continue
    fi
    rm -f "${_GEN_TMP}"
    sleep 2
    _PS_JSON="$(curl -sS -m 15 "http://127.0.0.1:11434/api/ps" || true)"
    if echo "${_PS_JSON}" | python3 -c '
import json,sys
want=sys.argv[1].strip()
j=json.load(sys.stdin)
for r in j.get("models") or []:
    name=str(r.get("name") or r.get("model") or "").strip()
    if name == want:
        sys.exit(0)
sys.exit(1)
' "${WORKER_MODEL}" 2>/dev/null; then
      _USED_CTX="${TRY_CTX}"
    fi
  done
  if [[ -z "${_USED_CTX}" ]]; then
    echo "ERROR: Ollama runtime did not load ${WORKER_MODEL} into /api/ps after warm attempts."
    echo "    Current /api/ps:"
    echo "${_PS_JSON:-$(curl -sS -m 10 http://127.0.0.1:11434/api/ps || true)}"
    echo "    If you use a very large num_ctx (e.g. 131072), try WORKER_OLLAMA_NUM_CTX=32000 in .env and redeploy,"
    echo "    or run: ${DOCKER_BIN} compose -f ${COMPOSE_REL} logs ollama --tail 100"
    exit 1
  fi
  echo "    Ollama runtime loaded ${WORKER_MODEL} (warm num_ctx=${_USED_CTX})"
  if [[ "${_USED_CTX}" != "${WORKER_CTX}" ]]; then
    echo "WARNING: Deploy wanted num_ctx=${WORKER_CTX} but only num_ctx=${_USED_CTX} could be loaded."
    echo "    Lower WORKER_OLLAMA_NUM_CTX / OLLAMA_NUM_CTX in .env to ${_USED_CTX} (or less) so the app matches Ollama."
  fi
fi
echo "==> done. If NLP / categories changed: Admin → Demo KB → Build Index."

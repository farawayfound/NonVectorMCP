#!/bin/bash
# Run ON nanobot with sudo (needs a TTY for your password):
#   ssh -t david@nanobot.local 'sudo bash -s' < scripts/init_chunkylink_git_on_server.sh
# Or: scp this file to the server, then: sudo bash ./init_chunkylink_git_on_server.sh
#
# Creates /srv/chunkylink/repo as a git repo with .gitignore (no .env / dist / data),
# initial commit on branch main, and ownership chunkylink:chunkylink.
#
# After this, add your Git host and push (see scripts/link_chunkylink_git_remote.sh).
#
set -euo pipefail

# Stale GIT_* from the shell breaks `git -C` (Git uses GIT_DIR over -C).
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE 2>/dev/null || true

REPO="${CHUNKYLINK_REPO:-/srv/chunkylink/repo}"
OWNER="${CHUNKYLINK_OWNER:-chunkylink}"

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Run as root: sudo bash $0"
  exit 1
fi

if [[ -d "${REPO}/.git" ]]; then
  echo "Already a git repo: ${REPO}/.git — aborting."
  exit 1
fi

if [[ ! -d "${REPO}/backend" ]]; then
  echo "Expected ChunkyLink app at ${REPO} (missing backend/). Aborting."
  exit 1
fi

echo "==> Writing ${REPO}/.gitignore"
cat >"${REPO}/.gitignore" <<'GITIGNORE'
# Runtime data
data/
*.db

# Environment
.env
.env.local
.env.production

# Python
__pycache__/
*.pyc
*.pyo
*.egg-info/
dist/
build/
.venv/
venv/

# Node / Frontend
frontend/node_modules/
frontend/dist/
frontend/.vite/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Logs
*.log

# spaCy models (downloaded at runtime)
backend/indexers/utils/models/
GITIGNORE
chown "${OWNER}:${OWNER}" "${REPO}/.gitignore"

echo "==> git init (cwd: ${REPO})"
cd "${REPO}" || {
  echo "Cannot cd to ${REPO}"
  exit 1
}
command git init -b main
command git config user.name "ChunkyLink (nanobot)"
command git config user.email "chunkylink@nanobot.local"

echo "==> git add / commit"
command git add -A
if command git diff --cached --quiet; then
  echo "Nothing to commit (unexpected). Aborting."
  exit 1
fi
command git commit -m "Initial commit from production tree (nanobot)"

echo "==> chown ${OWNER}:${OWNER} ${REPO}"
chown -R "${OWNER}:${OWNER}" "${REPO}"

echo "==> done."
echo "    git log -1 --oneline"
command git log -1 --oneline
echo ""
echo "Next: add remote and push (needs Git auth on this machine), e.g.:"
echo "  sudo bash ~/link_chunkylink_git_remote.sh 'git@github.com:YOU/chunkylink.git'"
echo "  sudo git -C ${REPO} push -u origin main"

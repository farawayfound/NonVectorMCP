#!/bin/bash
# Run ON nanobot with sudo after init_chunkylink_git_on_server.sh:
#   sudo bash scripts/link_chunkylink_git_remote.sh 'git@github.com:YOU/repo.git'
#   sudo bash scripts/link_chunkylink_git_remote.sh 'https://github.com/YOU/repo.git'
#
set -euo pipefail

unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE 2>/dev/null || true

REPO="${CHUNKYLINK_REPO:-/srv/chunkylink/repo}"
URL="${1:?Usage: $0 <remote-url>}"

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Run as root: sudo bash $0 '$URL'"
  exit 1
fi

if [[ ! -d "${REPO}/.git" ]]; then
  echo "No git repo at ${REPO}. Run init_chunkylink_git_on_server.sh first."
  exit 1
fi

cd "${REPO}" || exit 1

if command git remote get-url origin &>/dev/null; then
  echo "==> remote origin exists; set-url"
  command git remote set-url origin "${URL}"
else
  echo "==> remote add origin"
  command git remote add origin "${URL}"
fi

command git remote -v
echo ""
echo "Push this server's main branch to empty remote (create empty repo on GitHub first, no README):"
echo "  sudo git -C ${REPO} push -u origin main"
echo ""
echo "If the remote already has commits (e.g. you pushed from your laptop first), use instead:"
echo "  sudo git -C ${REPO} fetch origin"
echo "  sudo git -C ${REPO} pull origin main --allow-unrelated-histories"
echo "  # resolve any conflicts, commit, then:"
echo "  sudo git -C ${REPO} push -u origin main"

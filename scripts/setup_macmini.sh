#!/usr/bin/env bash
# ChunkyLink — one-shot bootstrap for a fresh Apple Silicon Mac Mini.
#
# Run this from the Mac Mini's own Terminal (not over SSH) because some
# steps open GUI dialogs (Xcode CLT, etc.).
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/farawayfound/ChunkyLink/main/scripts/setup_macmini.sh | bash
#
# Or after cloning:
#   bash scripts/setup_macmini.sh
#
set -euo pipefail

REPO_URL="https://github.com/farawayfound/ChunkyLink.git"
INSTALL_DIR="$HOME/chunkylink"
VENV_DIR="$INSTALL_DIR/venv"
DATA_DIR="$INSTALL_DIR/data"
LOG="$HOME/chunkylink_setup.log"

info()  { echo -e "\033[1;34m==>\033[0m $*"; }
ok()    { echo -e "\033[1;32m ✓\033[0m $*"; }
warn()  { echo -e "\033[1;33m !\033[0m $*"; }
die()   { echo -e "\033[1;31mERROR:\033[0m $*" >&2; exit 1; }

exec > >(tee -a "$LOG") 2>&1
info "Logging to $LOG"

# ── 1. Xcode Command Line Tools ───────────────────────────────────────────────
if xcode-select -p &>/dev/null; then
    ok "Xcode CLT already installed: $(xcode-select -p)"
else
    info "Installing Xcode Command Line Tools (a dialog will appear — click Install)..."
    xcode-select --install || true
    # Wait for the user to approve the dialog and installation to complete
    echo "  Waiting for Xcode CLT installation to finish..."
    until xcode-select -p &>/dev/null; do
        sleep 10
        echo -n "."
    done
    echo
    ok "Xcode CLT installed"
fi

# ── 2. Homebrew ───────────────────────────────────────────────────────────────
if command -v brew &>/dev/null; then
    ok "Homebrew already installed"
else
    info "Installing Homebrew..."
    NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add Homebrew to PATH for Apple Silicon
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
    fi
    ok "Homebrew installed"
fi

eval "$(brew shellenv)" 2>/dev/null || true

# ── 3. Python 3.11 ────────────────────────────────────────────────────────────
# Python 3.12's .app bundle triggers macOS Local Network Privacy restrictions,
# blocking connections to LAN IPs (e.g. nanobot Ollama).  Python 3.11 is not
# affected and is the supported runtime for the backend on macOS.
if command -v python3.11 &>/dev/null; then
    ok "Python 3.11 already installed"
else
    info "Installing Python 3.11 via Homebrew..."
    brew install python@3.11
    ok "Python 3.11 installed"
fi
PYTHON="$(brew --prefix python@3.11)/bin/python3.11"

# ── 4. Node.js (for frontend build) ──────────────────────────────────────────
if command -v node &>/dev/null; then
    ok "Node already installed: $(node --version)"
else
    info "Installing Node.js via Homebrew..."
    brew install node
    ok "Node installed: $(node --version)"
fi

# ── 5. Ollama ─────────────────────────────────────────────────────────────────
if command -v ollama &>/dev/null; then
    ok "Ollama already installed: $(ollama --version 2>/dev/null || echo 'ok')"
else
    info "Installing Ollama..."
    brew install ollama
    ok "Ollama installed"
fi

# Start Ollama service (launchd)
if ! pgrep -x ollama &>/dev/null; then
    info "Starting Ollama service..."
    brew services start ollama
    sleep 3
fi

# ── 5b. Redis (required for Library/research queue) ─────────────────────────
if command -v redis-server &>/dev/null; then
    ok "Redis already installed: $(redis-server --version | awk '{print $3}')"
else
    info "Installing Redis..."
    brew install redis
    ok "Redis installed"
fi

if ! (brew services list 2>/dev/null | awk '$1=="redis"{print $2}' | grep -q started); then
    info "Starting Redis service..."
    brew services start redis
    sleep 2
fi

if command -v redis-cli &>/dev/null; then
    if redis-cli ping 2>/dev/null | grep -q PONG; then
        ok "Redis is responding on localhost:6379"
    else
        warn "Redis installed but 'redis-cli ping' did not return PONG — try: brew services restart redis"
    fi
fi

# Pull the default model (gemma4:e4b — effective 4B edge variant, consistent for RAG/chat)
DEFAULT_MODEL="gemma4:e4b"
# Worker (nanobot) model defaults — must match what the nanobot GPU can handle.
WORKER_MODEL="${DEPLOY_WORKER_OLLAMA_MODEL:-gemma4:26b}"
WORKER_CTX="${DEPLOY_WORKER_OLLAMA_NUM_CTX:-32000}"
if ollama list 2>/dev/null | grep -q "$DEFAULT_MODEL"; then
    ok "Model $DEFAULT_MODEL already present"
else
    info "Pulling $DEFAULT_MODEL (this may take a few minutes)..."
    ollama pull "$DEFAULT_MODEL" || warn "Model pull failed — retry: ollama pull $DEFAULT_MODEL"
fi

# ── 6. Clone / update repo ────────────────────────────────────────────────────
if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "Updating existing repo at $INSTALL_DIR..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    info "Cloning ChunkyLink to $INSTALL_DIR..."
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"

# ── 7. .env file ──────────────────────────────────────────────────────────────
if [[ ! -f ".env" ]]; then
    info "Creating .env from template..."
    cp .env.example .env
    # Generate a random secret key
    SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    # macOS sed needs backup extension
    sed -i '' "s|change-me-to-a-random-64-char-hex-string|$SECRET|g" .env
    # Set the model
    sed -i '' "s|^OLLAMA_MODEL=.*|OLLAMA_MODEL=$DEFAULT_MODEL|g" .env
    # Set data dir to a stable location outside the repo
    sed -i '' "s|DATA_DIR=./data|DATA_DIR=$DATA_DIR|g" .env
    warn "Edit $INSTALL_DIR/.env to add your GitHub OAuth credentials and OWNER_NAME!"
fi

# Align OLLAMA_MODEL with the stack default when still on a legacy value.
# Also sync data/admin_config.json (which overrides .env at app startup).
# Failures here must NEVER block the rest of the deploy.
_sync_ollama_model() {
    # ── .env ──
    if [[ -f "$INSTALL_DIR/.env" ]]; then
        # Replace only known legacy models; leave custom choices alone
        if grep -qE '^[[:space:]]*OLLAMA_MODEL=[[:space:]]*(nemotron|llama3\.2)' "$INSTALL_DIR/.env" 2>/dev/null; then
            sed -i '' "s|^[[:space:]]*OLLAMA_MODEL=.*|OLLAMA_MODEL=$DEFAULT_MODEL|g" "$INSTALL_DIR/.env"
            ok "OLLAMA_MODEL in .env → $DEFAULT_MODEL"
        fi
    fi

    # ── admin_config.json ──
    local cfg="$DATA_DIR/admin_config.json"
    [[ -f "$cfg" ]] || return 0
    "$PYTHON" -c "
import json, sys, pathlib
p = pathlib.Path(sys.argv[1])
chat_model = sys.argv[2]
worker_model = sys.argv[3]
worker_ctx = int(sys.argv[4])
data = json.loads(p.read_text('utf-8'))
changed = False
# Chat model — only replace known legacy values
cur = (data.get('ollama_model') or '').strip()
if cur and (cur.startswith('nemotron') or cur in ('llama3.2','llama3.2:latest')):
    data['ollama_model'] = chat_model
    changed = True
# Worker model/ctx — always align so backend publishes correct values to Redis
wm = (data.get('worker_ollama_model') or '').strip()
wc = data.get('worker_ollama_num_ctx')
if wm != worker_model or wc != worker_ctx:
    data['worker_ollama_model'] = worker_model
    data['worker_ollama_num_ctx'] = worker_ctx
    data['worker_ollama_migrated_v2'] = True
    changed = True
    print(f'admin_config.json: worker → {worker_model}, num_ctx → {worker_ctx}')
if changed:
    p.write_text(json.dumps(data, indent=2) + '\n', 'utf-8')
" "$cfg" "$DEFAULT_MODEL" "$WORKER_MODEL" "$WORKER_CTX"
}
_sync_ollama_model || warn "Model config sync skipped (non-fatal) — set model via Admin UI after startup"

# ── 8. Python venv + deps ─────────────────────────────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating Python virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

info "Installing Python dependencies..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r requirements.txt

info "Downloading spaCy model (en_core_web_md)..."
"$VENV_DIR/bin/python" -m spacy download en_core_web_md --quiet || \
    warn "spaCy model download failed — retry: venv/bin/python -m spacy download en_core_web_md"

ok "Python environment ready"

# ── 9. Frontend build ─────────────────────────────────────────────────────────
info "Building frontend (clean)..."
cd frontend
# Wipe prior dist + vite cache so a stale build can never shadow a fresh one.
rm -rf dist node_modules/.vite 2>/dev/null || true
npm ci --silent
npm run build
cd ..
DIST_INDEX="$INSTALL_DIR/frontend/dist/index.html"
if [[ ! -f "$DIST_INDEX" ]]; then
    die "Frontend build produced no frontend/dist/index.html — aborting before restart."
fi
DIST_MTIME=$(stat -f "%m" "$DIST_INDEX")
ok "Frontend built → frontend/dist/ (index.html mtime=$DIST_MTIME)"

# ── 9b. Pre-flight: who currently owns port 8765 and any stray processes? ───
info "Pre-flight diagnostic: existing chunkylink processes / listeners"
echo "  — launchctl list | grep -i chunky —"
launchctl list 2>/dev/null | grep -i chunky || echo "    (none)"
echo "  — LaunchAgents/LaunchDaemons plists mentioning chunkylink —"
/usr/bin/grep -lR "chunkylink" \
    "$HOME/Library/LaunchAgents" \
    "/Library/LaunchAgents" \
    "/Library/LaunchDaemons" 2>/dev/null || echo "    (none beyond ours)"
echo "  — lsof -i :8765 (TCP LISTEN) —"
PORT_OWNERS=$(lsof -nP -iTCP:8765 -sTCP:LISTEN 2>/dev/null || true)
if [[ -n "$PORT_OWNERS" ]]; then
    echo "$PORT_OWNERS" | sed 's/^/    /'
else
    echo "    (nothing listening on :8765 yet — normal if backend is stopped)"
fi
echo "  — pgrep -fl 'uvicorn backend.main' —"
pgrep -fl "uvicorn backend.main" 2>/dev/null | sed 's/^/    /' || echo "    (none)"
echo "  — cloudflared / docker / nginx hints —"
pgrep -fl cloudflared 2>/dev/null | sed 's/^/    /' || true
pgrep -fl "docker.*chunky" 2>/dev/null | sed 's/^/    /' || true

# Capture the PID that currently owns :8765 so we can compare after restart.
PRE_PORT_PID=$(lsof -nP -iTCP:8765 -sTCP:LISTEN -Fp 2>/dev/null | sed -n 's/^p//p' | head -n1 || true)

# ── 10. LaunchAgent (auto-start on login) ─────────────────────────────────────
PLIST="$HOME/Library/LaunchAgents/com.chunkylink.backend.plist"
info "Installing LaunchAgent at $PLIST..."
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.chunkylink.backend</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_DIR/bin/uvicorn</string>
        <string>backend.main:app</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>8765</string>
        <string>--workers</string>
        <string>1</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$INSTALL_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>DATA_DIR</key>
        <string>$DATA_DIR</string>
    </dict>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/chunkylink.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/chunkylink.log</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
PLIST_EOF

# Load (or reload) the agent.
# Race note: `unload` can return before the old uvicorn has finished its lifespan
# shutdown, so a plain `load -w` right after sometimes races KeepAlive and
# the OLD process keeps serving requests for a while. `kickstart -k` forces
# launchd to SIGKILL the current instance and start a fresh one — which is
# exactly what we want for a deploy.
launchctl unload "$PLIST" 2>/dev/null || true
launchctl bootout "gui/$(id -u)/com.chunkylink.backend" 2>/dev/null || true
launchctl load -w "$PLIST"
launchctl kickstart -k "gui/$(id -u)/com.chunkylink.backend" 2>/dev/null || true
sleep 3

# If something *other* than our LaunchAgent still owns :8765, report it loudly.
AGENT_PID=$(launchctl list 2>/dev/null | awk '$3=="com.chunkylink.backend"{print $1}')
POST_PORT_PID=$(lsof -nP -iTCP:8765 -sTCP:LISTEN -Fp 2>/dev/null | sed -n 's/^p//p' | head -n1 || true)
if [[ -n "$POST_PORT_PID" && -n "$AGENT_PID" && "$POST_PORT_PID" != "$AGENT_PID" ]]; then
    warn "────────────────────────────────────────────────────────────────"
    warn "ROOT CAUSE CANDIDATE: port 8765 is owned by PID $POST_PORT_PID,"
    warn "but the LaunchAgent 'com.chunkylink.backend' PID is $AGENT_PID."
    warn "The script rebuilt the code and restarted the agent, but a"
    warn "DIFFERENT process is answering HTTP requests — that's why you"
    warn "see stale UI no matter how many times you rebuild."
    warn ""
    warn "Inspect the rogue process:"
    warn "  ps -o pid,ppid,command -p $POST_PORT_PID"
    warn "  lsof -p $POST_PORT_PID | grep -E 'cwd|txt' | head"
    warn ""
    warn "Kill it (safe — launchd will start the managed backend on :8765):"
    warn "  kill $POST_PORT_PID"
    warn "  launchctl kickstart -k \"gui/\$(id -u)/com.chunkylink.backend\""
    warn "────────────────────────────────────────────────────────────────"
fi

# ── 10b. Verify the running backend is reading the dist we just built ────────
info "Verifying backend sees the fresh frontend/dist..."
HEALTH_JSON=""
for _attempt in 1 2 3 4 5; do
    HEALTH_JSON=$(curl -fsS --max-time 3 http://127.0.0.1:8765/api/health 2>/dev/null || true)
    if [[ -n "$HEALTH_JSON" ]]; then break; fi
    sleep 2
done
if [[ -z "$HEALTH_JSON" ]]; then
    warn "Backend did not respond on :8765 after restart. Check: tail -f ~/Library/Logs/chunkylink.log"
else
    SERVED_MTIME=$("$PYTHON" -c "import json,sys; print(json.loads(sys.argv[1]).get('frontend',{}).get('index_html_mtime_unix',''))" "$HEALTH_JSON" 2>/dev/null || echo "")
    SERVED_GIT=$("$PYTHON" -c "import json,sys; print(json.loads(sys.argv[1]).get('git_head_short',''))" "$HEALTH_JSON" 2>/dev/null || echo "")
    LOCAL_GIT=$(git -C "$INSTALL_DIR" rev-parse --short HEAD 2>/dev/null || echo "")
    if [[ "$SERVED_MTIME" == "$DIST_MTIME" ]]; then
        ok "Backend is serving the freshly built dist (mtime=$SERVED_MTIME, git=$SERVED_GIT)"
    else
        warn "STALE: backend reports dist mtime=$SERVED_MTIME but disk mtime=$DIST_MTIME"
        warn "       served git_head=$SERVED_GIT  local git_head=$LOCAL_GIT"
        warn "       The LaunchAgent is likely running from a different WorkingDirectory or an old process."
        warn "       Inspect: launchctl print \"gui/\$(id -u)/com.chunkylink.backend\" | grep -E 'state|cwd|program'"
    fi
fi

# ── 11. Summary ───────────────────────────────────────────────────────────────
MAC_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "unknown")
echo ""
echo "════════════════════════════════════════════════════════"
ok "ChunkyLink deployed!"
echo ""
echo "  Backend:   http://$MAC_IP:8765"
echo "  Admin:     http://$MAC_IP:8765  (log in with GitHub)"
echo ""
echo "  Logs:      tail -f ~/Library/Logs/chunkylink.log"
echo "  Restart:   launchctl kickstart -k gui/\$(id -u)/com.chunkylink.backend"
echo "  Update:    cd $INSTALL_DIR && git pull && bash scripts/setup_macmini.sh"
echo ""
warn "NEXT STEPS:"
echo "  1. Edit .env: add GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, OWNER_NAME"
echo "     GITHUB_ALLOWED_ADMINS=your-github-username"
echo "  2. Set CORS_ORIGINS in .env to include http://$MAC_IP:8765"
echo "  3. launchctl kickstart -k gui/\$(id -u)/com.chunkylink.backend"
echo "  4. Open http://$MAC_IP:8765 on any device on your local network"
echo "════════════════════════════════════════════════════════"

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

# ── 3. Python 3.12 ────────────────────────────────────────────────────────────
if command -v python3.12 &>/dev/null; then
    ok "Python 3.12 already installed"
else
    info "Installing Python 3.12 via Homebrew..."
    brew install python@3.12
    ok "Python 3.12 installed"
fi
PYTHON="$(brew --prefix python@3.12)/bin/python3.12"

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

# Pull the default model (gemma4:e4b — effective 4B edge variant, consistent for RAG/chat)
DEFAULT_MODEL="gemma4:e4b"
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
d = sys.argv[2]
data = json.loads(p.read_text('utf-8'))
cur = (data.get('ollama_model') or '').strip()
if cur and not cur.startswith('nemotron') and cur not in ('llama3.2','llama3.2:latest'):
    sys.exit(0)
data['ollama_model'] = d
p.write_text(json.dumps(data, indent=2) + '\n', 'utf-8')
print('admin_config.json: ollama_model →', d)
" "$cfg" "$DEFAULT_MODEL"
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
info "Building frontend..."
cd frontend
npm ci --silent
npm run build
cd ..
ok "Frontend built → frontend/dist/"

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

# Load (or reload) the agent
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load -w "$PLIST"
sleep 2

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

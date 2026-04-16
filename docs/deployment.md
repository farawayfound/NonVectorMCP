# ChunkyPotato deployment (nanobot / self-hosted)

This document describes how ChunkyPotato is deployed on a small Linux host (example: **nanobot**, SSH user **david**, app path **`/srv/chunkylink/repo`**). Paths and hostnames are the defaults used in the helper scripts; override them with environment variables where noted.

**Compatibility:** The UI product name is **ChunkyPotato**, but **`chunkylink`** remains the convention for filesystem paths, the systemd unit, the service user, the SQLite filename, session cookie name, and `CHUNKYLINK_*` environment variables—so existing servers keep working without renames.

## Layout on the server

| Path | Role |
|------|------|
| `/srv/chunkylink/repo` | Application source (Git working tree) |
| `/srv/chunkylink/venv` | Python virtualenv used by systemd |
| `/srv/chunkylink/data` | Runtime data (`DATA_DIR` in `.env`; not inside the repo) |
| `/srv/chunkylink/repo/.env` | Production secrets (never committed) |

Systemd service: **`chunkylink`** (runs Uvicorn as user **`chunkylink`**).

## Prerequisites

- **Git** 2.35 or newer on the server (ownership / `safe.directory` behavior).
- **sudo** access for the admin SSH user (e.g. david) to run deploy and one-time Git setup.
- **Optional:** [nvm](https://github.com/nvm-sh/nvm) under the admin user (`~/.nvm`) so `deploy_chunkylink.sh` can run `npm ci` and `npm run build` in `frontend/` when you deploy. If Node is missing, set `DEPLOY_SKIP_NPM=1` and build the frontend elsewhere, or install nvm once on the server.

## Git and “safe directory” (important)

The application tree is normally owned by **`chunkylink`**, while deploy and init scripts run Git as **root** via **sudo**. Since Git 2.35, that combination is blocked unless the repository path is registered as safe.

The scripts **`init_chunkylink_git_on_server.sh`**, **`link_chunkylink_git_remote.sh`**, and **`deploy_chunkylink.sh`** add the canonical path to **root’s** global Git config:

`git config --global --add safe.directory /srv/chunkylink/repo`

If you use **`git`** on the same path as a **normal user** (not sudo), add the same path to **your** account once:

```bash
git config --global --add safe.directory /srv/chunkylink/repo
```

Avoid exporting stale **`GIT_DIR`** / **`GIT_WORK_TREE`** in your shell when running these scripts; the scripts unset them at startup.

## One-time setup: turn an existing install into a Git repository

Use this when the server already has a copy of the app under `/srv/chunkylink/repo` but no `.git` yet.

### 1. Copy helper scripts onto the server (if needed)

From your development machine:

```bash
scp scripts/init_chunkylink_git_on_server.sh scripts/link_chunkylink_git_remote.sh scripts/deploy_chunkylink.sh david@nanobot.local:~/
```

Optional: copy them into the app tree so they are versioned after the first commit:

```bash
# On the server:
sudo cp /home/david/init_chunkylink_git_on_server.sh /home/david/link_chunkylink_git_remote.sh /home/david/deploy_chunkylink.sh /srv/chunkylink/repo/scripts/
sudo chown chunkylink:chunkylink /srv/chunkylink/repo/scripts/*.sh
```

### 2. Initialize Git and the first commit

On the server (sudo will prompt for a password):

```bash
sudo bash ~/init_chunkylink_git_on_server.sh
```

This script:

- Writes **`.gitignore`** (excludes `.env`, `data/`, `frontend/dist/`, venv, logs, etc.).
- Runs **`git init`** on branch **`main`**, sets a local `user.name` / `user.email` for this repo only, **`git add -A`**, and creates the **initial commit**.
- Runs **`chown -R chunkylink:chunkylink /srv/chunkylink/repo`**.

If a previous attempt left a broken state, remove `.git` and rerun:

```bash
sudo rm -rf /srv/chunkylink/repo/.git
sudo bash ~/init_chunkylink_git_on_server.sh
```

### 3. Create an empty remote repository

On GitHub (or similar), create a **new empty** repository: **no** README, **no** `.gitignore`, **no** license. That avoids an unnecessary unrelated-history merge on first push.

### 4. Point `origin` at the remote and push

```bash
sudo bash ~/link_chunkylink_git_remote.sh 'git@github.com:YOUR_USER/YOUR_REPO.git'
sudo git -C /srv/chunkylink/repo push -u origin main
```

Use an SSH URL if the server has a deploy key or your SSH agent; otherwise use HTTPS and your host’s credential helper or token.

If the remote **already has commits** (for example you initialized from your laptop first), use **`fetch`**, then **`pull origin main --allow-unrelated-histories --no-rebase`** (Git 2.40+ requires an explicit merge vs rebase choice), resolve conflicts, commit, then **`push`**. If you instead want **only GitHub’s tree** and can discard the server’s unique commits, use **`fetch`** then **`reset --hard origin/main`** (destructive on that clone). The **`link_chunkylink_git_remote.sh`** script prints these commands as a reminder.

## Day-to-day updates

### 1. Push from your development machine

Commit and push to the same remote and branch the server tracks (typically **`main`**).

### Remote `origin` must exist

**`deploy_chunkylink.sh` always runs `git fetch` / `git pull` from `origin`.** If you only ran **`init_chunkylink_git_on_server.sh`** and never **`link_chunkylink_git_remote.sh`**, there is no `origin` yet—you will see fetch errors until you complete [§ 4 Point `origin` at the remote and push](#4-point-origin-at-the-remote-and-push). The deploy script now stops early with the same hint if `origin` is missing.

If `origin` is set but fetch still fails, check SSH keys / HTTPS credentials on the server and that the URL is correct (`git -C /srv/chunkylink/repo remote -v`).

### 2. Deploy on the Linux server (nanobot)

On **nanobot** (and similar hosts where the repo is owned by **`chunkylink`** but deploy runs as **root** via **sudo**), a plain **`git pull --ff-only`** inside **`deploy_chunkylink.sh`** often **fails** (divergent history, stray commits, or tracked files touched during earlier deploys). The reliable command is:

```bash
sudo DEPLOY_RESET_HARD=1 bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh
```

**`DEPLOY_RESET_HARD=1`** makes the script **`git fetch`** then **`git reset --hard`** to the remote branch so **GitHub is truth** for tracked files. Ignored files (**`.env`**, **`data/`**, **`frontend/dist/`** if gitignored, etc.) are **not** removed.

If you are certain the server branch is already a fast-forward behind **`origin`** (no local commits, no dirty tracked files), you can use the lighter command:

```bash
sudo bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh
```

### 2a. Deploy on `david@macmini` (LaunchAgent)

On macOS installs that use `scripts/setup_macmini.sh`, the app runs as a user LaunchAgent (`com.chunkylink.backend`) instead of a systemd service.

Run these commands directly on the Mac mini:

```bash
cd ~/chunkylink
git pull --ff-only
launchctl kickstart -k "gui/$(id -u)/com.chunkylink.backend"
```

Optional full refresh (re-installs deps, rebuilds frontend, and reloads the LaunchAgent):

```bash
cd ~/chunkylink
bash scripts/setup_macmini.sh
```

**Frontend build only (Mac mini):** Uvicorn serves **`frontend/dist/`** when that folder exists. If the UI looks unstyled, outdated, or wrong after a **`git pull`**, rebuild the bundle on the Mac mini (Node / npm required), then restart the backend:

```bash
cd ~/chunkylink/frontend && npm run build
launchctl kickstart -k "gui/$(id -u)/com.chunkylink.backend"
```

**`npm run build` must run inside `frontend/`.** There is **no** `package.json` at the repo root (`~/chunkylink`). If you see **`ENOENT: Could not read package.json`** you ran npm from the wrong directory — **`cd ~/chunkylink/frontend`** first (or use **`bash scripts/setup_macmini.sh`**, which **`cd`**s there for you).

A plain **`cd frontend && npm run build`** from the repo root is equivalent; the important part is running **`npm run build`** inside **`frontend/`** so **`dist/`** matches the current **`src/`**.

#### Request Access — "Email service is not configured"

The login page **Request Access** flow calls **`POST /api/auth/request-access`**, which sends an invite code by email. That requires **SMTP** in **`~/chunkylink/.env`**:

- **`SMTP_HOST`** (required — if empty, the API returns that error)
- **`SMTP_PORT`** (e.g. **587**)
- **`SMTP_USER`** / **`SMTP_PASSWORD`**
- **`SMTP_FROM`** (optional; often same as **`SMTP_USER`**)
- **`SMTP_USE_TLS`** (usually **`true`** for port 587)

Copy the block from **`.env.example`**, fill in a real relay (Gmail app password, Mailgun, SendGrid SMTP, etc.), then restart:

```bash
launchctl kickstart -k "gui/$(id -u)/com.chunkylink.backend"
```

#### Ask Me Anything vs Workspace / Library

| Feature | What it needs |
|---------|----------------|
| **Workspace** (document chat) | Your **uploaded** docs and **user** index under **`DATA_DIR`**. |
| **Library** | **Redis** (**`REDIS_URL`**) and the **nanobot** worker; separate from AMA. |
| **Ask Me Anything** | The **demo** index only: **`$DATA_DIR/indexes/demo`** (default **`~/chunkylink/data/indexes/demo`**). It does **not** use your Workspace uploads. |

If AMA “does nothing” or always errors, build the demo index once: **Admin → AMA KB (Demo KB) → Build Index**. Confirm Ollama is running (**`brew services list`**, **`ollama list`**) and matches **`OLLAMA_MODEL`** in **`.env`**.

**Cloudflare in front of the Mac:** **AMA** streams responses over **SSE** (**`POST /api/chat/ask`**). Proxies sometimes **buffer** event streams, which breaks the chat UI. Add a **Cache / configuration rule** to **bypass** caching (and avoid buffering) for **`/api/chat/*`** (or at least **`/api/chat/ask`**). Symptoms can include a stuck “thinking” state or no answer while Workspace (different route) still appears fine.

Quick verification on macOS:

```bash
launchctl print "gui/$(id -u)/com.chunkylink.backend" | grep -E "state =|pid ="
tail -n 100 ~/Library/Logs/chunkylink.log
```

(`grep -E` is built in on macOS. **`rg`** (ripgrep) is optional and not installed by default.)

**Important:** **`git pull` does not update the UI by itself.** The browser loads files from **`frontend/dist/`**, which is gitignored. You must run **`npm run build`** (or **`bash scripts/setup_macmini.sh`**, which runs **`npm ci`** + **`npm run build`**) after pulling, then restart the LaunchAgent.

#### Stale UI after deploy (Mac mini + Cloudflare / CDN)

Symptoms: you know **`~/chunkylink`** is on the latest commit and **`npm run build`** succeeded, but the site still looks like an older version—even in Incognito and after purging caches.

1. **Confirm the running backend is reading the dist you built**

   On the Mac mini:

   ```bash
   stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" ~/chunkylink/frontend/dist/index.html
   curl -sS http://127.0.0.1:8765/api/health
   ```

   The JSON field **`frontend.index_html_built_at`** must match the **`index.html`** modification time on disk. If it does **not**, the LaunchAgent is almost certainly using a **different** working directory or an old process: check **`launchctl print gui/$(id -u)/com.chunkylink.backend`** for **`working directory`** (should be **`~/chunkylink`**). Reload the plist after fixing: **`bash scripts/setup_macmini.sh`** or **`launchctl unload` / `load`** the agent.

2. **Cloudflare (orange-cloud) in front of the Mac**

   **`index.html`** is served with **no-store** headers, but many CDNs still cache HTML unless you add an explicit rule. Create a **Cache Rule** (or Page Rule) to **Bypass** cache for the site’s HTML entry (e.g. URI Path equals **`/`** or **`/index.html`**), or enable **Development Mode** temporarily. Hashed files under **`/assets/`** are safe to cache long-term; **do not** let **`/`** or SPA routes sit behind a long **TTL** for HTML.

3. **Force a clean frontend build**

   ```bash
   cd ~/chunkylink/frontend
   rm -rf node_modules/.vite dist
   npm ci && npm run build
   cd ..
   launchctl kickstart -k "gui/$(id -u)/com.chunkylink.backend"
   ```

4. **Wrong repo path** — Only one tree should be canonical (**`$HOME/chunkylink`** from **`setup_macmini.sh`**). If you sometimes **`git pull`** in another clone, **`dist/`** there is irrelevant.

**`deploy_chunkylink.sh`** will:

1. **`git fetch`** then either **`git pull --ff-only`** or, with **`DEPLOY_RESET_HARD=1`**, **`git reset --hard`** to match the remote (see [§ 2](#2-deploy-on-the-linux-server-nanobot)).
2. **`pip install -r requirements.txt`** using `/srv/chunkylink/venv/bin/pip`.
3. **`npm ci`** and **`npm run build`** in `frontend/` when Node is available via the invoking user’s nvm (`SUDO_USER`), unless **`DEPLOY_SKIP_NPM=1`**.
4. Force-align nanobot worker/runtime model settings to **`gemma4:26b`** + **`32000`** in **`.env`**, **`.env.nanobot`**, and (when present) **`data/admin_config.json`**.
5. **`chown -R chunkylink:chunkylink`** on the repo.
6. **`systemctl restart chunkylink`** and report whether the unit is **active**.

Backend-only change (skip frontend build):

```bash
sudo DEPLOY_SKIP_NPM=1 bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh
```

On **nanobot**, combine with reset if **`git pull`** would fail:

```bash
sudo DEPLOY_SKIP_NPM=1 DEPLOY_RESET_HARD=1 bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh
```

Merge a specific ref instead of the default pull (example):

```bash
sudo GIT_REF=origin/main bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh
```

The same **`DEPLOY_RESET_HARD=1`** invocation is listed again here for quick reference when you hit **`git pull --ff-only` failed** during a normal deploy:

```bash
sudo DEPLOY_RESET_HARD=1 bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh
```

### 3. Optional: deploy from Windows without an interactive shell on the server

From the project root on Windows (after **`git push`**):

```powershell
.\scripts\Deploy-Nanobot.ps1
.\scripts\Deploy-Nanobot.ps1 -Target "david@nanobot.local"
```

By default this runs **`sudo bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh`** over SSH. On **nanobot**, if that fails at **`git pull`**, run interactively with reset instead:

```powershell
ssh -t david@nanobot "sudo DEPLOY_RESET_HARD=1 bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh"
```

(Adjust user/host.) You still need a way to satisfy **sudo** (password prompt in an interactive session, or configured **NOPASSWD** for that command only).

### 4. After certain changes

If you change NLP categories, chunking, or anything that affects indexed metadata, rebuild the demo (or relevant) index in the UI: **Admin → Demo KB → Build Index**.

Restarting **Ollama** is only needed when you change Ollama itself or its models, not for every app deploy:

```bash
sudo systemctl restart ollama
sudo systemctl restart chunkylink
```

## Environment variables (all scripts)

| Variable | Default | Meaning |
|----------|---------|---------|
| `CHUNKYLINK_REPO` | `/srv/chunkylink/repo` | Git top-level / app root |
| `CHUNKYLINK_VENV` | `/srv/chunkylink/venv` | Python venv (deploy script) |
| `CHUNKYLINK_OWNER` | `chunkylink` | `chown` target after deploy / init |
| `DEPLOY_SKIP_NPM` | `0` | Set to **`1`** to skip frontend build (deploy only) |
| `DEPLOY_RESET_HARD` | `0` | Set to **`1`** to **`git reset --hard origin/<branch>`** after fetch (discards local drift on tracked files) |
| `GIT_REF` | *(empty)* | If set, deploy runs **`git merge --ff-only $GIT_REF`** instead of **`git pull --ff-only`** |

## Alternative one-time path: fresh clone

If you prefer not to migrate an existing tree, you can clone into a new directory, copy **`.env`** and point **`DATA_DIR`** at your existing data, then adjust the systemd unit’s **`WorkingDirectory`** and **`EnvironmentFile`**. The **`deploy_chunkylink.sh`** script’s error message documents the same idea at a high level.

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| **`detected dubious ownership`** or Git fails right after **`git init`** | Ensure **`safe.directory`** is set for `/srv/chunkylink/repo` for **root** (scripts do this) and for your user if you run **`git`** without sudo. |
| **`fatal: not in a git directory`** after init | Often the same ownership / **`safe.directory`** issue; upgrade scripts and clear a half-done **`.git`** with **`sudo rm -rf /srv/chunkylink/repo/.git`**, then rerun init. Unset stray **`GIT_DIR`** in your environment. |
| **`Already a git repo — aborting`** | Either deploy with **`deploy_chunkylink.sh`**, or remove **`.git`** only if you intend to re-run init from scratch. |
| **`'origin' does not appear to be a git repository`** / fetch fails | **`origin` is missing or the URL is wrong.** Run **`link_chunkylink_git_remote.sh`** with your repo URL, or fix **`git remote set-url origin …`**. |
| **`Need to specify how to reconcile divergent branches`** | On **`pull`**, add **`--no-rebase`** (merge) or **`--rebase`**, e.g. **`sudo git -C /srv/chunkylink/repo pull origin main --allow-unrelated-histories --no-rebase`**. |
| **`fatal: not a git repository`** from **`~`** | Run Git with **`sudo git -C /srv/chunkylink/repo …`** (or **`cd`** there first). Your home directory is not the repo. |
| **`git pull --ff-only` failed** / “local changes would be overwritten” | Common on **nanobot**. If **GitHub** should win, use [§ 2](#2-deploy-on-the-linux-server-nanobot): **`sudo DEPLOY_RESET_HARD=1 bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh`**. Alternatively: **`sudo git -C /srv/chunkylink/repo fetch origin && sudo git -C /srv/chunkylink/repo reset --hard origin/main`**, then rerun deploy without reset if you prefer. |
| Frontend build skipped | Install **nvm** + Node under the sudo-ing user, or set **`DEPLOY_SKIP_NPM=1`** and supply **`frontend/dist`** another way. |
| **Mac mini:** UI unstyled or clearly old after pull | **`git pull` alone does not refresh `dist/`** — run **`npm run build`** or **`bash scripts/setup_macmini.sh`**, then restart the agent. See [§ 2a](#2a-deploy-on-davidmacmini-launchagent). |
| **Mac mini:** UI stuck on old version despite rebuild + Incognito | Compare **`stat …/frontend/dist/index.html`** with **`curl http://127.0.0.1:8765/api/health`** → **`frontend.index_html_built_at`**. Mismatch → wrong **WorkingDirectory** or stale process. If they match, fix **Cloudflare / CDN HTML caching** (subsection *Stale UI after deploy* under [§ 2a](#2a-deploy-on-davidmacmini-launchagent)). |
| **`npm run build` → ENOENT `package.json`** | Run from **`~/chunkylink/frontend`**, not the repo root. See [§ 2a](#2a-deploy-on-davidmacmini-launchagent). |
| **Request Access:** *Email service is not configured* | Set **`SMTP_HOST`** (and related vars) in **`.env`**, restart LaunchAgent. See [§ 2a](#2a-deploy-on-davidmacmini-launchagent). |
| **Ask Me Anything** broken; Workspace OK | Build **Admin → AMA KB → Build Index**. Check **Ollama**. If behind **Cloudflare**, bypass cache / buffering for **`/api/chat/*`** (SSE). See [§ 2a](#2a-deploy-on-davidmacmini-launchagent). |
| Service not active after restart | **`journalctl -u chunkylink -e`** (Linux). **Mac mini:** **`launchctl print "gui/$(id -u)/com.chunkylink.backend"`** and **`grep -E "state =|pid ="`** on that output. |
| **`zsh: command not found: rg`** | The docs use **`grep -E`** for LaunchAgent checks; install **`ripgrep`** (`brew install ripgrep`) only if you prefer **`rg`**. |
| Log shows **Shutting down** / **Started server process** in a tight loop | Usually repeated **`launchctl kickstart -k`** or deploys. If you are **not** restarting manually, check **Console.app** for signals; **`KeepAlive`** in the plist will respawn after exit. |
| **Mac mini:** chat still uses **nemotron** after **`setup_macmini.sh`** | **`admin_config.json`** (under **`DATA_DIR`**) stores **`ollama_model`** and overrides **`.env`**. The setup script now rewrites legacy nemotron/llama defaults in both **`.env`** and **`~/chunkylink/data/admin_config.json`**. Restart: **`launchctl kickstart -k "gui/$(id -u)/com.chunkylink.backend"`**. To pin the stack default on any model: **`CHUNKYLINK_FORCE_DEFAULT_OLLAMA_MODEL=1 bash scripts/setup_macmini.sh`**. |

## Script reference (repository paths)

| Script | Purpose |
|--------|---------|
| `scripts/init_chunkylink_git_on_server.sh` | One-time Git init + `.gitignore` + initial commit + `chown` |
| `scripts/link_chunkylink_git_remote.sh` | Set **`origin`** URL (argument: remote URL) |
| `scripts/deploy_chunkylink.sh` | Pull (or reset with **`DEPLOY_RESET_HARD=1`**), dependencies, optional frontend build, align worker/runtime Ollama to **`gemma4:26b`** + **`32000`**, `chown`, **`systemctl restart chunkylink`** — on **nanobot**, prefer **`DEPLOY_RESET_HARD=1`** ([§ 2](#2-deploy-on-the-linux-server-nanobot)). |
| `scripts/Deploy-Nanobot.ps1` | Windows: SSH trigger for **`deploy_chunkylink.sh`** |

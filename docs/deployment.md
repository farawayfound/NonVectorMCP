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

### 2. Deploy on the server

SSH in and run:

```bash
sudo bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh
```

This will:

1. **`git fetch`** / **`git pull --ff-only`** (fails if the server has diverging local commits).
2. **`pip install -r requirements.txt`** using `/srv/chunkylink/venv/bin/pip`.
3. **`npm ci`** and **`npm run build`** in `frontend/` when Node is available via the invoking user’s nvm (`SUDO_USER`), unless **`DEPLOY_SKIP_NPM=1`**.
4. **`chown -R chunkylink:chunkylink`** on the repo.
5. **`systemctl restart chunkylink`** and report whether the unit is **active**.

Backend-only change (skip frontend build):

```bash
sudo DEPLOY_SKIP_NPM=1 bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh
```

Merge a specific ref instead of the default pull (example):

```bash
sudo GIT_REF=origin/main bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh
```

**GitHub is truth; discard server-only edits** (uncommitted or extra local commits on the current branch—tracked files only; ignored files like **`.env`** are left alone):

```bash
sudo DEPLOY_RESET_HARD=1 bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh
```

### 3. Optional: deploy from Windows without an interactive shell on the server

From the project root on Windows (after **`git push`**):

```powershell
.\scripts\Deploy-Nanobot.ps1
.\scripts\Deploy-Nanobot.ps1 -Target "david@nanobot.local"
```

This runs **`sudo bash /srv/chunkylink/repo/scripts/deploy_chunkylink.sh`** over SSH. You still need a way to satisfy **sudo** (password prompt in an interactive session, or configured **NOPASSWD** for that command only).

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
| **`git pull --ff-only` failed** / “local changes would be overwritten” | Uncommitted edits or diverged history. If **GitHub** should win: **`sudo DEPLOY_RESET_HARD=1 bash …/deploy_chunkylink.sh`** or **`sudo git -C /srv/chunkylink/repo fetch origin && sudo git -C /srv/chunkylink/repo reset --hard origin/main`**. |
| Frontend build skipped | Install **nvm** + Node under the sudo-ing user, or set **`DEPLOY_SKIP_NPM=1`** and supply **`frontend/dist`** another way. |
| Service not active after restart | **`journalctl -u chunkylink -e`** |

## Script reference (repository paths)

| Script | Purpose |
|--------|---------|
| `scripts/init_chunkylink_git_on_server.sh` | One-time Git init + `.gitignore` + initial commit + `chown` |
| `scripts/link_chunkylink_git_remote.sh` | Set **`origin`** URL (argument: remote URL) |
| `scripts/deploy_chunkylink.sh` | Pull, dependencies, optional frontend build, `chown`, **`systemctl restart chunkylink`** |
| `scripts/Deploy-Nanobot.ps1` | Windows: SSH trigger for **`deploy_chunkylink.sh`** |

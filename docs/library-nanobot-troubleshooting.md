# Library worker (nanobot) — troubleshooting runbook

This runbook captures fixes for **split-host Library research**: **Mac mini** runs the ChunkyLink **API + web UI + SQLite + Redis**; **nanobot** runs the **Library worker** (and **Ollama**) in **Docker**. Jobs dequeue from **Redis** on the Mac; the worker POSTs results to the Mac **HTTP API**.

If anything below is wrong, the worker container often **restarts in a loop** or Library jobs **fail** with opaque errors.

---

## 1. Architecture (non-negotiable mental model)

| Host | Role |
|------|------|
| **Mac mini** | Backend (`uvicorn`), frontend `dist/`, **Redis** (must be reachable on LAN), **`REDIS_URL` / `M1_BASE_URL` in Mac `.env`** for the app itself. |
| **nanobot** | `docker compose -f docker/docker-compose.nanobot.yml`: **`worker`** + **`ollama`**. Worker reads **`/srv/chunkylink/repo/.env.nanobot`**. |

From **inside** the worker container:

- **`localhost` / `127.0.0.1`** is the **container**, not the Mac. Never point **`REDIS_URL`** or **`M1_BASE_URL`** at localhost for cross-host setups.
- Use the Mac’s **LAN IPv4** (same subnet as nanobot), e.g. `192.168.0.65`.

---

## 2. `.env.nanobot` on nanobot (canonical reference)

Path: **`/srv/chunkylink/repo/.env.nanobot`** (see **`.env.nanobot.example`** in the repo).

| Variable | Purpose | Common mistake |
|----------|---------|------------------|
| **`REDIS_URL`** | `redis://<mac-lan-ip>:6379/<db>` — same DB index as the Mac backend **`.env`** `REDIS_URL`. | `localhost` → worker talks to itself; wrong IP → **errno 113 EHOSTUNREACH**. |
| **`M1_BASE_URL`** | `http://<mac-lan-ip>:8000` (or your API port) for ingest / worker-failure. | `localhost` or mDNS-only hostname from Linux Docker. |
| **`NANOBOT_API_KEY`** | Must match **`NANOBOT_API_KEY`** on the Mac **`.env`**. | Mismatch → 403 on worker callbacks. |
| **`OLLAMA_BASE_URL`** | Where **this worker process** reaches Ollama. In compose, usually **`http://ollama:11434`**. | Host-only IP only if Ollama is not the compose service. |
| **`OLLAMA_MODEL`** | Must match **`ollama list`** **inside** the `ollama` container. | Wrong tag → **HTTP 404** on `POST /api/generate`. |
| **`OLLAMA_NUM_CTX`** | Default **24576** (24k) in repo; must fit GPU VRAM + Docker memory for `gemma4:26b`. | If Ollama refuses to load or OOMs, lower (e.g. 16384) in `.env.nanobot` and recreate the worker. |

**Docker Compose note:** `docker/docker-compose.nanobot.yml` must **not** override **`OLLAMA_BASE_URL`** in a hardcoded `environment:` block — that prevented **`.env.nanobot`** from taking effect (fixed in repo: only **`env_file`** drives the worker).

Edit on nanobot:

```bash
sudo nano /srv/chunkylink/repo/.env.nanobot
cd /srv/chunkylink/repo
sudo docker compose -f docker/docker-compose.nanobot.yml up -d --force-recreate worker
```

Verify env **inside** the worker:

```bash
sudo docker compose -f docker/docker-compose.nanobot.yml exec worker python -c "import os; print('REDIS_URL', os.environ.get('REDIS_URL')); print('M1', os.environ.get('M1_BASE_URL')); print('OLLAMA', os.environ.get('OLLAMA_BASE_URL'))"
```

---

## 3. Redis on the Mac — “connection refused” from nanobot

**Symptom:** On nanobot, `nc -zv <mac-ip> 6379` or `redis-cli -h <mac-ip> ping` → **connection refused**, while Redis works locally on the Mac.

**Cause:** `redis-server` was only listening on **loopback** (`lsof` showed `localhost:6379`).

**Fix (Mac mini, SSH):**

1. Locate config (Homebrew): **`$(brew --prefix)/etc/redis.conf`** (often `/opt/homebrew/etc/redis.conf`).
2. Set **`bind 0.0.0.0`** (or include the Mac LAN IP explicitly). Replace a line like **`bind 127.0.0.1 ::1`**.
3. If clients are on the LAN without a password, **`protected-mode yes`** will block — for a **trusted home LAN only**, set **`protected-mode no`**, or prefer **`requirepass`** and use `redis://:password@host:6379/0` in **`.env.nanobot`**.
4. **`brew services restart redis`**
5. Confirm: **`lsof -iTCP:6379 -sTCP:LISTEN`** should show **`*:6379`** or the LAN IP, not only **`localhost`**.
6. From nanobot: **`redis-cli -h <mac-ip> -p 6379 ping`** → **`PONG`**.

**macOS firewall:** allow inbound **TCP 6379** for `redis-server` if enabled.

---

## 4. Redis — “errno 113 / EHOSTUNREACH” from the worker

**Cause:** Wrong Mac IP, different VLAN, VPN, or no route — not a Redis protocol error.

**Fix:** Confirm the Mac’s Wi‑Fi/Ethernet IP; from nanobot run **`ping`** and **`nc -zv <ip> 6379`** until the port is reachable.

The worker logs an extra line when it detects **errno 113** (see **`worker/main.py`**).

---

## 5. Docker on nanobot — permissions

**Symptom:** `permission denied` on **`/var/run/docker.sock`**.

**Fix:** `sudo docker compose …` or add user to **`docker`** group: **`sudo usermod -aG docker $USER`** (log out/in).

---

## 6. Ollama — model list and `404` on `/api/generate`

**Symptom:** `Client error '404 Not Found' for url '.../api/generate'`.

**Cause (usual):** Ollama returns **404** when the **`model`** in the JSON body is **not** in the local store for the **server you actually hit**.

**Important:** **`ollama list` on the nanobot host shell** can be **empty** while models exist **inside** the **`ollama`** container. Always check/pull **in the container**:

```bash
cd /srv/chunkylink/repo
sudo docker compose -f docker/docker-compose.nanobot.yml exec ollama ollama list
sudo docker compose -f docker/docker-compose.nanobot.yml exec ollama ollama pull gemma4:26b
```

**`OLLAMA_BASE_URL`:** from the **worker** container, **`http://ollama:11434`** is correct when **ollama** is the sibling service in the same compose file. Use the host LAN IP only if Ollama is exposed that way instead.

The worker calls **`GET /api/tags`** at startup (**`verify_ollama_model_tag`**) and logs if the configured **`OLLAMA_MODEL`** tag is missing.

---

## 7. Library failure messages in the UI

Failures are persisted via:

- **Redis** status stream (live SSE), and  
- **`POST /api/library/worker-failure`** from the worker (so SQLite **`error`** is set even if no browser had SSE open).

The backend persists **`error`** before emitting SSE where applicable; **`docker-compose`** must not race **`refresh()`** against DB (handled in app code). See **`backend/routes/library.py`**, **`backend/library/service.py`**, **`worker/main.py`**.

---

## 8. Quick checklist (copy when things break)

1. **Mac IP correct?** Same subnet as nanobot.
2. **From nanobot:** `redis-cli -h <mac-ip> -p 6379 ping` → **PONG**.
3. **From nanobot:** `curl -sS -o /dev/null -w "%{http_code}\n" http://<mac-ip>:8000/api/health` (or your API port) → **200**.
4. **`.env.nanobot`:** `REDIS_URL`, `M1_BASE_URL`, `NANOBOT_API_KEY`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`.
5. **`sudo docker compose -f docker/docker-compose.nanobot.yml up -d --build --force-recreate worker`**
6. **`sudo docker compose -f docker/docker-compose.nanobot.yml logs --tail=100 worker`**

---

## Related files in the repo

| File | Relevance |
|------|-----------|
| **`.env.nanobot.example`** | Annotated template for nanobot. |
| **`docker/docker-compose.nanobot.yml`** | Worker + Ollama; worker env from **`env_file`**. |
| **`worker/config.py`** | Reads **`OLLAMA_*`**, **`REDIS_URL`**, **`M1_BASE_URL`**. |
| **`worker/main.py`** | Redis loopback guard in Docker; clearer Redis connect errors. |
| **`worker/synthesizer/llm_client.py`** | Ollama **`trust_env=False`**, 404 messaging, **`verify_ollama_model_tag`**. |
| **`scripts/deploy_nanobot_worker.sh`** | Compose up + optional **`ollama pull`**. |

For general server layout, see **`docs/deployment.md`**.

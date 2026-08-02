# ULTRA Deployment & Operations Runbook

How to stand up, run, monitor and upgrade the ULTRA Algorithmic Trading
Platform. The platform spec lives in `docs/`; this file is the operator's
playbook.

## Quick reference

| Artifact | Purpose |
|----------|---------|
| `main.py` | Bot entry point (`--mode paper\|live\|backtest`, `--broker deriv\|binance`) |
| `deploy/ultra.service` | Linux systemd unit (auto-restart + hardening) |
| `deploy/start.sh` | Linux/macOS auto-restart supervisor |
| `deploy/start.ps1` | Windows auto-restart supervisor |
| `deploy/healthcheck.sh` | Linux/macOS health probe (process + fresh DB writes); also the Docker HEALTHCHECK |
| `deploy/healthcheck.ps1` | Windows health probe (process + fresh DB writes) |
| `deploy/backup.sh` | Linux/macOS daily DB + log backup with pruning |
| `deploy/backup.ps1` | Windows daily DB + log backup with pruning |
| `Dockerfile` / `docker-compose.yml` | Containerized deployment (recommended) |
| `src/dashboard/app.py` | Streamlit dashboard (port 8501) |
| `VERSION` | Version of the platform (single source of truth) |

## Prerequisites

- Python **3.11+** (tested on 3.12 / 3.14)
- `pip install -r requirements.txt` (runtime) or `requirements-dev.txt` (adds tests)
- An `.env` file (copy `.env.example`); **no token is needed for paper mode**.
  The compose file treats `.env` as optional (`required: false`, needs Docker
  Compose >= 2.24) so a fresh checkout with no `.env` still starts in token-less
  paper mode.

```
cp .env.example .env      # then edit BROKER/TRADING_MODE/DERIV_API_TOKEN
```

## Option 1 — Docker (recommended for VPS)

```bash
docker compose up -d --build            # builds and starts in paper mode
docker compose ps                        # Status column: healthy / unhealthy
docker compose logs -f ultra            # follow logs
docker compose down                     # stop (graceful SIGTERM)
```

- Runtime state is kept in `./data`, `./logs`, `./backups` (mounted volumes).
- Secrets are read from `.env` (`env_file`) — **never baked into the image**.
- The container self-reports health (`deploy/healthcheck.sh`: PID alive + DB
  written within 5 min). `docker compose ps` shows `healthy`; Docker restarts
  an unhealthy/stopped container via `restart: unless-stopped`.
- Override mode/broker without touching files:

```bash
docker compose run --rm -e TRADING_MODE=live -e BROKER=deriv ultra
```

- The container runs as an unprivileged user and only installs runtime deps.

## Option 2 — Linux (systemd)

```bash
# 1. Place the code and a venv
sudo mkdir -p /opt/ultra
sudo cp -r src config main.py requirements.txt VERSION /opt/ultra/
cd /opt/ultra && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt

# 2. Configure the unit (edit broker/mode/token)
sudo cp deploy/ultra.service /etc/systemd/system/ultra.service

# 3. Start + enable on boot
sudo systemctl daemon-reload
sudo systemctl enable --now ultra
sudo systemctl status ultra
```

The unit restarts the bot on crash (with backoff), passes `SIGINT` on stop
(graceful close of positions), and uses `ProtectSystem`/`NoNewPrivileges`
hardening. Manual supervisor alternative: `./deploy/start.sh paper`.

## Option 3 — Windows

```powershell
python -m venv venv
venv\Scripts\pip install -r requirements.txt
python main.py --mode paper --broker binance
```

For resilience, run the PowerShell supervisor (auto-restart on crash):

```powershell
powershell -ExecutionPolicy Bypass -File deploy\start.ps1 paper
```

Register it with Task Scheduler (At startup, Restart on failure) or NSSM as a
service. The health check `deploy\healthcheck.ps1` exits `0` when the PID file
is alive and the DB was written to within 5 minutes — wire it to your uptime
monitor.

## Dashboard & Monitoring

- **Dashboard:** `streamlit run src/dashboard/app.py` (separate process, port 8501).
- **Heartbeat:** the orchestrator logs a heartbeat every 30s (ticks/candles/
  signals/trades) and a `data/bot.pid` file is written on startup for probes.
- **Health gate (bot):** `deploy/healthcheck.ps1` (Windows) /
  `deploy/healthcheck.sh` (Linux/macOS, and the Docker HEALTHCHECK) check
  process + DB freshness; exit `0` = healthy.
- **Alerts:** set `ALERT_EMAIL` / `WEBHOOK_URL` in `.env` (used by the
  monitoring layer).

## Backups

- Windows: schedule `deploy/backup.ps1` daily (Task Scheduler). It snapshots
  the SQLite DB (WAL-safe copy) + logs into a dated zip and prunes old ones
  (`-KeepDays 14`).
- Linux/macOS: `deploy/backup.sh` does the same into a dated `.tar.gz` with
  `-mtime` pruning. Cron example (runs daily at 02:30 UTC):

```cron
30 2 * * * cd /opt/ultra && ./deploy/backup.sh 14 backups >> logs/backup.log 2>&1
```

- A systemd timer is the cleaner alternative to cron; both are equivalent for
  this job. The Docker image ships `deploy/backup.sh` too, so you can run it
  from a one-off container against the mounted `./data` volume.

## Upgrades

```bash
git pull                                # or docker compose pull / build
python -m pytest -q                     # run the suite
python scripts/iterate.py --full        # run the criteria loop
sudo systemctl restart ultra            # or: docker compose up -d --build
```

## Security notes

- `.env` is git-ignored; keep it `chmod 600`. Rotate `DERIV_API_TOKEN` if it
  was ever exposed.
- Prefer paper mode on public data (Binance needs no token). Live trading
  requires a funded account and a real token.
- Run the bot as an unprivileged user (Docker does this by default).
- The bot reads market data 24/7 on Binance; if the host is far from Binance
  (SSL handshake timeouts), use a VPS in a Binance-friendly region.

## Target production architecture (roadmap)

Direction for a 24/7 VPS deployment. The recommended flow: develop on Windows
→ CI on GitHub Actions → same Docker images on an Ubuntu VPS.

```
Internet → Ubuntu 24.04 VPS → Docker Compose
                                  ├── ultra (bot + Streamlit dashboard)   [done]
                                  ├── PostgreSQL (trades/analytics)       [planned]
                                  ├── Redis (cache/queues)                [planned]
                                  └── monitoring (Prometheus/Grafana)     [planned]
Nginx reverse proxy + HTTPS (optional)  →  dashboard.ultra.example        [planned]
```

| Component | Status | Notes |
|-----------|--------|-------|
| Docker + Compose (bot, volumes, log rotation, HEALTHCHECK, restart policy) | ✅ done | See Option 1 |
| CI (GitHub Actions: tests on 3.11/3.12 + image build) | ✅ done | `.github/workflows/ci.yml` |
| Backups + pruning (Windows & Linux scripts) | ✅ done | `deploy/backup.{ps1,sh}` |
| Health checks + restart policies (systemd, supervisors, container) | ✅ done | `deploy/healthcheck.{ps1,sh}` |
| VPS deployment | 🟡 next | Needs a VPS with Docker Engine |
| PostgreSQL | 🟡 planned | `DatabaseConfig.postgres_*` exists but `DatabaseManager` is SQLite-only; wiring needs a Postgres host to test against |
| Redis | 🟡 planned | Not wired; no cache/queue layer yet |
| Nginx + HTTPS | 🟡 planned | Fronts the Streamlit dashboard (8501) |
| Prometheus/Grafana | 🟡 planned | Container health + bot metrics endpoints don't exist yet |

VPS sizing for one bot: **2 vCPUs / 4 GB RAM / 40–60 GB SSD / Ubuntu 24.04**;
scale to 4–8 vCPU / 8–16 GB for multi-broker or backtests.

Phases: local (SQLite, paper) → Docker (same image, still SQLite paper) →
VPS (Docker + backup/health/restart) → scale-up (PostgreSQL, Redis, Nginx,
monitoring). SQLite remains the correct store for a single-instance bot;
PostgreSQL matters when multiple instances/analytics workloads appear.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Failed to connect` at startup | Check `BROKER` + network egress (Binance REST is flaky from some regions) |
| `DERIV_API_TOKEN required` | Only for `--mode live`; set the token or use paper |
| Deriv `InvalidToken` at auth | Token rejected by the server: confirm it is from `deriv.com/account/api-token`, matches the app id in `DERIV_APP_ID` (demo app ids like `1089` reject real-money tokens), and is not expired. The 2026 Deriv platform may require a registered app (developers.deriv.com) — otherwise run paper on Binance (`--broker binance`), which needs no token |
| Stale DB healthcheck | Bot not receiving ticks → check broker connectivity / symbols |
| Dashboard empty | Run the bot first so it can seed the DB, then start Streamlit |
| Container exits in a loop | `docker compose logs ultra`; confirm `.env` is present |

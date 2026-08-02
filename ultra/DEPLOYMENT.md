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
| `deploy/healthcheck.ps1` | Health probe (process + fresh DB writes) |
| `deploy/backup.ps1` | Daily DB + log backup with pruning |
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
docker compose logs -f ultra            # follow logs
docker compose down                     # stop (graceful SIGTERM)
```

- Runtime state is kept in `./data`, `./logs`, `./backups` (mounted volumes).
- Secrets are read from `.env` (`env_file`) — **never baked into the image**.
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
- **Health gate (bot):** `deploy/healthcheck.ps1` checks process + DB freshness.
- **Alerts:** set `ALERT_EMAIL` / `WEBHOOK_URL` in `.env` (used by the
  monitoring layer).

## Backups

- Windows: schedule `deploy/backup.ps1` daily (Task Scheduler). It snapshots
  the SQLite DB (WAL-safe copy) + logs into a dated zip and prunes old ones
  (`-KeepDays 14`).
- Linux: add a cron line or systemd timer calling an equivalent DB `VACUUM INTO`.

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

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Failed to connect` at startup | Check `BROKER` + network egress (Binance REST is flaky from some regions) |
| `DERIV_API_TOKEN required` | Only for `--mode live`; set the token or use paper |
| Stale DB healthcheck | Bot not receiving ticks → check broker connectivity / symbols |
| Dashboard empty | Run the bot first so it can seed the DB, then start Streamlit |
| Container exits in a loop | `docker compose logs ultra`; confirm `.env` is present |

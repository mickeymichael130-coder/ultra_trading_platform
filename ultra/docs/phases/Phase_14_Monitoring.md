# Phase 14 — Monitoring

## Objective

Prove the platform is alive and healthy: process state, DB freshness, broker
latency, and engine loops — surfaced as checks that a supervisor/healthcheck
can act on, and shown in the dashboard.

## Responsibilities

`health.py` + healthchecks (Phase 17 `deploy/healthcheck.*`):

- Process alive (`data/bot.pid`).
- DB recently written (candles/logs freshness).
- Internet reachability + broker ping/REST latency.
- Log critical failures to a place the dashboard filters (Logs page).

Scope: periodic probes, not deep metrics.

## Folder Structure

```
src/monitoring/
└── health.py      # health checks + API latency
deploy/healthcheck.ps1 / .sh   # ops probe (alive + DB freshness)
```

## Class Diagram

```
classDiagram
    class HealthMonitor {
        +check_db() / check_internet() / ping_latency()
        +report() -> status dict
    }
```

## Data Flow

Probe → bool/ms → logs + dashboard Logs page + up-time supervisor (Docker
HEALTHCHECK / systemd).

## Config

| Setting | Default | Purpose |
|---------|---------|---------|
| `ping_url` | per-broker | Latency ping target |
| `log_level` | INFO | Log verbosity |

## Testing

- Unit: reachable/unreachable DB + mock realpath, latency measured. ✅ (Phase 2).

## Definition of Done

- [x] healthcheck returns non-zero on failure, zero when healthy.
- [x] `deploy/healthcheck.*` wired into supervisor + compose HEALTHCHECK.

## Future

- Prometheus /health HTTP endpoint + Grafana dashboards.
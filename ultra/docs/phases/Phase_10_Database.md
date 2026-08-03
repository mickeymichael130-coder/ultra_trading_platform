# Phase 10 — Database

## Objective

Persist every artifact the platform produces — ticks→candles, signals, trades,
positions, account snapshots, and logs — in a single SQLite store that is safe
to read from the dashboard while the engine writes.

## Responsibilities

`DatabaseManager` wraps a SQLite connection used by every layer:

- Schema bootstrap (tables + indices) on first run.
- `save_trade` (with correct `exec_id` mapping), `get_signals`, candles, balance
  snapshots, system_logs.
- WAL mode so the dashboard can read without locking the engine.
- Defensive reader helpers for the dashboard (see `dashboard/db.py`).

## Folder Structure

```
src/database/
└── manager.py      # DatabaseManager + schema
data/ultra.db       # runtime store (gitignored; see Phase 17 for backup)
```

## Class Diagram

```
classDiagram
    class DatabaseManager {
        +connect(path)
        +migrate()
        +save_candle / save_trade / save_signal / write_log
        +get_signals / get_trades / get_candles
    }
```

## Data Flow

Every layer writes to the DB (execution, risk, candle builder, logger) and the
dashboard reads it.

## Configuration

| Setting | Default | Purpose |
|---------|---------|---------|
| `--db` / `DB_PATH` | `data/ultra.db` | Store location |
| WAL | on | read/write concurrency |

## Testing

- Schema migration, idempotent boostrap, trade/order mapping (Iteration 18). ✅
- Live append while dashboard reads (integration).

## Definition of Done

- [x] All runtime entities persist and reload.
- [x] 193-test suite green over the shared store.

## Future

- Postgres backend for analytics (config present, not wired).
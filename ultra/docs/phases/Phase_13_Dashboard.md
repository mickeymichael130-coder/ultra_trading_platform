# Phase 13 — Dashboard

## Objective

A read-only, dark trading-terminal UI over the engine DB: live state, markets,
positions, signals (incl. AI notes), analytics, backtesting, risk, and logs —
in one consistent 12-page Streamlit app.

## Responsibilities

- **Read-only monitoring.** It never makes trading decisions or places orders.
- Consistent sidebar navigation + status (engine online / kill switch).
- Cached DB reads + cached plotly figures so warm reruns stay fast.
- Graceful empty/missing-DB states on every page.

Must **not** call engine logic or mutate risk_state.

## Folder Structure

```
src/dashboard/
├── app.py          # 12 pages + dispatch + sidebar
├── theme.py        # dark palette + global CSS
├── components.py   # KPI grid, badges, page header
├── charts.py       # cached plotly builders (st.cache_data 5s)
└── db.py           # cached defensive SQLite readers
```

## Class/Page Overview

Dashboard · Markets · Trading Engine · Portfolio · Trade History · Analytics ·
Backtesting · Strategy Lab · Risk Center · Signals · Settings · Logs.

## Performance

- `kpi_row` emits all cards as **one** HTML grid (fewer DOM elements).
- `st.cache_data` on charts + 3s DB TTL (see `charts.py`/`db.py`).
- Warm reruns measured 1.1–2.3s (Iteration 20); cold = environment cost.

## Data Flow

Dashboard ← `data/ultra.db` only. Engine writes; dashboard reads. C13 gate
(scripts/criteria.py) enforces no deprecated `use_container_width` + cached
charts.

## Testing

- 5 AppTests smoke the unified old sidebar invariants (DB path + nav radio +
  AI-note expanders). ✅

## Definition of Done

- [x] 12 pages render on a real DB without errors.
- [x] Warm reruns < ~3s/page (see Iterations 19–20).
- [x] C13 perf gate green; 193-test suite green.

## Future

- Dedicated "AI Research" page (regime/momentum history).
- Editable config (read-write risk params) behind an auth flag.
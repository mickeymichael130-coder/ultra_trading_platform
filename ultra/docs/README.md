# UATP — Living Engineering Manual

**Universal Algorithmic Trading Platform (UATP)** — Version 1.0 Enterprise Blueprint.

This is the living specification for the platform. It is written **before** and
**alongside** code: every module in `src/` is documented here, and every new
module must land here first. The manual is version-controlled Markdown so it
stays in sync with the repo and can be exported to PDF/HTML later.

## Reading Order

| Doc | What it answers |
|-----|-----------------|
| `00_Project_Overview.md` | Why are we building this? Goals, non-goals, principles. |
| `01_System_Architecture.md` | How is the system put together? Layers, data flow, broker abstraction. |
| `02_Domain_Model.md` | What are the broker-neutral objects (Order, Trade, Position, Account, MarketTick, Candle, Signal)? |
| `03_Project_Structure.md` | Where does each file live, now and in the target layout? |
| `phases/` | One doc per phase: objectives, interfaces, sequence, testing, definition of done. |
| `diagrams/` | Mermaid diagrams (version-controlled, render in any Markdown viewer). |

## Relationship to `BLUEPRINT_CHECKLIST.md`

- **`docs/` = the specification.** What the platform is and how each piece is built.
- **`BLUEPRINT_CHECKLIST.md` = the progress tracker.** Pass/fail status per phase,
  iteration log, and open items.

Update the checklist when code changes land. Update `docs/` when the *design*
changes (or before code changes land).

## Standards

- Python 3.11+ · type hints throughout · docstrings on public classes/methods
- Separation of concerns: layers communicate through defined interfaces, never
  directly through broker internals
- Dependency injection for brokers and strategies
- Environment-based configuration (`.env`, no hardcoded credentials)
- Unit tests for core logic; the suite must stay green (`python -m pytest`)
- Diagrams in Mermaid so they version-control cleanly

## Decision Record Index

Significant architecture decisions are logged as ADRs at the bottom of
`00_Project_Overview.md`. Current decisions:

- ADR-001: Build a **broker-agnostic platform**, not a Deriv bot.
- ADR-002: Broker-neutral **core domain models**; adapters translate to/from each broker API.
- ADR-003: **Documentation first** — the manual is the spec, code follows it.

## Status

Phase status is tracked in `BLUEPRINT_CHECKLIST.md` (all 17 blueprint phases ✅
through iteration 7; 164 tests passing).

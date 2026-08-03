# Phase 15 — Live Trading

**Status: token-gated.** Requires a working broker token + a full live session.

## Objective

Run the entire pipeline against a live broker account (`--mode live`):
streaming ticks → candles → signals → genuine fills → positions/SL→TP → closing
with real money, with all the safety gates (paper logic + risk + kill switch)
still enforced.

## Architecture

Identical runtime flow to paper — same orchestrator, indicators, strategy,
risk, position manager. Only difference: `ExecutionEngine` talks to real order
endpoints and `get_balance()` syncs real account state (live), instead of
simulated fills.

## Key Gates

- A valid **broker token** (Deriv: registered app + PAT +
  OTP-authenticated WS; Binance: live API keys).
- Paper validation of a full session first (ticks→candles→signals→paper fills).
- Dashboard/permission in **live** mode is explicitly read-only.

## Task

1. [ ] Provide a valid broker token in `.env`.
2. [ ] `python main.py --mode live` streams a candidate live session.
3. [ ] Validate real fills, SL/TP execution, `get_balance()` live snapshots.
4. [ ] Confirm no dependency on simulated fill code in live mode.

## Testing / Validation

- Deterministic on-record paper parity first.
- Live smoke: tick count, candle count, signal count, closed trade count, 0 errors.

## Definition of Done (when unlocked)

- [ ] Full live session completes with nothing but real state.
- [ ] No paper-only logic leaks into live path.
- [ ] kill switch instant halt verified.

## Blockers (current)

Deriv rejects `subscribe` streams unauthenticated with `InvalidToken`/`InvalidAppID`;
requires a registered app + PAT + OTP-authenticated WS. Deferred (see checklist
"Live Deriv streaming").
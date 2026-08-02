#!/usr/bin/env bash
# ULTRA auto-restart supervisor (Linux/macOS).
# Keeps the bot alive: on crash it is relaunched, with a bounded backoff.
#
# Usage:
#   ./deploy/start.sh paper
#   ./deploy/start.sh live
set -euo pipefail

MODE="${1:-paper}"
BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${BOT_DIR}/venv/bin/python"
LOG_DIR="${BOT_DIR}/logs"
SUPERVISOR_LOG="${LOG_DIR}/supervisor.log"

mkdir -p "$LOG_DIR"

log() { echo "$(date '+%F %T') $*" | tee -a "$SUPERVISOR_LOG"; }

log "ULTRA supervisor starting (mode=$MODE, dir=$BOT_DIR)"

CONSECUTIVE_FAILURES=0
MAX_CONSECUTIVE=10

while true; do
    log "Launching bot (mode=$MODE) ..."
    "$PYTHON" "$BOT_DIR/main.py" --mode "$MODE" >> "$SUPERVISOR_LOG" 2>&1
    EXIT_CODE=$?

    if [ "$EXIT_CODE" -eq 130 ] || [ "$EXIT_CODE" -eq 0 ]; then
        # 130 = SIGINT (Ctrl+C / systemd stop), 0 = clean exit -> do not restart.
        log "Bot stopped cleanly (code=$EXIT_CODE). Supervisor exiting."
        exit 0
    fi

    CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
    log "Bot exited unexpectedly (code=$EXIT_CODE). Attempt $CONSECUTIVE_FAILURES."

    if [ "$CONSECUTIVE_FAILURES" -ge "$MAX_CONSECUTIVE" ]; then
        log "Too many consecutive failures. Giving up - notify an operator."
        exit 1
    fi

    sleep 5
done

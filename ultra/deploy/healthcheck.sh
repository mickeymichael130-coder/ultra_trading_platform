#!/usr/bin/env bash
# ULTRA health check (Linux/macOS). Mirrors deploy/healthcheck.ps1.
# Verifies the bot process is alive and the DB is being written to.
# Exit 0 = healthy, 1 = unhealthy. For use with uptime monitors / cron /
# Docker HEALTHCHECK.
#
# Usage:
#   deploy/healthcheck.sh [max_age_seconds]
set -uo pipefail

MAX_AGE="${1:-300}"
BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$BOT_DIR/data/bot.pid"
DB_PATH="$BOT_DIR/data/ultra.db"
EXIT_CODE=0

check() {
    local label="$1" ok="$2" detail="$3"
    if [ "$ok" = "1" ]; then
        echo "OK   $label ($detail)"
    else
        echo "FAIL $label ($detail)"
        EXIT_CODE=1
    fi
}

# 1. PID file exists and process is running.
if [ -f "$PID_FILE" ]; then
    BOT_PID="$(head -n1 "$PID_FILE" | tr -d '[:space:]')"
    if [ -n "$BOT_PID" ] && kill -0 "$BOT_PID" 2>/dev/null; then
        check "bot process" 1 "pid=$BOT_PID"
    else
        check "bot process" 0 "pid=$BOT_PID not running"
    fi
else
    check "pid file" 0 "data/bot.pid missing"
fi

# 2. Database was modified recently (bot is actively persisting state).
if [ -f "$DB_PATH" ]; then
    AGE="$(($(date +%s) - $(stat -c %Y "$DB_PATH" 2>/dev/null || echo 0)))"
    if [ "$AGE" -le "$MAX_AGE" ]; then
        check "database writes" 1 "last write ${AGE}s ago"
    else
        check "database writes" 0 "stale, last write ${AGE}s ago"
    fi
else
    check "database file" 0 "data/ultra.db missing"
fi

exit "$EXIT_CODE"

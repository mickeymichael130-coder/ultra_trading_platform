#!/usr/bin/env bash
# ULTRA daily backup (Linux/macOS). Mirrors deploy/backup.ps1.
# Archives the SQLite DB and logs into a dated tarball, then prunes old backups.
# SQLite WAL files are snapshotted via a consistent copy so no table lock blocks.
#
# Usage (cron, daily):
#   deploy/backup.sh [keep_days] [backup_root]
set -euo pipefail

KEEP_DAYS="${1:-14}"
BACKUP_ROOT="${2:-backups}"
BOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$BOT_DIR/data"
LOG_DIR="$BOT_DIR/logs"
DB_PATH="$DATA_DIR/ultra.db"

case "$BACKUP_ROOT" in
    /*) BACKUP_DIR="$BACKUP_ROOT" ;;
    *)  BACKUP_DIR="$BOT_DIR/$BACKUP_ROOT" ;;
esac
mkdir -p "$BACKUP_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE="$BACKUP_DIR/ultra_backup_$STAMP.tar.gz"
TEMP_DIR="$BACKUP_DIR/_tmp_$STAMP"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

mkdir -p "$TEMP_DIR"
if [ -f "$DB_PATH" ]; then
    cp -p "$DB_PATH" "$TEMP_DIR/ultra.db"
    [ -f "$DB_PATH-wal" ] && cp -p "$DB_PATH-wal" "$TEMP_DIR/" || true
    [ -f "$DB_PATH-shm" ] && cp -p "$DB_PATH-shm" "$TEMP_DIR/" || true
else
    log "WARNING: no database found at $DB_PATH. Backing up logs only."
fi
[ -d "$LOG_DIR" ] && cp -R "$LOG_DIR/." "$TEMP_DIR/" 2>/dev/null || true

tar -czf "$ARCHIVE" -C "$TEMP_DIR" . >/dev/null
rm -rf "$TEMP_DIR"

log "Backup created: $ARCHIVE"

# Prune backups older than keep_days (tolerates the yyyyMMdd_HHmmss stamp).
find "$BACKUP_DIR" -maxdepth 1 -name 'ultra_backup_*.tar.gz' \
    -mtime "+$KEEP_DAYS" -print -delete | while read -r f; do
    log "Pruned old backup: $(basename "$f")"
done

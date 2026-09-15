#!/usr/bin/env bash
# Nightly backup of the Garden Tracker database.
# Run from cron as the garden user (see README for the crontab line).
set -euo pipefail

APP_DIR="${GARDEN_APP_DIR:-/opt/garden}"
DATA_DIR="${GARDEN_DATA:-$APP_DIR/data}"
DEST="${GARDEN_BACKUP_DIR:-$DATA_DIR/backups}"   # e.g. an NFS mount
KEEP="${GARDEN_BACKUP_KEEP:-30}"                  # how many to retain

stamp="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DEST"
out="$DEST/garden-$stamp.db.gz"

# SQLite's online backup API gives a consistent copy even while the service
# is running (WAL-safe). Uses the app's own venv so sqlite3 CLI isn't needed.
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
"$APP_DIR/venv/bin/python" - "$DATA_DIR/garden.db" "$tmp" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close(); src.close()
PY
gzip -c "$tmp" > "$out"
echo "wrote $out"

# Prune old backups, keep the newest $KEEP.
ls -1t "$DEST"/garden-*.db.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f

#!/bin/sh
# First start only: import the bundled seed CSV into a fresh database.
# Set GARDEN_SEED=0 to start with an empty database instead.
set -e
DB="${GARDEN_DB:-${GARDEN_DATA:-/data}/garden.db}"
if [ ! -f "$DB" ] && [ "${GARDEN_SEED:-1}" != "0" ] && [ -f /app/seed/garden_produce.csv ]; then
  echo "entrypoint: new database, importing seed/garden_produce.csv"
  /app/venv/bin/python -m app.seed /app/seed/garden_produce.csv
fi
exec "$@"

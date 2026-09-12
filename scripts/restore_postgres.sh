#!/usr/bin/env bash
# Restores a CreatorOS Postgres backup created by backup_postgres.sh.
# Usage: scripts/restore_postgres.sh backups/creatoros_20260101_000000.sql.gz
#
# Refuses to run without an explicit file argument and asks for confirmation
# before touching the target database — this is a destructive operation.
set -euo pipefail

cd "$(dirname "$0")/.."
source .env 2>/dev/null || true

FILE="${1:?Usage: scripts/restore_postgres.sh <backup_file.sql.gz>}"
if [ ! -f "$FILE" ]; then
  echo "Backup file not found: $FILE" >&2
  exit 1
fi

: "${POSTGRES_USER:=creatoros}"
: "${POSTGRES_DB:=creatoros}"
: "${POSTGRES_HOST:=localhost}"
: "${POSTGRES_PORT:=5432}"

echo "This will REPLACE all data in ${POSTGRES_DB}@${POSTGRES_HOST}:${POSTGRES_PORT}."
read -r -p "Type the database name (${POSTGRES_DB}) to confirm: " CONFIRM
if [ "$CONFIRM" != "$POSTGRES_DB" ]; then
  echo "Confirmation did not match. Aborting."
  exit 1
fi

echo "Restoring from $FILE ..."
gunzip -c "$FILE" | PGPASSWORD="${POSTGRES_PASSWORD:-}" psql \
  -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB"

echo "Restore complete."

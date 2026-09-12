#!/usr/bin/env bash
# Dumps the CreatorOS Postgres database to backups/creatoros_<timestamp>.sql.gz.
# Never deletes old backups automatically — retention is a deliberate,
# separate decision (see docs/operations.md).
set -euo pipefail

cd "$(dirname "$0")/.."
source .env 2>/dev/null || true

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP="$(date -u +%Y%m%d_%H%M%S)"
OUT_FILE="${BACKUP_DIR}/creatoros_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

: "${POSTGRES_USER:=creatoros}"
: "${POSTGRES_DB:=creatoros}"
: "${POSTGRES_HOST:=localhost}"
: "${POSTGRES_PORT:=5432}"

echo "Backing up ${POSTGRES_DB}@${POSTGRES_HOST}:${POSTGRES_PORT} -> ${OUT_FILE}"
PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump \
  -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --no-owner --format=plain | gzip > "$OUT_FILE"

echo "Backup complete: $OUT_FILE ($(du -h "$OUT_FILE" | cut -f1))"

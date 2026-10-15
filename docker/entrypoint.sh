#!/usr/bin/env bash
set -euo pipefail

log() { printf '[entrypoint] %s\n' "$*"; }

# ---------- Validate required env ----------
: "${POSTGRES_HOST:?POSTGRES_HOST is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"

# ---------- Run migrations ----------
# Idempotent. Runs against POSTGRES_DB (dev DB for app, test DB for test).
log "Running alembic migrations against ${POSTGRES_HOST}/${POSTGRES_DB}..."
if ! alembic -c /app/alembic.ini upgrade head; then
    log "ERROR: alembic upgrade failed"
    exit 1
fi
log "Migrations complete."

# ---------- Hand off to CMD ----------
log "Executing: $*"
exec "$@"

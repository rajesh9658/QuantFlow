#!/usr/bin/env bash
set -euo pipefail

log() { printf '[docker-test] %s\n' "$*"; }

cleanup() {
    log "Tearing down docker environment..."
    docker compose down -v
}
trap cleanup EXIT

log "Starting postgres and redis services..."
docker compose up -d --wait postgres redis

log "Services are healthy. Running test suite via app container..."
docker compose run --rm app pytest "$@"

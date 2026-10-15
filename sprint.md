QuantFlow Local Multi-Exchange Docker Setup
This setup runs QuantFlow, PostgreSQL, and Redis locally with proper healthcheck-based startup ordering, secrets from a gitignored .env, automatic Alembic migrations before serving traffic, and a dedicated way to run the test suite against real Postgres/Redis using the same image.

File Tree
text
quantflow/
├── docker-compose.yml
├── Dockerfile
├── .dockerignore
├── .env.example                 # committed template
├── .env                         # gitignored, real secrets
├── .gitignore                   # must contain .env
├── alembic.ini
├── requirements.txt
├── requirements-dev.txt
├── docker/
│   ├── entrypoint.sh
│   └── postgres-init/
│       └── 01-create-test-db.sql
├── quantflow/
│   └── ...
└── tests/
    └── ...
1. docker-compose.yml
yaml
name: quantflow

services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:?POSTGRES_USER is required}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}
      POSTGRES_DB: ${POSTGRES_DB:-quantflow}
      # Ensures passwords hashed with scram-sha-256
      POSTGRES_INITDB_ARGS: "--auth-host=scram-sha-256"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./docker/postgres-init:/docker-entrypoint-initdb.d:ro
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    healthcheck:
      test:
        - CMD-SHELL
        - pg_isready -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -h 127.0.0.1
      interval: 5s
      timeout: 5s
      retries: 12
      start_period: 10s

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command:
      - redis-server
      - --appendonly
      - "yes"
      - --save
      - "60 1"
    volumes:
      - redis_data:/data
    ports:
      - "${REDIS_PORT:-6379}:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "-h", "127.0.0.1", "ping"]
      interval: 5s
      timeout: 3s
      retries: 12
      start_period: 5s

  app:
    build:
      context: .
      dockerfile: Dockerfile
      target: runtime
    image: quantflow:local
    restart: unless-stopped
    env_file:
      - .env
    environment:
      # Compose-internal service names override the .env defaults
      POSTGRES_HOST: postgres
      POSTGRES_PORT: "5432"
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      APP_ENV: ${APP_ENV:-development}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      LOG_FORMAT: ${LOG_FORMAT:-console}
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    ports:
      - "${APP_PORT:-8000}:8000"
    # Source mount enables uvicorn --reload during local dev.
    # Read-only so the container can never write into the repo.
    volumes:
      - ./quantflow:/app/quantflow:ro
      - ./alembic:/app/alembic:ro
      - ./alembic.ini:/app/alembic.ini:ro
      - ./config:/app/config:ro
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://127.0.0.1:8000/health"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 30s
    command:
      - uvicorn
      - quantflow.main:app
      - --host
      - "0.0.0.0"
      - --port
      - "8000"
      - --reload

  # -----------------------------------------------------------------
  # Test runner — same image, separate database, activated via profile.
  #   docker compose --profile test run --rm test
  #   docker compose --profile test run --rm test pytest tests/unit
  # -----------------------------------------------------------------
  test:
    build:
      context: .
      dockerfile: Dockerfile
      target: runtime
    image: quantflow:local
    profiles: ["test"]
    env_file:
      - .env
    environment:
      POSTGRES_HOST: postgres
      POSTGRES_PORT: "5432"
      POSTGRES_DB: quantflow_test
      REDIS_HOST: redis
      REDIS_PORT: "6379"
      REDIS_DB: "1"
      APP_ENV: test
      LOG_LEVEL: WARNING
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    # Source mount keeps test code in sync with the working tree.
    # pytest cache is redirected to tmpfs because the mount is read-only.
    volumes:
      - ./quantflow:/app/quantflow:ro
      - ./tests:/app/tests:ro
      - ./alembic:/app/alembic:ro
      - ./alembic.ini:/app/alembic.ini:ro
    tmpfs:
      - /app/.pytest_cache
      - /tmp
    command: ["pytest", "-xvs", "-p", "no:cacheprovider", "tests/"]

volumes:
  postgres_data:
  redis_data:
Startup ordering — why this works
depends_on alone only waits for the container to start, not to be ready.

condition: service_healthy forces Compose to wait for the target's healthcheck to report healthy before starting the dependent service.

postgres uses pg_isready, which checks the server accepts connections and the target database exists.

redis uses redis-cli ping, which confirms the server is accepting commands.

start_period gives the service time to initialize without marking failed healthchecks during warm-up.

No sleep-based waits are used anywhere.

2. Dockerfile
dockerfile
# syntax=docker/dockerfile:1.7

# ---------- Builder ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy lockfiles first for layer caching
COPY requirements.txt requirements-dev.txt ./

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install -r requirements.txt -r requirements-dev.txt

# ---------- Runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# curl for healthcheck; tini for proper PID 1 signal handling
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r quantflow \
    && useradd -r -g quantflow -d /app -s /usr/sbin/nologin quantflow

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Copy project (no .env — excluded by .dockerignore)
COPY --chown=quantflow:quantflow . .

RUN chmod +x /app/docker/entrypoint.sh

USER quantflow

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
CMD ["uvicorn", "quantflow.main:app", "--host", "0.0.0.0", "--port", "8000"]
Notes:

Non-root user quantflow for runtime safety.

tini reaps zombies and forwards SIGTERM to uvicorn.

.env never enters the image — see .dockerignore.

3. docker/entrypoint.sh
bash
#!/usr/bin/env bash
set -euo pipefail

log() { printf '[entrypoint] %s\n' "$*"; }

# ---------- Validate required env ----------
: "${POSTGRES_HOST:?POSTGRES_HOST is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"

# ---------- Run migrations ----------
# Idempotent. Runs against POSTGRES_DB (dev DB for `app`, test DB for `test`).
log "Running alembic migrations against ${POSTGRES_HOST}/${POSTGRES_DB}..."
if ! alembic -c /app/alembic.ini upgrade head; then
    log "ERROR: alembic upgrade failed"
    exit 1
fi
log "Migrations complete."

# ---------- Hand off to CMD ----------
log "Executing: $*"
exec "$@"
Behavior:

Runs on every container start. Alembic upgrade head is idempotent, so this is safe for restarts and for the test service.

Fails fast if migrations fail — the app never serves traffic against an out-of-date schema.

Handles docker compose run --rm app bash gracefully (migrations run, then the shell opens).

For the test service, POSTGRES_DB=quantflow_test ensures migrations target the test database, not the dev one.

4. docker/postgres-init/01-create-test-db.sql
Postgres runs any *.sql files in /docker-entrypoint-initdb.d only on first initialization (empty data volume). This creates the test database alongside the main one:

sql
-- Runs as the superuser (POSTGRES_USER) once, on first init.
CREATE DATABASE quantflow_test OWNER :"POSTGRES_USER";
If you change POSTGRES_USER, this script adapts. To recreate from scratch:

bash
docker compose down -v
docker compose up -d postgres
5. .dockerignore
text
# --- Secrets (CRITICAL) ---
.env
.env.*
!.env.example

# --- Python ---
__pycache__/
*.py[cod]
*.egg-info/
.eggs/
build/
dist/
.venv/
venv/
env/

# --- Caches / coverage ---
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
.coverage.*
coverage.json
htmlcov/
.tox/

# --- VCS / IDE ---
.git/
.gitignore
.gitattributes
.idea/
.vscode/
*.swp

# --- Project artifacts ---
logs/
*.log
data/
notebooks/
go_live/attestation.json
*.parquet
*.csv.gz

# --- OS ---
.DS_Store
Thumbs.db

# --- Docker ---
Dockerfile
docker-compose*.yml
.dockerignore
Critical: .env is excluded, so COPY . . in the Dockerfile cannot leak secrets into image layers. Only .env.example is allowed through as a reference.

6. .env.example
bash
# =====================================================================
# QuantFlow local environment
# Copy to .env and fill in real values:
#     cp .env.example .env
# .env is gitignored and MUST NOT be committed.
# =====================================================================

# ---------- Application ----------
APP_ENV=development              # development | test | paper | live
APP_PORT=8000
LOG_LEVEL=INFO                   # DEBUG | INFO | WARNING | ERROR
LOG_FORMAT=console               # console (dev) | json (prod)

# ---------- PostgreSQL ----------
# POSTGRES_HOST and POSTGRES_PORT are overridden by docker-compose
# for in-container networking (postgres:5432). These values are used
# only when running the app outside Docker.
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=quantflow
POSTGRES_PASSWORD=change_me_use_a_long_random_string
POSTGRES_DB=quantflow

# ---------- Redis ----------
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=                  # leave blank for local dev

# ---------- Exchange credentials ----------
# Referenced from quantflow.yaml as:
#     credentials_ref: "env:BINANCE_API_KEY"
# Never commit real keys.
BINANCE_API_KEY=replace_with_real_key
BINANCE_API_SECRET=replace_with_real_secret

BYBIT_API_KEY=replace_with_real_key
BYBIT_API_SECRET=replace_with_real_secret

# ---------- Go-live attestation ----------
# Generate with:  openssl rand -hex 32
# Do NOT reuse across environments.
QUANTFLOW_GO_LIVE_SIGNING_KEY=replace_with_random_64_hex_chars

# ---------- Optional overrides ----------
# Override the default event bus backend: in_memory | redis
QUANTFLOW_EVENT_BUS_TYPE=in_memory
Also add to .gitignore (project root):

gitignore
.env
.env.*
!.env.example
7. Sample quantflow.yaml (excerpt) — multi-exchange, multi-service
For the compose environment to actually connect to both exchanges, quantflow.yaml must be updated to the list shape from the multi-exchange spec:

yaml
exchanges:
  - exchange_id: binance
    type: binance
    enabled: true
    credentials_ref: "env:BINANCE_API_KEY"
    symbols:
      "BTC/USDT": "BTCUSDT"
      "ETH/USDT": "ETHUSDT"
    rate_limit_overrides:
      requests_per_second: 20

  - exchange_id: bybit
    type: bybit
    enabled: true
    credentials_ref: "env:BYBIT_API_KEY"
    symbols:
      "BTC/USDT": "BTCUSDT"
      "ETH/USDT": "ETHUSDT"
    rate_limit_overrides:
      requests_per_second: 10

database:
  host: "{{env:POSTGRES_HOST}}"
  port: "{{env:POSTGRES_PORT}}"
  user: "{{env:POSTGRES_USER}}"
  password: "{{env:POSTGRES_PASSWORD}}"
  name: "{{env:POSTGRES_DB}}"

redis:
  host: "{{env:REDIS_HOST}}"
  port: "{{env:REDIS_PORT}}"
  db: "{{env:REDIS_DB}}"
8. Usage
First-time setup
bash
cp .env.example .env
# edit .env — at minimum set POSTGRES_PASSWORD and QUANTFLOW_GO_LIVE_SIGNING_KEY
docker compose build
Run the app (with hot reload)
bash
docker compose up
# → postgres and redis start
# → both healthchecks pass
# → app container starts, entrypoint runs alembic upgrade head
# → uvicorn serves on http://localhost:8000
Run the test suite (against real Postgres + Redis)
bash
# Full suite
docker compose --profile test run --rm test

# A specific file
docker compose --profile test run --rm test pytest tests/integration/test_order_flow.py

# With verbose + stop on first failure (already the default)
docker compose --profile test run --rm test pytest -xvs tests/integration
The test service:

Uses the same image as the app (quantflow:local), guaranteeing the code under test is the code that runs.

Connects to real Postgres (quantflow_test database) and real Redis (logical DB 1).

Runs migrations automatically against the test DB.

Isolated from dev data — tests never touch the quantflow database.

Inspect / debug
bash
# Open a shell inside the app image
docker compose run --rm app bash

# Open psql
docker compose exec postgres psql -U quantflow -d quantflow

# Tail logs
docker compose logs -f app
Reset everything
bash
docker compose down -v          # removes postgres_data and redis_data volumes
docker compose build --no-cache
docker compose up
9. Design Notes
Requirement	How it's satisfied
App waits for Postgres/Redis healthily	depends_on: { condition: service_healthy } + pg_isready / redis-cli ping healthchecks. No sleep.
Secrets never baked into image	.env excluded in .dockerignore; loaded only via env_file: at runtime.
Migrations run before traffic	docker/entrypoint.sh runs alembic upgrade head and execs the app only on success.
Tests hit real Postgres/Redis	test service uses the same image, POSTGRES_DB=quantflow_test, REDIS_DB=1, real service dependencies.
Same image for app and test	Both build from target: runtime; no separate test image.
Concurrent exchange connections	Config-driven list (Sprint 14); credentials resolved from .env through EnvSecretsProvider.
Reproducible local environment	Named volumes, non-root user, tini as PID 1, healthcheck-gated startup.
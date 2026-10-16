# QuantFlow

QuantFlow is an async, event-driven quantitative trading, backtesting, and execution framework built with Python 3.12, FastAPI, PostgreSQL, Redis, and a real-time React 18 / Vite 5 trading dashboard.

---

## Architecture Overview

- **Backend Composition Root**: `quantflow/main.py` with FastAPI lifespan orchestrating `ExchangeRegistry`, `MarketDataEngine`, `RiskEngine`, `PortfolioEngine`, `PaperExecutionHandler`, `PluginLoader`, and `AsyncIOScheduler`.
- **Event Bus**: In-memory and Redis stream event buses emitting real-time telemetry (trades, signals, risk status, orderbook ticks).
- **REST & WebSocket API**: Versioned at `/api/v1` with Prometheus metrics exposition at `/metrics` and authenticated bidirectional WebSocket streams at `/ws/dashboard`.
- **Trading Dashboard**: React 18, TypeScript, Tailwind CSS, TanStack Query, and Zustand stores with zero hardcoded values, strict reconnect guards, and emergency stop safeguards.

---

## Getting Started (Local Development)

### Prerequisites
- Python 3.12+ (or [uv](https://astral.sh/uv))
- Node.js 20+ & npm
- Docker Engine & Docker Compose

### 1. Configure Local Environment
```bash
cp .env.example .env
```

### 2. Start the Stack (Postgres, Redis, Backend, Frontend)
```bash
docker compose up -d --build
```
- **Trading Dashboard**: [http://localhost:3000](http://localhost:3000)
- **API & Health**: [http://localhost:8000/health](http://localhost:8000/health)
- **Prometheus Metrics**: [http://localhost:8000/metrics](http://localhost:8000/metrics)

---

## Running Test Suites

### Backend Unit & Integration Tests
```bash
# Run locally using uv
uv run pytest -v

# Or run in isolated Docker test container with PostgreSQL & Redis
docker compose --profile test run --rm test
```

### Frontend Vitest & Bundle Build
```bash
cd dashboard
npm run test
npm run build
```

### Zero Hardcoded Values Verification
```bash
# Cross-platform check
python scripts/check_no_hardcoded.py

# Or in Linux / Git Bash
bash scripts/check-no-hardcoded.sh
```

---

## Manual Production Deployment

To deploy to your production server:

1. **Copy repository to your production server.**
2. **Create production configuration:**
   ```bash
   cp .env.production.example .env.production
   nano .env.production
   ```
   Provide your:
   - `DOMAIN`: Host domain name (e.g. `trading.yourdomain.com`)
   - `POSTGRES_PASSWORD`: Secure database password
   - `REDIS_PASSWORD`: Secure Redis password
   - `JWT_SECRET_KEY`: Cryptographically secure secret
   - Exchange credentials & keys (e.g. `BINANCE_API_KEY`, `BINANCE_API_SECRET`)
3. **Launch Production Stack with Automatic TLS (Caddy):**
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```
4. **Refer to [RUNBOOK.md](file:///f:/QuantFlow/RUNBOOK.md) for operations, secret rotation, and alert response.**

---

## Key Documentation
- [sprint.md](file:///f:/QuantFlow/sprint.md): Complete Phase A & B Implementation Specifications.
- [DECISIONS.md](file:///f:/QuantFlow/DECISIONS.md): Architectural decisions and rationale.
- [RUNBOOK.md](file:///f:/QuantFlow/RUNBOOK.md): Production operations runbook.

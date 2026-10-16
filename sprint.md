You are the lead full-stack engineer for QuantFlow, a modular async quantitative trading platform. The backend specification is complete (Sprints 0–15). Your task has two phases: (A) boot the backend in a running state and (B) build the production-grade frontend that talks to it. Ship both to a live production environment.

Work autonomously. Do not ask for clarification on details already specified in this prompt or the spec files. When a decision is ambiguous, pick the option that maximizes determinism, testability, and observability, and document it in DECISIONS.md.

Phase A — Backend: bring it to a running state
A1. Repository layout (enforce this)
text
quantflow/
├── pyproject.toml # PEP 621, hatchling backend
├── alembic.ini
├── alembic/versions/
├── config/
│ ├── quantflow.yaml # multi-exchange shape (Sprint 14)
│ └── quantflow.example.yaml
├── quantflow/
│ ├── **init**.py
│ ├── main.py # FastAPI app factory
│ ├── core/ # interfaces.py, exchange_registry.py, symbol_mapper.py
│ ├── clock/ # clock.py (SystemClock, SimulatedClock)
│ ├── events/ # events.py (pydantic v2 models)
│ ├── config/ # config_manager.py, secrets.py
│ ├── logging/ # logging_setup.py (structlog)
│ ├── di/ # di_container.py
│ ├── bus/ # event_bus.py (in-memory + redis implementations)
│ ├── adapters/ # binance.py, bybit.py
│ ├── market_data/ # engine.py, local_order_book.py
│ ├── strategy/ # engine.py, plugin_loader.py
│ ├── risk/ # engine.py
│ ├── execution/ # paper_handler.py, order_simulator.py, fees.py
│ ├── portfolio/ # engine.py
│ ├── analytics/ # engine.py, aggregators.py
│ ├── replay/ # engine.py, event_store.py
│ ├── backtest/ # engine.py, sweep.py, walk_forward.py, significance.py
│ ├── go_live/ # checks.py, gate.py, guard.py, attest.py
│ ├── api/ # FastAPI routers — see A3
│ └── scheduler/ # async_io_scheduler.py
├── tests/
│ ├── unit/
│ ├── integration/
│ └── e2e/
├── docker/
│ ├── entrypoint.sh
│ └── postgres-init/01-create-test-db.sql
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env.example
└── README.md
A2. Bring the backend to a running state
Create every module described in Sprints 0–15 with the exact signatures given there. No placeholders, no ..., no pass # TODO. Every method must be implemented or raise NotImplementedError with a clear message if truly out of scope (and there should be almost none).

Implement the composition root at quantflow/main.py:

create_app() returns a FastAPI instance.

On startup (lifespan): resolve config → configure logging → construct DI container → build ExchangeRegistry → build MarketDataEngine → build strategies via PluginLoader → build RiskEngine, PaperExecutionHandler/LiveExecutionHandler, PortfolioEngine, AnalyticsEngine, Scheduler → subscribe everything → start the EventBus.

On shutdown: reverse order, with cancellation on timeout.

The app must refuse to start in live mode without a valid attestation (Sprint 15).

Provide both InMemoryEventBus and RedisStreamEventBus behind the same ABC. Selection is driven by QUANTFLOW_EVENT_BUS_TYPE.

Make the whole stack start with zero live credentials in paper mode: use a SyntheticEventStore that generates deterministic fake ticker/orderbook/trade streams so the app runs end-to-end without touching an exchange.

Run every test suite in tests/. All tests must pass. Achieve the coverage gates from Sprint 15 (85% line, 75% branch, 95% on critical modules). If a test is missing for a code path you added, write it.

Verify the stack runs with:

bash
docker compose up -d postgres redis
docker compose run --rm app alembic upgrade head
docker compose up app
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/metrics | head
All three must succeed before moving to Phase B.

A3. Required FastAPI surface
Implement these routers under /api/v1 (contracts from the frontend spec):

REST endpoints

Method Path Returns
GET /health {"status": "ok", "version": "...", "started_at": "..."}
GET /metrics Prometheus exposition format
GET /api/v1/portfolio current portfolio snapshot
GET /api/v1/portfolio/history?from=&to=&interval= equity curve time series
GET /api/v1/trades?from=&to=&strategy=&symbol=&exchange_id=&limit=&offset= paginated fills
GET /api/v1/orders?status=&strategy=&exchange_id=&limit=&offset= paginated orders
GET /api/v1/signals?from=&to=&strategy=&exchange_id=&limit=&offset= paginated signals
GET /api/v1/strategies list of loaded plugins with per-strategy metrics
GET /api/v1/strategies/{name}/metrics detailed strategy performance
GET /api/v1/strategies/{name}/config current strategy config
PATCH /api/v1/strategies/{name}/config update config (hot-reloadable values only)
POST /api/v1/strategies/{name}/toggle enable/disable
GET /api/v1/risk/status current risk state
GET /api/v1/risk/config risk thresholds
PATCH /api/v1/risk/config update thresholds (hot-reload)
POST /api/v1/risk/emergency-stop {enabled, trigger} → activates/deactivates
GET /api/v1/exchanges list of exchanges with status
GET /api/v1/exchanges/{id}/status single exchange status
POST /api/v1/exchanges/{id}/toggle enable/disable
GET /api/v1/logs?level=&from=&to=&correlation_id=&limit=&offset= paginated logs
GET /api/v1/metrics/summary aggregated analytics snapshot
GET /api/v1/backtest/runs list of historical backtest runs
GET /api/v1/backtest/runs/{id} one backtest report
POST /api/v1/backtest/run trigger a backtest (async job, returns job_id)
GET /api/v1/backtest/jobs/{job_id} job status
WebSocket

Single endpoint: GET /ws/dashboard (upgrade to WebSocket).

Authenticate via Authorization: Bearer <jwt> header or ?token= query param.

Send the message envelope shapes specified in the frontend spec (see Phase B, "WebSocket contract").

Client actions: subscribe, unsubscribe, ping.

Server events: connected, portfolio_update, fill, signal, risk_status, exchange_status, log, ticker, pong, error.

Throttle ticker events to one per symbol per 250ms.

Middleware / cross-cutting

CORSMiddleware with origins from QUANTFLOW_CORS_ORIGINS (comma-separated). No \* in production.

Request ID middleware: generate X-Request-ID, bind to structlog context, echo in response.

Correlation ID middleware: propagate into the EventBus context so every WS event carries it.

Auth middleware: JWT verification on all /api/v1/_ and /ws/_. In APP_ENV=development, allow a dev bypass with a fixed user.

Rate limiting: slowapi or equivalent, keyed by user, on all mutating endpoints (POST/PATCH/DELETE).

Structured error handling: all exceptions return {"error": {"code": "...", "message": "...", "request_id": "..."}}.

Phase B — Frontend: production-ready dashboard
B1. Stack (do not deviate)
Layer Choice
Framework React 18 + TypeScript (strict mode on)
Build Vite 5
Routing React Router v6
UI primitives shadcn/ui (installed via CLI, components committed to repo)
Styling Tailwind CSS 3
Server state TanStack Query v5
Real-time state Zustand
Financial charts TradingView Lightweight Charts
Analytics charts Recharts
Forms React Hook Form + Zod
HTTP fetch wrapped in a typed client (no axios)
Testing Vitest + React Testing Library + MSW for REST, mock-socket for WS
Linting ESLint + eslint-plugin-react-hooks, Prettier
B2. Absolute rule: zero hardcoded values
A CI check (scripts/check-no-hardcoded.sh) must fail the build if any of the following patterns appear in src/ outside of src/config/ and src/test/:

Any literal http://, https://, ws://, wss:// URL.

Any literal localhost, 127.0.0.1, or IP address.

Any literal API route string (e.g., /api/v1/) outside src/config/endpoints.ts.

Any numeric trading constant (0.001, 0.5, 10000, etc.) that is not decorated with an inline comment // non-configurable: <reason>.

Any process.env.X access outside src/config/env.ts.

All configuration flows through one module:

typescript
// src/config/env.ts
import { z } from "zod";

const EnvSchema = z.object({
VITE_API_BASE_URL: z.string().url(),
VITE_WS_URL: z.string().url(),
VITE_APP_ENV: z.enum(["development", "staging", "production"]),
VITE_AUTH_MODE: z.enum(["jwt", "dev-bypass"]).default("jwt"),
VITE_TICKER_THROTTLE_MS: z.coerce.number().int().positive().default(250),
VITE_RECONNECT_BASE_MS: z.coerce.number().int().positive().default(1000),
VITE_RECONNECT_MAX_MS: z.coerce.number().int().positive().default(30000),
VITE_WS_PING_INTERVAL_MS: z.coerce.number().int().positive().default(30000),
VITE_QUERY_STALE_MS: z.coerce.number().int().positive().default(5000),
});

export const env = EnvSchema.parse(import.meta.env);
Endpoints live in src/config/endpoints.ts as a frozen object of template functions. No fetch call may inline a path.

B3. State management — strict separation
Rule 1: Server data never lives in Zustand. Use TanStack Query for anything fetched via REST (portfolio snapshot, trades, orders, signals, strategies, risk config, exchange status, logs, backtest runs).

Rule 2: Real-time data never lives in TanStack Query. Use Zustand stores for WebSocket-pushed state.

Rule 3: One WebSocket connection per tab. A single WebSocketProvider (React context) owns the connection. Zustand stores receive updates via subscription from the provider — stores never open sockets themselves.

Store layout:

text
src/state/
├── ws/
│ ├── WebSocketProvider.tsx # connection lifecycle, reconnect, ping/pong
│ ├── useWebSocket.ts # hook to send actions, read status
│ └── wsRouter.ts # dispatches inbound messages to stores
├── portfolioStore.ts # { snapshot, history, lastUpdate }
├── riskStore.ts # { status, config, emergencyStop }
├── exchangeStore.ts # { exchanges: Record<id, status> }
├── logStore.ts # bounded ring buffer (max 1000)
├── tickerStore.ts # { bySymbol: Record<canonical, Ticker> }
└── uiStore.ts # { theme, sidebarOpen, activeFilters }
Every store:

Is created with create<State>()(...) and typed.

Exposes selectors (usePortfolioStore(s => s.snapshot)), not the whole store.

Uses subscribeWithSelector middleware.

Never holds React refs, DOM nodes, or functions.

Rule 4: Query invalidation on WS events. When the WS router receives fill or portfolio_update, it calls queryClient.invalidateQueries({ queryKey: ["trades"] }) and ["portfolio"] — but does not write into the query cache directly. The live numbers come from Zustand; the historical tables refresh via Query.

Rule 5: No useEffect for data fetching. All REST reads are useQuery; all REST writes are useMutation. Only the WS provider and layout effects use useEffect.

B4. WebSocket contract (frontend expects exactly this)
Envelope: { event: string; timestamp: string; data: T }.

Events: connected, portfolio_update, fill, signal, risk_status, exchange_status, log, ticker, pong, error — with the exact payload shapes defined in the backend spec.

The wsRouter.ts is a typed switch over event. It is the only file that knows about WS message shapes. Everything else consumes the stores.

B5. Pages
Build these routes under src/pages/:

/ → Overview: equity curve (Recharts), current PnL, exposure, drawdown, win rate, top positions, exchange status pills, risk status pill.

/portfolio → positions table (sortable, filterable), cash/equity breakdown, realized vs unrealized PnL chart, equity curve with drawdown overlay.

/trades → paginated fills table with filters (symbol, strategy, exchange, date range, side). CSV export. Row click opens detail drawer.

/orders → paginated orders table with status badges, lifecycle timeline for a selected order.

/signals → paginated signals with approve/reject reason codes, filterable.

/strategies → plugin cards: name, version, active toggle, live metrics, config editor (React Hook Form + Zod), per-strategy equity curve.

/risk → current risk status, thresholds editor, emergency stop button (with confirm dialog requiring typing EMERGENCY STOP), circuit breaker state, daily PnL vs limit gauge.

/exchanges → per-exchange cards: connection status, latency, subscribed symbols, reconnect count, enable/disable toggle.

/logs → live tail with level filter, correlation_id search, pause/play, download.

/backtest → backtest list, run form (strategy, params, date range), job progress, report viewer (Sharpe, Sortino, drawdown, WFE, tier results).

B6. Real-time chart behavior
Equity curve: append a new point on each portfolio_update (throttled to 1/s). Use Recharts <LineChart> with isAnimationActive={false} for smoothness.

Ticker display: subscribe to ticker events only for symbols visible on the current page. Send {action: "subscribe", symbols: [...]} on mount, unsubscribe on unmount. The provider tracks refcounts.

Order book (if displayed): use TradingView Lightweight Charts with 20 levels per side, updated on orderbook events. Recreate the book only on snapshot, not on every diff.

B7. Execution correctness (production-critical)
Idempotency: every mutating mutation sends an Idempotency-Key header (UUID v4 generated client-side, cached for the request). The backend must honor it.

Optimistic updates: only for strategy.toggle and risk.config.patch. All others are pessimistic (wait for server).

Error handling: every mutation has onError that surfaces a toast with error.message and request_id. Never swallow errors.

Reconnect: exponential backoff with jitter, capped at VITE_RECONNECT_MAX_MS. On reconnect, refetch all active queries (queryClient.invalidateQueries()), then re-subscribe to tickers.

Stale WS data guard: if lastMessageAt is older than 10s, show a "Connection stale" banner. If older than 30s, show "Disconnected — reconnecting".

No memory leaks: every subscription (WS, Query, store) must be cleaned up on unmount. Use AbortController for in-flight fetches.

Type safety: no any, no as casts except for unknown narrowing. tsconfig has strict: true, noUncheckedIndexedAccess: true, exactOptionalPropertyTypes: true.

B8. Auth
JWT stored in httpOnly cookie if backend supports it; otherwise in memory only (never localStorage).

On app load, call GET /api/v1/auth/me to validate session. If 401, redirect to login.

WS connection passes the token via ?token= query param (browser WS API does not support headers). Backend must accept both.

Logout clears cookie/in-memory token and closes the WS connection.

B9. Build & deploy
npm run build produces dist/ with hashed assets.

Dockerfile.frontend:

Stage 1: node:20-alpine builds the app with VITE\_\* args.

Stage 2: nginx:1.27-alpine serves dist/ with:

try_files $uri /index.html for SPA routing.

/api/ and /ws/ proxied to the backend service (upstream URL from env at container start via envsubst template).

Security headers: X-Content-Type-Options, X-Frame-Options: DENY, Content-Security-Policy with a strict policy allowing only the configured API/WS origins.

Gzip/Brotli for text assets.

Local: extend docker-compose.yml with a frontend service that depends on app being healthy.

Production: docker-compose.prod.yml overrides:

No source mounts.

restart: always.

Resource limits (deploy.resources.limits).

Traefik or Caddy as reverse proxy with TLS (Let's Encrypt).

Postgres and Redis on persistent named volumes with backups (pg_dump cron, Redis AOF).

Logging driver: json-file with rotation, or journald.

Prometheus + Grafana + Alertmanager services, wired to the metrics endpoint and the alert rules from Sprint 15.

B10. Testing
Unit: stores, selectors, wsRouter, Zod schemas, hooks (useWebSocket, useTicker).

Integration: each page rendered with MSW intercepting REST and mock-socket simulating WS events. Assert store → UI propagation.

E2E: Playwright suite covering (1) login, (2) view portfolio, (3) trigger emergency stop with confirm dialog, (4) watch a fill arrive via WS and appear in the trades table, (5) toggle a strategy and see it persist after reload.

Coverage gate: 80% lines, 70% branches. CI fails below.

B11. CI/CD
GitHub Actions workflow .github/workflows/ci.yml:

backend: ruff, mypy, pytest --cov on Python 3.12, with Postgres + Redis services.

frontend: tsc --noEmit, eslint, vitest --coverage, npm run build, scripts/check-no-hardcoded.sh.

e2e: Playwright against docker compose up stack.

docker: build both images, push to registry on tag.

B12. Production release checklist
Before docker compose -f docker-compose.prod.yml up -d:

□ features.enable_live_trading: false in config/quantflow.yaml unless a valid attestation.json exists (Sprint 15).
□ .env populated with production secrets (Vault reference paths, not literal values).
□ QUANTFLOW_CORS_ORIGINS set to the exact frontend origin(s).
□ VITE_API_BASE_URL and VITE_WS_URL point to the production domain (HTTPS/WSS).
□ TLS certificates provisioned and auto-renewing.
□ Postgres backups scheduled and restore tested.
□ Prometheus targets scraping, Alertmanager routing verified with a synthetic alert.
□ Grafana dashboards imported.
□ scripts/check-no-hardcoded.sh passes.
□ All tests green in CI on the release commit.
□ Go-live attestation signed (if enabling live mode).
□ Rollback plan documented: previous image tag, DB migration downgrade path, kill switch (emergency stop).
Deliverables
Backend: fully implemented, all tests passing, running under docker compose up, exposing the REST + WS surface in A3.

Frontend: fully implemented per B1–B11, zero hardcoded values, all tests passing, building to a production bundle.

docker-compose.yml (dev) and docker-compose.prod.yml (prod) with the frontend service added.

Dockerfile.frontend and nginx.conf.template.

DECISIONS.md: every non-obvious choice, with the reason and the alternative rejected.

RUNBOOK.md: how to deploy, roll back, rotate secrets, respond to each Prometheus alert.

README.md: local dev, running tests, deploying, going live.

scripts/check-no-hardcoded.sh: the CI gate.

Definition of done
docker compose up brings up Postgres, Redis, backend, and frontend; the dashboard loads at http://localhost:3000 and shows live portfolio/PnL/positions updating via WebSocket.

docker compose --profile test run --rm test passes all backend tests against real Postgres and Redis.

npm run test and npm run build pass in the frontend directory.

scripts/check-no-hardcoded.sh exits 0.

CI is green on the release commit.

docker compose -f docker-compose.prod.yml up -d deploys successfully to the target host, healthchecks pass, and the live dashboard is reachable over HTTPS.

No file in the repository contains a hardcoded API URL, WS URL, credential, or trading constant.

Work through Phase A end-to-end before starting Phase B. Commit in logical chunks with descriptive messages. Do not stop for confirmation — make the best engineering decision and document it.

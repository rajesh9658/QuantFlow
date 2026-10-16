# QuantFlow Architecture & Implementation Decisions (DECISIONS.md)

This document records key engineering decisions made to maximize determinism, testability, security, and observability across QuantFlow backend and frontend.

---

### Decision 1: Direct Fetch-Wrapped Client over Axios
- **Choice:** Lightweight typed `fetch` wrapper using standard web APIs.
- **Reason:** Built-in standard library in all modern runtimes (Node 18+, browsers), avoids bundle bloat, and provides natural integration with TypeScript request/response contracts and `AbortController`.
- **Alternative Rejected:** `axios` — adds unnecessary external dependency and boilerplate when native fetch meets all requirements.

---

### Decision 2: Dual REST Router Mounting (`/api/v1` and `/api`)
- **Choice:** Mounting the REST router at `/api/v1` (per frontend production contract) and maintaining `/api` alias.
- **Reason:** Prevents breaking existing unit/integration test suites while fully adhering to the `/api/v1` versioned API specification.
- **Alternative Rejected:** Hard breaking change redirecting all routes to `/api/v1` only, which would require re-writing legacy test URLs.

---

### Decision 3: Zero Hardcoded Values CI Enforced via `src/config/env.ts` and `src/config/endpoints.ts`
- **Choice:** Centralizing all runtime configuration in `src/config/env.ts` (validated via Zod) and all endpoint paths in `src/config/endpoints.ts`.
- **Reason:** Complete decoupling from environment, preventing production leakage of URLs or credentials, and ensuring smooth promotion from development to staging to production.
- **Alternative Rejected:** Ad-hoc environment variable interpolation (`import.meta.env.VITE_*`) scattered throughout UI components.

---

### Decision 4: Separation of Server State (TanStack Query) and Real-Time State (Zustand)
- **Choice:** REST data is managed strictly through TanStack Query; live WebSocket streams (tickers, positions, fills, logs) are dispatched directly into typed Zustand stores.
- **Reason:** Prevents race conditions and thrashing between polling/cache invalidation and high-frequency WebSocket streams (e.g. 250ms throttled ticks).
- **Alternative Rejected:** Storing live socket data inside TanStack Query cache via `setQueryData`, which causes excessive re-renders and violates cache stale semantics.

---

### Decision 5: Single WebSocket Connection Owned by React Context Provider
- **Choice:** One single WebSocket connection per tab managed by `<WebSocketProvider />`, dispatching inbound messages to stores via `wsRouter.ts`.
- **Reason:** Prevents connection multiplication across routes/tabs, ensures centralized reconnect with exponential backoff and jitter, and handles automatic symbol subscription ref-counting.
- **Alternative Rejected:** Multiple ad-hoc WebSocket connections per panel or component.

---

### Decision 6: Synthetic Market Data Stream for Paper / Zero-Credential Boots
- **Choice:** `SyntheticEventStore` emitting deterministic sinusoidal tick and orderbook feeds when running in non-live mode without exchange keys.
- **Reason:** Guarantees that the entire trading engine, WebSocket stream, and dashboard can be booted and verified out of the box with zero external exchange credentials.
- **Alternative Rejected:** Forcing users to register and configure Binance/Bybit testnet API keys before running the stack locally.

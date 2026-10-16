/**
 * Centralized frozen endpoints catalog.
 * No API paths may be inlined outside this file.
 */

function buildQuery(params?: Record<string, string | number | boolean | null | undefined>): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const str = search.toString();
  return str ? `?${str}` : "";
}

export const endpoints = Object.freeze({
  auth: {
    me: () => "/api/v1/auth/me",
  },
  portfolio: {
    snapshot: () => "/api/v1/portfolio",
    history: (from?: string, to?: string, interval?: string) =>
      `/api/v1/portfolio/history${buildQuery({ from, to, interval })}`,
  },
  trades: (params?: {
    from?: string;
    to?: string;
    strategy?: string;
    symbol?: string;
    exchange_id?: string;
    limit?: number;
    offset?: number;
  }) => `/api/v1/trades${buildQuery(params)}`,
  orders: (params?: {
    status?: string;
    strategy?: string;
    exchange_id?: string;
    limit?: number;
    offset?: number;
  }) => `/api/v1/orders${buildQuery(params)}`,
  signals: (params?: {
    from?: string;
    to?: string;
    strategy?: string;
    exchange_id?: string;
    limit?: number;
    offset?: number;
  }) => `/api/v1/signals${buildQuery(params)}`,
  strategies: {
    list: () => "/api/v1/strategies",
    metrics: (name: string) => `/api/v1/strategies/${encodeURIComponent(name)}/metrics`,
    config: (name: string) => `/api/v1/strategies/${encodeURIComponent(name)}/config`,
    toggle: (name: string) => `/api/v1/strategies/${encodeURIComponent(name)}/toggle`,
  },
  risk: {
    status: () => "/api/v1/risk/status",
    config: () => "/api/v1/risk/config",
    emergencyStop: () => "/api/v1/risk/emergency-stop",
  },
  exchanges: {
    list: () => "/api/v1/exchanges",
    status: (id: string) => `/api/v1/exchanges/${encodeURIComponent(id)}/status`,
    toggle: (id: string) => `/api/v1/exchanges/${encodeURIComponent(id)}/toggle`,
  },
  logs: (params?: {
    level?: string;
    from?: string;
    to?: string;
    correlation_id?: string;
    limit?: number;
    offset?: number;
  }) => `/api/v1/logs${buildQuery(params)}`,
  metrics: {
    summary: () => "/api/v1/metrics/summary",
  },
  backtest: {
    runs: () => "/api/v1/backtest/runs",
    run: (id: string) => `/api/v1/backtest/runs/${encodeURIComponent(id)}`,
    trigger: () => "/api/v1/backtest/run",
    job: (jobId: string) => `/api/v1/backtest/jobs/${encodeURIComponent(jobId)}`,
  },
});

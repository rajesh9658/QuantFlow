export interface Position {
  symbol: string;
  quantity: number;
  avg_entry_price: number;
  unrealized_pnl: number;
}

export interface PortfolioSnapshot {
  cash: number;
  total_equity: number;
  total_exposure: number;
  realized_pnl: number;
  unrealized_pnl: number;
  positions: Position[];
}

export interface EquityCurvePoint {
  timestamp: string;
  equity: number;
  drawdown: number;
  exposure: number;
}

export interface TradeExecution {
  fill_id: string;
  order_id: string;
  symbol: string;
  side: 'buy' | 'sell' | string;
  price: number;
  quantity: number;
  commission: number;
  timestamp_exchange: string;
  realized_pnl: number;
  strategy?: string;
}

export interface RiskStatus {
  emergency_stop: boolean;
  daily_pnl: number;
  daily_loss_limit: number;
  current_exposure: number;
  max_exposure: number;
  circuit_breaker_active: boolean;
}

export interface RiskConfig {
  max_position_qty: number;
  max_daily_loss: number;
  max_total_exposure: number;
  allowed_symbols: string[];
  trading_schedule: {
    start_utc: string;
    end_utc: string;
    timezone: string;
  };
}

export interface StrategyMetrics {
  win_rate: number;
  sharpe: number;
  total_trades: number;
}

export interface StrategySummary {
  name: string;
  version: string;
  active: boolean;
  config: Record<string, unknown>;
  metrics: StrategyMetrics;
}

export interface DetailedStrategyMetrics {
  win_rate: number;
  sharpe: number;
  sortino: number;
  profit_factor: number;
  max_drawdown: number;
  equity_curve: Array<[string, number]>;
}

export interface ExchangeStatus {
  name: string;
  connected: boolean;
  latency_ms: number;
  last_heartbeat: string;
  symbols_subscribed: string[];
}

export interface LogEntry {
  correlation_id: string;
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | string;
  logger_name: string;
  message: string;
  metadata: Record<string, unknown>;
  received_at: string;
}

export interface AnalyticsSnapshot {
  sharpe: number;
  sortino: number;
  win_rate: number;
  profit_factor: number;
  avg_trade: number;
  avg_slippage: number;
  avg_latency: number;
  max_drawdown: number;
}

export interface WSMessage<T = unknown> {
  event: string;
  timestamp: string;
  data: T;
}

export interface WSTickerData {
  symbol: string;
  bid: number;
  ask: number;
  last: number;
}

export interface WSPongData {
  server_time: string;
}

export interface WSErrorData {
  code: string;
  message: string;
}

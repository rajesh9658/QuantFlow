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
  side: "buy" | "sell" | string;
  price: number;
  quantity: number;
  commission: number;
  timestamp_exchange?: string | null;
  realized_pnl: number;
  strategy?: string;
}

export interface OrderItem {
  order_id: string;
  exchange_order_id?: string;
  symbol: string;
  side: "buy" | "sell" | string;
  type: string;
  quantity: number;
  filled_quantity: number;
  avg_price: number;
  status: "NEW" | "PARTIALLY_FILLED" | "FILLED" | "CANCELLED" | "REJECTED" | string;
  created_at: string;
}

export interface SignalItem {
  event_id: string;
  strategy_name: string;
  symbol: string;
  direction: "BUY" | "SELL" | "HOLD" | string;
  confidence: number;
  timestamp_exchange?: string | null;
  rejection_reason?: string | null;
}

export interface RiskStatus {
  emergency_stop: boolean;
  circuit_breaker_active: boolean;
  daily_pnl: number;
  daily_loss_limit: number;
  current_exposure: number;
  max_exposure: number;
}

export interface RiskConfig {
  max_position_qty: number;
  max_daily_loss: number;
  max_total_exposure: number;
  allowed_symbols: string[];
  trading_schedule: string;
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
  equity_curve: EquityCurvePoint[];
}

export interface ExchangeStatus {
  name: string;
  connected: boolean;
  latency_ms: number;
  last_heartbeat?: string | null;
  symbols_subscribed: string[];
}

export interface ExchangeItem {
  id: string;
  name: string;
  type: string;
  enabled: boolean;
  connected: boolean;
  latency_ms: number;
  last_heartbeat?: string | null;
  symbols_subscribed: string[];
}

export interface LogEntry {
  correlation_id: string;
  level: "DEBUG" | "INFO" | "WARNING" | "ERROR" | string;
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

export interface BacktestRunItem {
  id: string;
  strategy_name: string;
  start_date: string;
  end_date: string;
  status: "queued" | "running" | "completed" | "failed" | string;
  created_at: string;
  sharpe: number;
  win_rate: number;
  total_return: number;
  max_drawdown: number;
}

export interface BacktestRunDetail {
  id: string;
  strategy_name: string;
  params: Record<string, unknown>;
  start_date: string;
  end_date: string;
  status: string;
  created_at: string;
  metrics: Record<string, unknown>;
  equity_curve: EquityCurvePoint[];
  trades: TradeExecution[];
}

export interface BacktestJobStatus {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed" | string;
  progress: number;
  run_id?: string | null;
  error?: string | null;
}

export interface UserMe {
  user_id: string;
  role: string;
  email: string;
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

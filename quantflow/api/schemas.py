"""Pydantic request and response schemas for QuantFlow REST and WebSocket APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ── Portfolio Schemas ──────────────────────────────────────────────


class PositionItem(BaseModel):
    """Position representation in portfolio snapshot."""

    symbol: str
    quantity: float
    avg_entry_price: float
    unrealized_pnl: float = 0.0


class PortfolioSnapshotResponse(BaseModel):
    """Current portfolio state snapshot."""

    cash: float
    total_equity: float
    total_exposure: float
    realized_pnl: float
    unrealized_pnl: float
    positions: list[PositionItem] = Field(default_factory=list)


class EquityCurvePoint(BaseModel):
    """Historical equity curve sample point."""

    timestamp: str | datetime
    equity: float
    drawdown: float
    exposure: float = 0.0


# ── Trading & Execution Schemas ─────────────────────────────────────


class TradeExecutionItem(BaseModel):
    """Trade fill representation."""

    fill_id: str
    order_id: str
    symbol: str
    side: str
    price: float
    quantity: float
    commission: float = 0.0
    timestamp_exchange: str | datetime | None = None
    realized_pnl: float = 0.0


class OrderItem(BaseModel):
    """Order representation."""

    order_id: str
    exchange_order_id: str = ""
    symbol: str
    side: str
    type: str
    quantity: float
    filled_quantity: float = 0.0
    avg_price: float = 0.0
    status: str = "NEW"
    created_at: str | datetime


class SignalItem(BaseModel):
    """Strategy signal representation."""

    event_id: str
    strategy_name: str
    symbol: str
    direction: str
    confidence: float = 1.0
    timestamp_exchange: str | datetime | None = None


# ── Strategy Schemas ───────────────────────────────────────────────


class StrategyMetricsSummary(BaseModel):
    """Summary metrics embedded in strategy list."""

    win_rate: float = 0.0
    sharpe: float = 0.0
    total_trades: int = 0


class StrategySummaryItem(BaseModel):
    """Loaded strategy plugin item."""

    name: str
    version: str = "1.0.0"
    active: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    metrics: StrategyMetricsSummary = Field(default_factory=StrategyMetricsSummary)


class DetailedStrategyMetricsResponse(BaseModel):
    """Detailed strategy performance report."""

    win_rate: float
    sharpe: float
    sortino: float
    profit_factor: float
    max_drawdown: float
    equity_curve: list[EquityCurvePoint] = Field(default_factory=list)


class StrategyToggleRequest(BaseModel):
    """Request payload to toggle a strategy's active status."""

    active: bool


class StrategyToggleResponse(BaseModel):
    """Response after toggling a strategy."""

    name: str
    active: bool


# ── Risk Schemas ───────────────────────────────────────────────────


class RiskStatusResponse(BaseModel):
    """Current risk and limit state."""

    emergency_stop: bool
    circuit_breaker_active: bool
    daily_pnl: float
    daily_loss_limit: float
    current_exposure: float
    max_exposure: float


class RiskConfigResponse(BaseModel):
    """Configured risk policy thresholds."""

    max_position_qty: float = 5.0
    max_daily_loss: float = 1000.0
    max_total_exposure: float = 100000.0
    allowed_symbols: list[str] = Field(
        default_factory=lambda: ["BTC/USDT", "ETH/USDT"]
    )
    trading_schedule: str = "00:00-23:59"


class EmergencyStopRequest(BaseModel):
    """Request payload to trigger or release emergency stop."""

    enabled: bool
    trigger: str = "manual"


class EmergencyStopResponse(BaseModel):
    """Response payload following emergency stop toggle."""

    status: str  # "activated" | "deactivated"


# ── Exchange & Monitoring Schemas ──────────────────────────────────


class ExchangeStatusItem(BaseModel):
    """Exchange adapter connection health."""

    name: str
    connected: bool
    latency_ms: float = 0.0
    last_heartbeat: str | datetime | None = None
    symbols_subscribed: list[str] = Field(default_factory=list)


class LogEntryItem(BaseModel):
    """Structured log record."""

    correlation_id: str
    level: str
    logger_name: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    received_at: str | datetime


class AnalyticsMetricsSnapshot(BaseModel):
    """System-wide performance analytics snapshot."""

    sharpe: float
    sortino: float
    win_rate: float
    profit_factor: float
    avg_trade: float
    avg_slippage: float
    avg_latency: float
    max_drawdown: float


# ── WebSocket Envelopes ───────────────────────────────────────────


class WSMessageEnvelope(BaseModel, Generic[T]):  # noqa: UP046
    """Standard envelope for all server -> client WebSocket events."""

    event: str
    timestamp: str
    data: T


class WSClientAction(BaseModel):
    """Client -> Server action envelope."""

    action: str
    symbols: list[str] = Field(default_factory=list)

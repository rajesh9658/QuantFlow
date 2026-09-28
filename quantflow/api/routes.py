"""FastAPI REST routes for QuantFlow trading platform."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from quantflow.api.dependencies import APIState, get_api_state
from quantflow.api.schemas import (
    AnalyticsMetricsSnapshot,
    DetailedStrategyMetricsResponse,
    EmergencyStopRequest,
    EmergencyStopResponse,
    EquityCurvePoint,
    ExchangeStatusItem,
    LogEntryItem,
    OrderItem,
    PortfolioSnapshotResponse,
    RiskConfigResponse,
    RiskStatusResponse,
    SignalItem,
    StrategySummaryItem,
    StrategyToggleRequest,
    StrategyToggleResponse,
    TradeExecutionItem,
)

router = APIRouter(prefix="/api", tags=["QuantFlow API"])


# ── Portfolio Endpoints ────────────────────────────────────────────


@router.get(
    "/portfolio",
    response_model=PortfolioSnapshotResponse,
    summary="Current portfolio snapshot",
)
async def get_portfolio(
    state: Annotated[APIState, Depends(get_api_state)],
) -> PortfolioSnapshotResponse:
    """Retrieve the latest portfolio equity, cash, exposure, PnL, and open positions."""
    data = state.get_portfolio_snapshot()
    return PortfolioSnapshotResponse(**data)


@router.get(
    "/portfolio/history",
    response_model=list[EquityCurvePoint],
    summary="Equity curve time series",
)
async def get_portfolio_history(
    state: Annotated[APIState, Depends(get_api_state)],
    from_ts: str | None = Query(None, alias="from"),
    to_ts: str | None = Query(None, alias="to"),
    interval: str | None = Query(None),
) -> list[EquityCurvePoint]:
    """Retrieve historical equity snapshots and drawdown series."""
    points = state.get_portfolio_history(
        from_ts=from_ts, to_ts=to_ts, interval=interval
    )
    return [EquityCurvePoint(**p) for p in points]


# ── Execution, Order, and Signal Endpoints ─────────────────────────


@router.get(
    "/trades",
    response_model=list[TradeExecutionItem],
    summary="Execution history",
)
async def get_trades(
    state: Annotated[APIState, Depends(get_api_state)],
    from_ts: str | None = Query(None, alias="from"),
    to_ts: str | None = Query(None, alias="to"),
    strategy: str | None = Query(None),
    symbol: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[TradeExecutionItem]:
    """Retrieve paginated trade fills and executions."""
    trades = state.get_trades(
        from_ts=from_ts,
        to_ts=to_ts,
        strategy=strategy,
        symbol=symbol,
        limit=limit,
        offset=offset,
    )
    return [TradeExecutionItem(**t) for t in trades]


@router.get(
    "/orders",
    response_model=list[OrderItem],
    summary="Order history",
)
async def get_orders(
    state: Annotated[APIState, Depends(get_api_state)],
    status_filter: str | None = Query(None, alias="status"),
    strategy: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[OrderItem]:
    """Retrieve order placement and execution status history."""
    orders = state.get_orders(
        status=status_filter,
        strategy=strategy,
        limit=limit,
        offset=offset,
    )
    return [OrderItem(**o) for o in orders]


@router.get(
    "/signals",
    response_model=list[SignalItem],
    summary="Signal history",
)
async def get_signals(
    state: Annotated[APIState, Depends(get_api_state)],
    from_ts: str | None = Query(None, alias="from"),
    to_ts: str | None = Query(None, alias="to"),
    strategy: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[SignalItem]:
    """Retrieve generated trading strategy signals."""
    sigs = state.get_signals(
        from_ts=from_ts,
        to_ts=to_ts,
        strategy=strategy,
        limit=limit,
        offset=offset,
    )
    return [SignalItem(**s) for s in sigs]


# ── Strategy Endpoints ─────────────────────────────────────────────


@router.get(
    "/strategies",
    response_model=list[StrategySummaryItem],
    summary="Loaded strategy plugins",
)
async def get_strategies(
    state: Annotated[APIState, Depends(get_api_state)],
) -> list[StrategySummaryItem]:
    """List loaded strategy plugins, active states, and summary metrics."""
    strategies = state.get_strategies()
    return [StrategySummaryItem(**s) for s in strategies]


@router.get(
    "/strategies/{name}/metrics",
    response_model=DetailedStrategyMetricsResponse,
    summary="Detailed strategy performance",
)
async def get_strategy_metrics(
    name: str,
    state: Annotated[APIState, Depends(get_api_state)],
) -> DetailedStrategyMetricsResponse:
    """Retrieve in-depth performance statistics and equity curve."""
    metrics = state.get_strategy_metrics(name)
    return DetailedStrategyMetricsResponse(**metrics)


@router.post(
    "/strategies/{name}/toggle",
    response_model=StrategyToggleResponse,
    summary="Enable/disable strategy",
)
async def toggle_strategy(
    name: str,
    body: StrategyToggleRequest,
    state: Annotated[APIState, Depends(get_api_state)],
) -> StrategyToggleResponse:
    """Toggle strategy active state."""
    strat_name, active = state.toggle_strategy(name, body.active)
    return StrategyToggleResponse(name=strat_name, active=active)


# ── Risk Management Endpoints ──────────────────────────────────────


@router.get(
    "/risk/status",
    response_model=RiskStatusResponse,
    summary="Current risk state",
)
async def get_risk_status(
    state: Annotated[APIState, Depends(get_api_state)],
) -> RiskStatusResponse:
    """Retrieve real-time risk checks and circuit breaker status."""
    status_data = state.get_risk_status()
    return RiskStatusResponse(**status_data)


@router.get(
    "/risk/config",
    response_model=RiskConfigResponse,
    summary="Risk thresholds (for display)",
)
async def get_risk_config(
    state: Annotated[APIState, Depends(get_api_state)],
) -> RiskConfigResponse:
    """Retrieve configured risk limits and allowed trading parameters."""
    cfg = state.get_risk_config()
    return RiskConfigResponse(**cfg)


@router.post(
    "/risk/emergency-stop",
    response_model=EmergencyStopResponse,
    summary="Trigger emergency stop",
)
async def trigger_emergency_stop(
    body: EmergencyStopRequest,
    state: Annotated[APIState, Depends(get_api_state)],
) -> EmergencyStopResponse:
    """Engage or disengage manual emergency stop."""
    status_str = await state.set_emergency_stop(body.enabled, body.trigger)
    return EmergencyStopResponse(status=status_str)


# ── Exchange & Operational Monitoring Endpoints ────────────────────


@router.get(
    "/exchanges/status",
    response_model=list[ExchangeStatusItem],
    summary="Exchange connection health",
)
async def get_exchanges_status(
    state: Annotated[APIState, Depends(get_api_state)],
) -> list[ExchangeStatusItem]:
    """Retrieve connection health and latency for exchange adapters."""
    items = state.get_exchanges_status()
    return [ExchangeStatusItem(**item) for item in items]


@router.get(
    "/logs",
    response_model=list[LogEntryItem],
    summary="Structured log query",
)
async def get_logs(
    state: Annotated[APIState, Depends(get_api_state)],
    level: str | None = Query(None),
    from_ts: str | None = Query(None, alias="from"),
    to_ts: str | None = Query(None, alias="to"),
    correlation_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[LogEntryItem]:
    """Query structured system and component logs."""
    logs = state.get_logs(
        level=level,
        from_ts=from_ts,
        to_ts=to_ts,
        correlation_id=correlation_id,
        limit=limit,
        offset=offset,
    )
    return [LogEntryItem(**entry) for entry in logs]


@router.get(
    "/metrics",
    response_model=AnalyticsMetricsSnapshot,
    summary="Current analytics snapshot",
)
async def get_metrics(
    state: Annotated[APIState, Depends(get_api_state)],
) -> AnalyticsMetricsSnapshot:
    """Retrieve overall system analytics snapshot (Sharpe, Sortino, Win Rate, etc.)."""
    metrics = state.get_analytics_metrics()
    return AnalyticsMetricsSnapshot(**metrics)

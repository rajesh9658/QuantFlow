"""FastAPI REST routes for QuantFlow trading platform."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from quantflow.api.dependencies import APIState, get_api_state, verify_api_key
from quantflow.api.schemas import (
    AnalyticsMetricsSnapshot,
    BacktestJobStatusResponse,
    BacktestRunDetailResponse,
    BacktestRunItem,
    BacktestRunRequest,
    BacktestRunResponse,
    DetailedStrategyMetricsResponse,
    EmergencyStopRequest,
    EmergencyStopResponse,
    EquityCurvePoint,
    ExchangeItem,
    ExchangeStatusItem,
    ExchangeToggleRequest,
    ExchangeToggleResponse,
    LogEntryItem,
    OrderItem,
    PortfolioSnapshotResponse,
    RiskConfigResponse,
    RiskConfigUpdateRequest,
    RiskStatusResponse,
    SignalItem,
    StrategyConfigResponse,
    StrategyConfigUpdateRequest,
    StrategySummaryItem,
    StrategyToggleRequest,
    StrategyToggleResponse,
    TradeExecutionItem,
    UserMeResponse,
)

router = APIRouter(tags=["QuantFlow API"])


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
    dependencies=[Depends(verify_api_key)],
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
    dependencies=[Depends(verify_api_key)],
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


@router.get(
    "/metrics/summary",
    response_model=AnalyticsMetricsSnapshot,
    summary="Aggregated analytics summary",
)
async def get_metrics_summary(
    state: Annotated[APIState, Depends(get_api_state)],
) -> AnalyticsMetricsSnapshot:
    """Retrieve overall system analytics snapshot."""
    metrics = state.get_analytics_metrics()
    return AnalyticsMetricsSnapshot(**metrics)


@router.get(
    "/strategies/{name}/config",
    response_model=StrategyConfigResponse,
    summary="Get strategy configuration",
)
async def get_strategy_config(
    name: str,
    state: Annotated[APIState, Depends(get_api_state)],
) -> StrategyConfigResponse:
    """Retrieve current strategy parameters."""
    cfg = state.get_strategy_config(name)
    return StrategyConfigResponse(name=name, config=cfg)


@router.patch(
    "/strategies/{name}/config",
    response_model=StrategyConfigResponse,
    summary="Update strategy configuration",
    dependencies=[Depends(verify_api_key)],
)
async def update_strategy_config(
    name: str,
    body: StrategyConfigUpdateRequest,
    state: Annotated[APIState, Depends(get_api_state)],
) -> StrategyConfigResponse:
    """Hot-reload strategy parameter configuration."""
    cfg = state.update_strategy_config(name, body.config)
    return StrategyConfigResponse(name=name, config=cfg)


@router.patch(
    "/risk/config",
    response_model=RiskConfigResponse,
    summary="Update risk configuration",
    dependencies=[Depends(verify_api_key)],
)
async def update_risk_config(
    body: RiskConfigUpdateRequest,
    state: Annotated[APIState, Depends(get_api_state)],
) -> RiskConfigResponse:
    """Update risk limits and thresholds."""
    updates = body.model_dump(exclude_unset=True)
    cfg = state.update_risk_config(updates)
    return RiskConfigResponse(**cfg)


@router.get(
    "/exchanges",
    response_model=list[ExchangeItem],
    summary="List all exchange adapters",
)
async def get_exchanges(
    state: Annotated[APIState, Depends(get_api_state)],
) -> list[ExchangeItem]:
    """Retrieve detailed state and configuration for all exchange adapters."""
    items = state.get_exchanges()
    return [ExchangeItem(**item) for item in items]


@router.get(
    "/exchanges/{id}/status",
    response_model=ExchangeItem,
    summary="Get single exchange adapter status",
)
async def get_exchange_status_by_id(
    id: str,
    state: Annotated[APIState, Depends(get_api_state)],
) -> ExchangeItem:
    """Retrieve status for a specific exchange adapter."""
    item = state.get_exchange_status_by_id(id)
    if not item:
        raise HTTPException(
            status_code=404, detail=f"Exchange '{id}' not found"
        )
    return ExchangeItem(**item)


@router.post(
    "/exchanges/{id}/toggle",
    response_model=ExchangeToggleResponse,
    summary="Enable or disable an exchange adapter",
    dependencies=[Depends(verify_api_key)],
)
async def toggle_exchange(
    id: str,
    body: ExchangeToggleRequest,
    state: Annotated[APIState, Depends(get_api_state)],
) -> ExchangeToggleResponse:
    """Toggle connection and order routing for a specific exchange adapter."""
    res = state.toggle_exchange(id, body.enabled)
    return ExchangeToggleResponse(id=id, enabled=res["enabled"])


@router.get(
    "/backtest/runs",
    response_model=list[BacktestRunItem],
    summary="List historical backtest runs",
)
async def get_backtest_runs(
    state: Annotated[APIState, Depends(get_api_state)],
) -> list[BacktestRunItem]:
    """Retrieve list of historical backtest runs with performance summaries."""
    runs = state.get_backtest_runs()
    return [BacktestRunItem(**r) for r in runs]


@router.get(
    "/backtest/runs/{id}",
    response_model=BacktestRunDetailResponse,
    summary="Get detailed backtest run report",
)
async def get_backtest_run_detail(
    id: str,
    state: Annotated[APIState, Depends(get_api_state)],
) -> BacktestRunDetailResponse:
    """Retrieve in-depth backtest report including equity curve and trade logs."""
    run = state.get_backtest_run(id)
    if not run:
        raise HTTPException(
            status_code=404, detail=f"Backtest run '{id}' not found"
        )
    return BacktestRunDetailResponse(**run)


@router.post(
    "/backtest/run",
    response_model=BacktestRunResponse,
    summary="Trigger a backtest execution",
    dependencies=[Depends(verify_api_key)],
)
async def trigger_backtest_run(
    body: BacktestRunRequest,
    state: Annotated[APIState, Depends(get_api_state)],
) -> BacktestRunResponse:
    """Trigger an asynchronous backtest simulation job."""
    job_id = state.submit_backtest_job(body.model_dump())
    return BacktestRunResponse(job_id=job_id, status="queued")


@router.get(
    "/backtest/jobs/{job_id}",
    response_model=BacktestJobStatusResponse,
    summary="Get backtest job status",
)
async def get_backtest_job_status(
    job_id: str,
    state: Annotated[APIState, Depends(get_api_state)],
) -> BacktestJobStatusResponse:
    """Inquire about the execution status of an asynchronous backtest job."""
    job = state.get_backtest_job(job_id)
    if not job:
        raise HTTPException(
            status_code=404, detail=f"Backtest job '{job_id}' not found"
        )
    return BacktestJobStatusResponse(**job)


@router.get(
    "/auth/me",
    response_model=UserMeResponse,
    summary="Get current authenticated user",
)
async def get_current_user() -> UserMeResponse:
    """Retrieve current session identity."""
    return UserMeResponse(user_id="dev-trader-1", role="admin")


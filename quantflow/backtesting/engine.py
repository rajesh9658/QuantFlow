"""Backtesting pipeline and single-run execution engine."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
import inspect
import time as _time
from typing import Any

from quantflow.analytics.engine import AnalyticsEngine
from quantflow.common.events import (
    FillEvent,
    OrderBookEvent,
    RejectedSignalEvent,
    SignalEvent,
    TickEvent,
)
from quantflow.config.manager import ConfigManager
from quantflow.core.clock import SimulatedClock
from quantflow.core.event_bus import AsyncEventBus, InMemoryEventBus
from quantflow.core.interfaces import Strategy
from quantflow.core.logging import get_logger
from quantflow.exchanges.null import NullExchangeAdapter
from quantflow.execution.paper import PaperExecutionHandler
from quantflow.market_data.engine import MarketDataEngine
from quantflow.market_data.orderbook import LocalOrderBook
from quantflow.portfolio.engine import PortfolioEngine
from quantflow.replay.engine import ReplayEngine, ReplaySpeed
from quantflow.replay.event_store import EventStoreReader
from quantflow.risk.engine import RiskEngine

logger = get_logger("backtest_engine")


@dataclass
class BacktestPipeline:
    """All wired components for a single backtest run."""

    clock: SimulatedClock
    event_bus: AsyncEventBus
    replay: ReplayEngine
    strategy: Strategy
    execution: PaperExecutionHandler
    portfolio: PortfolioEngine
    risk: RiskEngine
    analytics: AnalyticsEngine
    market_engine: MarketDataEngine


@dataclass
class BacktestResult:
    """Output of a single backtest run."""

    params: dict[str, Any]
    start: datetime
    end: datetime

    # Metrics from AnalyticsEngine (Sprint 11)
    metrics: dict[str, float]
    equity_curve: list[tuple[datetime, float]]
    trades: list[dict[str, Any]]
    signals: list[dict[str, Any]]
    rejected_signals: list[dict[str, Any]]

    # Diagnostics
    duration_seconds: float
    event_count: int
    success: bool
    error: str | None = None


def build_backtest_pipeline(
    base_config: ConfigManager | None,
    data_reader: EventStoreReader,
    strategy_cls: type[Strategy],
    strategy_params: dict[str, Any],
    start: datetime,
    end: datetime,
) -> BacktestPipeline:
    """Construct a fresh, fully-wired backtest pipeline.

    Deterministic: no network, no wall-clock, no external state.
    """
    start_tz = start.replace(tzinfo=UTC) if start.tzinfo is None else start

    clock = SimulatedClock(start_time=start_tz)
    event_bus = InMemoryEventBus(clock=clock)

    config = base_config if base_config is not None else ConfigManager(
        defaults={
            "risk": {
                "allowed_symbols": ["BTC/USDT", "ETH/USDT"],
                "max_position_qty": 1000.0,
                "max_daily_loss": 100000.0,
            },
            "portfolio": {"initial_cash": 100000.0},
            "analytics": {"risk_free_rate": 0.0, "annualization_factor": 252.0},
        }
    )

    # In-memory order books dict shared between market data, price provider, and execution
    order_books: dict[str, LocalOrderBook] = {}

    symbol = strategy_params.get("symbol")
    if symbol:
        order_books[symbol] = LocalOrderBook(symbol)

    last_prices: dict[str, float] = {}

    # Event handlers to update LocalOrderBooks dynamically as ticks/orderbooks are replayed
    async def _on_order_book_update(ev: OrderBookEvent) -> None:
        book = order_books.setdefault(ev.symbol, LocalOrderBook(ev.symbol))
        await book.apply_snapshot(
            bids=ev.bids,
            asks=ev.asks,
            update_id=int(clock.now().timestamp() * 1000),
        )

    async def _on_tick_update(ev: TickEvent) -> None:
        last_prices[ev.symbol] = ev.last_price
        book = order_books.setdefault(ev.symbol, LocalOrderBook(ev.symbol))
        bid = ev.bid_price if ev.bid_price > 0 else (ev.last_price - 0.5)
        ask = ev.ask_price if ev.ask_price > 0 else (ev.last_price + 0.5)
        bid_sz = ev.bid_size if ev.bid_size > 0 else 10.0
        ask_sz = ev.ask_size if ev.ask_size > 0 else 10.0
        if bid > 0 and ask > 0:
            await book.apply_snapshot(
                bids=[[bid, bid_sz]],
                asks=[[ask, ask_sz]],
                update_id=int(clock.now().timestamp() * 1000),
            )

    # Hook into subscriber list synchronously
    event_bus._subscribers[OrderBookEvent].append(_on_order_book_update)
    event_bus._subscribers[TickEvent].append(_on_tick_update)

    market_engine = MarketDataEngine(event_bus=event_bus, clock=clock)

    execution = PaperExecutionHandler(
        config=config,
        event_bus=event_bus,
        order_books=order_books,
        clock=clock,
    )

    def price_provider(sym: str) -> float | None:
        book = order_books.get(sym)
        if book:
            mid = book.mid_price()
            if mid is not None:
                return mid
        return last_prices.get(sym)

    portfolio = PortfolioEngine(
        config=config,
        event_bus=event_bus,
        price_provider=price_provider,
        initial_cash_or_clock=clock,
        clock=clock,
    )

    exchange = NullExchangeAdapter(clock=clock)
    risk = RiskEngine(
        config=config,
        event_bus=event_bus,
        exchange_adapter=exchange,
        execution_handler=execution,
        clock_or_checks=clock,
        clock=clock,
    )

    analytics = AnalyticsEngine(config=config, event_bus=event_bus, clock=clock)

    # In backtests, fills emitted by pure fill_simulator have realized_pnl=0.0.
    # Track positions to pass calculated realized_pnl to analytics for trade stats.
    orig_handle_fill = analytics._handle_fill
    pos_tracker: dict[str, dict[str, float]] = {}

    async def _enriched_handle_fill(event: FillEvent | Any) -> None:
        payload = getattr(event, "payload", event)
        sym = str(getattr(payload, "symbol", ""))
        side_val = getattr(payload, "side", "")
        side_str = str(getattr(side_val, "value", side_val)).upper()
        px = float(getattr(payload, "price", getattr(payload, "fill_price", 0.0)))
        qty = float(getattr(payload, "quantity", 0.0))

        if sym not in pos_tracker:
            pos_tracker[sym] = {"qty": 0.0, "cost": 0.0}
        pos = pos_tracker[sym]

        pnl = float(getattr(payload, "realized_pnl", 0.0))
        if pnl == 0.0:
            if pos["qty"] > 0 and side_str == "SELL":
                close_qty = min(pos["qty"], qty)
                avg_px = pos["cost"] / pos["qty"]
                pnl = (px - avg_px) * close_qty
                pos["cost"] -= avg_px * close_qty
                pos["qty"] -= close_qty
            elif pos["qty"] < 0 and side_str == "BUY":
                close_qty = min(abs(pos["qty"]), qty)
                avg_px = pos["cost"] / abs(pos["qty"])
                pnl = (avg_px - px) * close_qty
                pos["cost"] -= avg_px * close_qty
                pos["qty"] -= close_qty
            else:
                pos["qty"] += qty if side_str == "BUY" else -qty
                pos["cost"] += px * qty

        if pnl != 0.0 and hasattr(event, "model_copy"):
            enriched = event.model_copy(update={"realized_pnl": pnl})
            await orig_handle_fill(enriched)
        else:
            await orig_handle_fill(event)

    analytics._handle_fill = _enriched_handle_fill

    # Instantiate strategy
    strat_factory: Any = strategy_cls
    try:
        strategy: Strategy = strat_factory(event_bus=event_bus, config=strategy_params, clock=clock)
    except TypeError:
        try:
            strategy = strat_factory(event_bus=event_bus, config=strategy_params)
        except TypeError:
            strategy = strat_factory()

    replay = ReplayEngine(
        event_store=data_reader,
        event_bus=event_bus,
        clock=clock,
        speed=ReplaySpeed.INSTANT,
    )

    return BacktestPipeline(
        clock=clock,
        event_bus=event_bus,
        replay=replay,
        strategy=strategy,
        execution=execution,
        portfolio=portfolio,
        risk=risk,
        analytics=analytics,
        market_engine=market_engine,
    )


class BacktestEngine:
    """Runs a single backtest for a strategy + parameter set over [start, end].

    Deterministic: reuses Sprint 8, 11, and 13 without modification.
    """

    def __init__(self, base_config: ConfigManager | None = None) -> None:
        self.config = base_config if base_config is not None else ConfigManager()

    async def run(
        self,
        data_reader: EventStoreReader,
        strategy_cls: type[Strategy],
        params: dict[str, Any],
        start: datetime,
        end: datetime,
    ) -> BacktestResult:
        """Run single deterministic backtest over the time range [start, end)."""
        start_tz = start.replace(tzinfo=UTC) if start.tzinfo is None else start
        end_tz = end.replace(tzinfo=UTC) if end.tzinfo is None else end

        pipeline = build_backtest_pipeline(
            base_config=self.config,
            data_reader=data_reader,
            strategy_cls=strategy_cls,
            strategy_params=params,
            start=start_tz,
            end=end_tz,
        )

        captured_fills: list[dict[str, Any]] = []
        captured_signals: list[dict[str, Any]] = []
        captured_rejected: list[dict[str, Any]] = []

        running_positions: dict[str, dict[str, float]] = {}

        async def on_fill(ev: FillEvent) -> None:
            payload = getattr(ev, "payload", ev)
            side = getattr(payload, "side", "")
            side_str = str(getattr(side, "value", side)).upper()
            sym = str(getattr(payload, "symbol", ""))
            fill_px = float(getattr(payload, "price", getattr(payload, "fill_price", 0.0)))
            fill_qty = float(getattr(payload, "quantity", 0.0))

            if sym not in running_positions:
                running_positions[sym] = {"qty": 0.0, "cost": 0.0}
            pos = running_positions[sym]

            pnl = float(getattr(payload, "realized_pnl", 0.0))
            if pnl == 0.0:
                if pos["qty"] > 0 and side_str == "SELL":
                    close_qty = min(pos["qty"], fill_qty)
                    avg_px = pos["cost"] / pos["qty"]
                    pnl = (fill_px - avg_px) * close_qty
                    pos["cost"] -= avg_px * close_qty
                    pos["qty"] -= close_qty
                elif pos["qty"] < 0 and side_str == "BUY":
                    close_qty = min(abs(pos["qty"]), fill_qty)
                    avg_px = pos["cost"] / abs(pos["qty"])
                    pnl = (avg_px - fill_px) * close_qty
                    pos["cost"] -= avg_px * close_qty
                    pos["qty"] += close_qty
                else:
                    pos["qty"] += fill_qty if side_str == "BUY" else -fill_qty
                    pos["cost"] += fill_px * fill_qty

            captured_fills.append(
                {
                    "fill_id": str(getattr(payload, "fill_id", getattr(ev, "event_id", ""))),
                    "order_id": getattr(payload, "order_id", ""),
                    "symbol": sym,
                    "side": side_str,
                    "price": fill_px,
                    "quantity": fill_qty,
                    "commission": float(getattr(payload, "commission", 0.0)),
                    "realized_pnl": pnl,
                    "timestamp": getattr(ev, "timestamp_exchange", getattr(ev, "timestamp", None)),
                }
            )

        async def on_signal(ev: SignalEvent) -> None:
            payload = getattr(ev, "payload", ev)
            direction = getattr(payload, "direction", getattr(payload, "side", ""))
            dir_str = str(getattr(direction, "value", direction))
            captured_signals.append(
                {
                    "event_id": str(ev.event_id),
                    "strategy": getattr(payload, "strategy_id", ""),
                    "symbol": getattr(payload, "symbol", ""),
                    "direction": dir_str.upper(),
                    "side": dir_str.upper(),
                    "confidence": float(
                        getattr(payload, "confidence", getattr(payload, "signal_strength", 1.0))
                    ),
                    "timestamp": getattr(ev, "timestamp_exchange", getattr(ev, "timestamp", None)),
                }
            )

        async def on_rejected(ev: RejectedSignalEvent) -> None:
            payload = getattr(ev, "payload", ev)
            captured_rejected.append(
                {
                    "signal_id": str(getattr(payload, "signal_id", getattr(ev, "event_id", ""))),
                    "reason": getattr(payload, "reason", ""),
                    "timestamp": getattr(ev, "timestamp_exchange", getattr(ev, "timestamp", None)),
                }
            )

        await pipeline.event_bus.subscribe(FillEvent, on_fill)
        await pipeline.event_bus.subscribe(SignalEvent, on_signal)
        await pipeline.event_bus.subscribe(RejectedSignalEvent, on_rejected)

        # Start components
        await pipeline.analytics.start()
        await pipeline.portfolio.start()
        await pipeline.execution.start()
        await pipeline.risk.start()

        strat_obj: Any = pipeline.strategy
        if hasattr(strat_obj, "initialize") and callable(strat_obj.initialize):
            try:
                res = strat_obj.initialize(config=params, clock=pipeline.clock)
            except TypeError:
                try:
                    res = strat_obj.initialize(params)
                except TypeError:
                    res = strat_obj.initialize()
            if inspect.isawaitable(res):
                await res

        if hasattr(strat_obj, "start") and callable(strat_obj.start):
            res_start = strat_obj.start()
            if inspect.isawaitable(res_start):
                await res_start

        wall_start = _time.monotonic()
        error: str | None = None
        success = True
        try:
            await pipeline.replay.run(start_tz, end_tz)
            # Brief yield to let final asynchronous callbacks complete
            await asyncio.sleep(0.01)
        except Exception as e:
            success = False
            error = str(e)
            logger.error("Backtest run failed: %s", e, exc_info=True)
        wall_duration = _time.monotonic() - wall_start

        # Stop in reverse order
        if hasattr(strat_obj, "stop") and callable(strat_obj.stop):
            res_stop = strat_obj.stop()
            if inspect.isawaitable(res_stop):
                await res_stop
        await pipeline.risk.stop()
        await pipeline.execution.stop()
        await pipeline.portfolio.stop()
        await pipeline.analytics.stop()

        return BacktestResult(
            params=params,
            start=start_tz,
            end=end_tz,
            metrics=pipeline.analytics.get_metrics(),
            equity_curve=pipeline.analytics.get_equity_curve(),
            trades=captured_fills,
            signals=captured_signals,
            rejected_signals=captured_rejected,
            duration_seconds=wall_duration,
            event_count=len(captured_fills) + len(captured_signals),
            success=success,
            error=error,
        )

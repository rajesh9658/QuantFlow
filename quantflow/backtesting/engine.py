"""Deterministic cash-spot backtesting using the same paper ledger as the app."""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from quantflow.analytics.engine import AnalyticsEngine
from quantflow.common.events import (
    FillEvent,
    OrderBookEvent,
    OrderEvent,
    RejectedSignalEvent,
    SignalEvent,
    TickEvent,
)
from quantflow.config.manager import ConfigManager
from quantflow.core.clock import SimulatedClock
from quantflow.core.event_bus import AsyncEventBus, InMemoryEventBus
from quantflow.core.interfaces import Strategy
from quantflow.exchanges.null import NullExchangeAdapter as NullExchangeAdapter
from quantflow.execution.paper import PaperExecutionHandler
from quantflow.market_data.engine import MarketDataEngine
from quantflow.market_data.orderbook import LocalOrderBook
from quantflow.portfolio.engine import PortfolioEngine
from quantflow.portfolio.ledger import AccountLedger
from quantflow.replay.engine import ReplayEngine, ReplaySpeed
from quantflow.replay.event_store import EventStoreReader
from quantflow.risk.engine import RiskEngine


@dataclass
class BacktestPipeline:
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
    params: dict[str, Any]
    start: datetime
    end: datetime
    metrics: dict[str, float]
    equity_curve: list[tuple[datetime, float]]
    trades: list[dict[str, Any]]
    signals: list[dict[str, Any]]
    rejected_signals: list[dict[str, Any]]
    duration_seconds: float
    event_count: int
    success: bool
    error: str | None = None
    exposure_history: dict[datetime, float] = field(default_factory=dict)


def build_backtest_pipeline(
    base_config: ConfigManager | None,
    data_reader: EventStoreReader,
    strategy_cls: type[Strategy],
    strategy_params: dict[str, Any],
    start: datetime,
    end: datetime,
) -> BacktestPipeline:
    start = start.replace(tzinfo=UTC) if start.tzinfo is None else start
    clock = SimulatedClock(start_time=start)
    bus = InMemoryEventBus(clock=clock)
    cfg = base_config if base_config is not None else ConfigManager(env_dict={})
    ledger = AccountLedger(
        float(cfg.get("portfolio.initial_cash", 200.0)), float(cfg.get("tax.rate", 0.0))
    )
    books: dict[str, LocalOrderBook] = {}
    portfolio = PortfolioEngine(
        config=cfg,
        event_bus=bus,
        clock=clock,
        ledger=ledger,
        initial_cash=ledger.initial_cash,
    )
    execution = PaperExecutionHandler(
        config=cfg, event_bus=bus, clock=clock, order_books=books, ledger=ledger
    )
    risk = RiskEngine(
        config=cfg,
        event_bus=bus,
        execution_handler=execution,
        clock=clock,
        ledger=ledger,
    )
    analytics = AnalyticsEngine(config=cfg, event_bus=bus, clock=clock)

    async def on_book(ev: OrderBookEvent) -> None:
        book = books.setdefault(ev.symbol, LocalOrderBook(ev.symbol))
        await book.apply_snapshot(ev.bids, ev.asks, int(clock.now().timestamp() * 1000))
        mid = book.mid_price()
        if mid:
            risk.market_prices[ev.symbol] = mid
            await portfolio.update_mark_price(ev.symbol, mid)

    async def on_tick(ev: TickEvent) -> None:
        if ev.bid_price <= 0 or ev.ask_price < ev.bid_price or ev.last_price <= 0:
            raise ValueError("Invalid historical quote")
        book = books.setdefault(ev.symbol, LocalOrderBook(ev.symbol))
        await book.apply_snapshot(
            [[ev.bid_price, ev.bid_size]],
            [[ev.ask_price, ev.ask_size]],
            int(clock.now().timestamp() * 1000),
        )
        risk.market_prices[ev.symbol] = ev.last_price
        await portfolio.update_mark_price(ev.symbol, ev.last_price)

    bus._subscribers[OrderBookEvent].append(on_book)
    bus._subscribers[TickEvent].append(on_tick)
    factory: Any = strategy_cls
    strategy = factory(event_bus=bus, config=strategy_params, clock=clock)
    replay = ReplayEngine(
        event_store=data_reader, event_bus=bus, clock=clock, speed=ReplaySpeed.INSTANT
    )
    return BacktestPipeline(
        clock,
        bus,
        replay,
        strategy,
        execution,
        portfolio,
        risk,
        analytics,
        MarketDataEngine(event_bus=bus, clock=clock),
    )


class BacktestEngine:
    def __init__(self, base_config: ConfigManager | None = None) -> None:
        self.config = base_config or ConfigManager(env_dict={})

    async def run(
        self,
        data_reader: EventStoreReader,
        strategy_cls: type[Strategy],
        params: dict[str, Any],
        start: datetime,
        end: datetime,
    ) -> BacktestResult:
        start = start.replace(tzinfo=UTC) if start.tzinfo is None else start
        end = end.replace(tzinfo=UTC) if end.tzinfo is None else end
        if end <= start:
            raise ValueError("Backtest end must be after start")
        if float(self.config.get("portfolio.initial_cash", 200.0)) <= 0:
            raise ValueError("Backtest cash must be positive")
        pipeline = build_backtest_pipeline(
            self.config, data_reader, strategy_cls, params, start, end
        )
        fills, signals, rejected = [], [], []

        async def on_fill(ev: FillEvent) -> None:
            fills.append(
                {
                    "fill_id": ev.fill_id,
                    "order_id": ev.order_id,
                    "symbol": ev.symbol,
                    "side": ev.side,
                    "price": ev.fill_price,
                    "quantity": ev.quantity,
                    "commission": ev.commission,
                    "realized_pnl": ev.realized_pnl,
                    "gross_realized_pnl": ev.metadata.get("gross_realized_pnl", 0.0),
                    "closed_trade_pnl": ev.metadata.get("closed_trade_pnl", 0.0),
                    "closed_quantity": ev.metadata.get("closed_quantity", 0.0),
                    "taxable_gain": ev.metadata.get("taxable_gain", 0.0),
                    "timestamp": ev.timestamp_exchange or ev.timestamp,
                }
            )

        async def on_signal(ev: SignalEvent) -> None:
            signals.append(
                {
                    "event_id": ev.event_id,
                    "strategy": ev.strategy_id,
                    "symbol": ev.symbol,
                    "direction": ev.side,
                    "side": ev.side,
                    "confidence": ev.signal_strength,
                    "timestamp": ev.timestamp,
                }
            )

        async def on_rejected(ev: RejectedSignalEvent) -> None:
            rejected.append(
                {
                    "signal_id": ev.signal_id,
                    "reason": ev.reason,
                    "timestamp": ev.timestamp,
                }
            )

        await pipeline.event_bus.subscribe(FillEvent, on_fill)
        await pipeline.event_bus.subscribe(SignalEvent, on_signal)
        await pipeline.event_bus.subscribe(RejectedSignalEvent, on_rejected)
        wall_start, error = time.perf_counter(), None
        try:
            await pipeline.analytics.start()
            await pipeline.risk.start()
            await pipeline.portfolio.start()
            await pipeline.execution.start()
            await pipeline.portfolio._publish_update()
            await pipeline.strategy.initialize(config=params, clock=pipeline.clock)
            await pipeline.replay.run(start, end)
            pipeline.clock.advance_to(end)
            if self.config.get("backtest.close_at_end", False):
                for symbol, quantity in pipeline.portfolio.get_positions().items():
                    await pipeline.execution.submit_order(
                        OrderEvent(
                            strategy_id="backtest_close",
                            symbol=symbol,
                            side="SELL",
                            order_type="MARKET",
                            quantity=quantity,
                        )
                    )
            await pipeline.portfolio._recalculate_valuation()
            await pipeline.portfolio._publish_update()
            pipeline.analytics.finalize()
            if pipeline.replay.events_published == 0:
                raise ValueError("No historical events in requested range")
        except Exception as exc:
            error = str(exc)
        finally:
            stop = getattr(pipeline.strategy, "stop", None)
            if stop is not None:
                result = stop()
                if inspect.isawaitable(result):
                    await result
            await pipeline.execution.stop()
            await pipeline.portfolio.stop()
            await pipeline.risk.stop()
            await pipeline.analytics.stop()
        ledger = pipeline.execution.ledger
        equity = pipeline.portfolio.get_total_equity()
        metrics = pipeline.analytics.get_metrics()
        metrics.update(
            {
                "initial_cash": ledger.initial_cash,
                "final_equity": equity,
                "total_commission": ledger.total_fees,
                "taxable_gains_estimate": ledger.taxable_gains,
                "tax_reserve_estimate": ledger.tax_reserve,
                "after_tax_equity_estimate": equity - ledger.tax_reserve,
                "after_tax_pnl_estimate": equity
                - ledger.tax_reserve
                - ledger.initial_cash,
                "after_tax_return_estimate": (equity - ledger.tax_reserve)
                / ledger.initial_cash
                - 1,
                "available_cash_after_tax_reserve": ledger.available_cash,
                "open_position_count": float(len(pipeline.portfolio.get_positions())),
            }
        )
        return BacktestResult(
            params,
            start,
            end,
            metrics,
            pipeline.analytics.get_equity_curve(),
            fills,
            signals,
            rejected,
            time.perf_counter() - wall_start,
            pipeline.replay.events_published,
            error is None,
            error,
            pipeline.analytics.exposure_history,
        )

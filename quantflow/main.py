"""Paper-only application composition. Historical research never places orders."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from quantflow.analytics.engine import AnalyticsEngine
from quantflow.api.app import create_app as create_api_app
from quantflow.api.dependencies import APIState, set_api_state
from quantflow.api.websocket import ws_manager
from quantflow.common.events import FillEvent, OrderBookEvent, TickEvent
from quantflow.config.manager import ConfigManager
from quantflow.core.clock import SystemClock
from quantflow.core.event_bus import InMemoryEventBus
from quantflow.core.interfaces import EventBus
from quantflow.core.logging import setup_logging
from quantflow.core.scheduler import AsyncIOScheduler
from quantflow.execution.paper import PaperExecutionHandler
from quantflow.market_data.orderbook import LocalOrderBook
from quantflow.portfolio.engine import PortfolioEngine
from quantflow.portfolio.ledger import AccountLedger
from quantflow.replay.event_store import SyntheticEventStore
from quantflow.risk.engine import RiskEngine
from quantflow.strategies.engine import StrategyEngine
from quantflow.strategies.momentum.strategy import SimpleMomentumStrategy


async def _run_synthetic_feed(
    event_bus: EventBus, stop_event: asyncio.Event, interval_seconds: float = 1.0
) -> None:
    """Explicit demo feed only; never used as historical profitability evidence."""
    store = SyntheticEventStore(symbols=["BTC/USDT"])
    step = 0
    while not stop_event.is_set():
        for symbol in store.symbols:
            await event_bus.publish(store.generate_tick(symbol, step=step))
        step += 1
        with suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    config = ConfigManager(
        config_path=os.environ.get("QUANTFLOW_CONFIG_PATH", "config/paper.india.yaml")
    )
    setup_logging(level=config.get("log_level", "INFO"))
    if os.environ.get("APP_ENV", config.get("environment", "paper")).lower() == "live":
        raise RuntimeError(
            "Live execution is unavailable: this build supports "
            "cash-spot paper research only"
        )
    source = config.get("market_data.source", "none")
    if source not in {"none", "demo"}:
        raise ValueError(
            "Use market_data.source none or demo for the paper app; "
            "use the historical research runner for CSV data"
        )
    clock, bus = SystemClock(), InMemoryEventBus()
    ledger = AccountLedger(
        float(config.get("portfolio.initial_cash", 200.0)),
        float(config.get("tax.rate", 0.312)),
    )
    books: dict[str, LocalOrderBook] = {}
    portfolio = PortfolioEngine(
        config=config,
        event_bus=bus,
        clock=clock,
        initial_cash=ledger.initial_cash,
        ledger=ledger,
    )
    execution = PaperExecutionHandler(
        config=config, event_bus=bus, clock=clock, order_books=books, ledger=ledger
    )
    risk = RiskEngine(
        config=config,
        event_bus=bus,
        clock=clock,
        execution_handler=execution,
        ledger=ledger,
    )
    analytics = AnalyticsEngine(config=config, event_bus=bus, clock=clock)

    async def on_tick(event: TickEvent) -> None:
        book = books.setdefault(event.symbol, LocalOrderBook(event.symbol))
        await book.apply_snapshot(
            [[event.bid_price, event.bid_size]],
            [[event.ask_price, event.ask_size]],
            int(clock.now().timestamp() * 1000),
        )
        await portfolio.update_mark_price(event.symbol, event.last_price)

    async def on_book(event: OrderBookEvent) -> None:
        book = books.setdefault(event.symbol, LocalOrderBook(event.symbol))
        await book.apply_snapshot(
            event.bids, event.asks, int(clock.now().timestamp() * 1000)
        )
        mid = book.mid_price()
        if mid is not None:
            await portfolio.update_mark_price(event.symbol, mid)

    await bus.subscribe(TickEvent, on_tick)
    await bus.subscribe(OrderBookEvent, on_book)
    params = config.get(
        "strategies.SimpleMomentum", {"symbol": "BTC/USDT", "order_notional": 20.0}
    )
    strategies = StrategyEngine(
        bus, {"Simple Momentum": SimpleMomentumStrategy(bus, params, clock)}, clock
    )
    scheduler = AsyncIOScheduler()
    state = APIState(config, bus, portfolio, risk, analytics, strategies)
    set_api_state(state)
    app.state.pipeline_started = False
    app.state.data_source = source

    async def on_fill(event: FillEvent) -> None:
        state._trades.append(
            {
                "fill_id": event.fill_id,
                "order_id": event.order_id,
                "symbol": event.symbol,
                "side": event.side.lower(),
                "price": event.fill_price,
                "quantity": event.quantity,
                "commission": event.commission,
                "realized_pnl": event.realized_pnl,
                "timestamp_exchange": (
                    event.timestamp_exchange or event.timestamp
                ).isoformat(),
            }
        )

    await bus.subscribe(FillEvent, on_fill)
    task, stop = None, asyncio.Event()
    try:
        await analytics.start()
        await risk.start()
        await portfolio.start()
        await execution.start()
        await portfolio._publish_update()
        await strategies.start()
        await scheduler.start()
        await ws_manager.subscribe_to_event_bus(bus)
        app.state.pipeline_started = True
        if source == "demo":
            task = asyncio.create_task(_run_synthetic_feed(bus, stop))
        yield
    finally:
        app.state.pipeline_started = False
        if task:
            stop.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await state.close()
        await ws_manager.unsubscribe_from_event_bus()
        await scheduler.stop()
        await strategies.stop()
        await execution.stop()
        await portfolio.stop()
        await risk.stop()
        await analytics.stop()


def create_app() -> FastAPI:
    application = create_api_app()
    application.router.lifespan_context = lifespan
    return application


app = create_app()
__all__ = ["app", "create_app"]

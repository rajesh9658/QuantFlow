"""Integration tests for multi-exchange market data and routing correctness."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from quantflow.common.events import (
    OrderBookEvent,
    OrderEvent,
    TickEvent,
    TradeEvent,
)
from quantflow.config.manager import ConfigManager
from quantflow.core.clock import SystemClock
from quantflow.core.event_bus import AsyncEventBus
from quantflow.core.exchange_registry import ExchangeRegistry
from quantflow.core.interfaces import ExchangeAdapter
from quantflow.execution.paper import PaperExecutionHandler
from quantflow.market_data.engine import MarketDataEngine
from quantflow.market_data.raw import RawMarketData
from quantflow.market_data.symbol_mapper import SymbolMapper
from quantflow.risk.engine import RiskEngine
from quantflow.strategies.momentum.strategy import SimpleMomentumStrategy


class MockStreamAdapter(ExchangeAdapter):
    """Adapter that pushes recorded fixture streams to its sink."""

    def __init__(self, exchange_id: str, sink: MarketDataEngine) -> None:
        self.exchange_id = exchange_id
        self.sink = sink
        self.placed_orders: list[OrderEvent] = []

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def subscribe_market_data(self, symbols: list[str]) -> None:
        pass

    async def place_order(self, order: OrderEvent) -> str:
        self.placed_orders.append(order)
        return f"{self.exchange_id}_order_{len(self.placed_orders)}"

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def get_balances(self) -> dict[str, float]:
        return {}

    async def emit_fixture_stream(self, frames: list[dict]) -> None:
        for f in frames:
            raw = RawMarketData(
                exchange_id=self.exchange_id,
                symbol_native=f["symbol"],
                kind=f["kind"],
                data=f["data"],
                received_at=SystemClock().now(),
            )
            await self.sink.on_raw_market_data(raw)
            await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_market_data_engine_concurrent_isolation() -> None:
    """Market data engine publishes events from both exchanges concurrently

    without cross-contaminating exchange_id tags.
    """
    bus = AsyncEventBus()
    config = ConfigManager(
        defaults={
            "exchanges": [
                {
                    "exchange_id": "binance",
                    "type": "binance",
                    "symbols": {"BTC/USDT": "BTCUSDT", "ETH/USDT": "ETHUSDT"},
                },
                {
                    "exchange_id": "bybit",
                    "type": "bybit",
                    "symbols": {"BTC/USDT": "BTCUSDT", "ETH/USDT": "ETHUSDT"},
                },
            ]
        }
    )
    symbol_mapper = SymbolMapper(config)
    engine = MarketDataEngine(
        event_bus=bus, clock=SystemClock(), symbol_mapper=symbol_mapper
    )

    binance_adapter = MockStreamAdapter("binance", sink=engine)
    bybit_adapter = MockStreamAdapter("bybit", sink=engine)

    q_ticks = await bus.subscribe_queue(TickEvent, maxsize=50)
    q_books = await bus.subscribe_queue(OrderBookEvent, maxsize=50)
    q_trades = await bus.subscribe_queue(TradeEvent, maxsize=50)

    binance_fixtures = [
        {
            "symbol": "BTCUSDT",
            "kind": "ticker",
            "data": {"bid": 50000.0, "ask": 50001.0, "last": 50000.5, "volume": 10.0},
        },
        {
            "symbol": "BTCUSDT",
            "kind": "orderbook",
            "data": {"bids": [[50000.0, 1.0]], "asks": [[50001.0, 1.0]], "u": 1},
        },
        {
            "symbol": "BTCUSDT",
            "kind": "trade",
            "data": {"price": 50000.5, "size": 0.5, "trade_id": "binance_t1"},
        },
        {
            "symbol": "ETHUSDT",
            "kind": "ticker",
            "data": {"bid": 3000.0, "ask": 3001.0, "last": 3000.5, "volume": 20.0},
        },
    ]

    bybit_fixtures = [
        {
            "symbol": "BTCUSDT",
            "kind": "ticker",
            "data": {"bid": 49990.0, "ask": 49991.0, "last": 49990.5, "volume": 5.0},
        },
        {
            "symbol": "BTCUSDT",
            "kind": "orderbook",
            "data": {"bids": [[49990.0, 2.0]], "asks": [[49991.0, 2.0]], "u": 1},
        },
        {
            "symbol": "BTCUSDT",
            "kind": "trade",
            "data": {"price": 49990.5, "size": 1.5, "trade_id": "bybit_t1"},
        },
        {
            "symbol": "ETHUSDT",
            "kind": "ticker",
            "data": {"bid": 2990.0, "ask": 2991.0, "last": 2990.5, "volume": 15.0},
        },
    ]

    # Run both concurrently
    await asyncio.gather(
        binance_adapter.emit_fixture_stream(binance_fixtures),
        bybit_adapter.emit_fixture_stream(bybit_fixtures),
    )

    # Collect published events
    ticks: list[TickEvent] = []
    while not q_ticks.empty():
        ticks.append(q_ticks.get_nowait())

    books: list[OrderBookEvent] = []
    while not q_books.empty():
        books.append(q_books.get_nowait())

    trades: list[TradeEvent] = []
    while not q_trades.empty():
        trades.append(q_trades.get_nowait())

    assert len(ticks) == 4
    assert len(books) == 2
    assert len(trades) == 2

    # Verify Binance ticks
    binance_ticks = [t for t in ticks if t.exchange_id == "binance"]
    assert len(binance_ticks) == 2
    for t in binance_ticks:
        assert t.source == "binance"
        assert t.exchange == "binance"
        assert t.exchange_id == "binance"
        if t.symbol == "BTC/USDT":
            assert t.last_price == 50000.5

    # Verify Bybit ticks
    bybit_ticks = [t for t in ticks if t.exchange_id == "bybit"]
    assert len(bybit_ticks) == 2
    for t in bybit_ticks:
        assert t.source == "bybit"
        assert t.exchange == "bybit"
        assert t.exchange_id == "bybit"
        if t.symbol == "BTC/USDT":
            assert t.last_price == 49990.5

    # Verify books
    for b in books:
        assert b.source in ("binance", "bybit")
        assert b.exchange == b.source
        assert b.exchange_id == b.source
        if b.exchange_id == "binance":
            assert b.bids == [[50000.0, 1.0]]
        else:
            assert b.bids == [[49990.0, 2.0]]

    # Verify trades
    for tr in trades:
        assert tr.source in ("binance", "bybit")
        assert tr.exchange == tr.source
        assert tr.exchange_id == tr.source
        if tr.exchange_id == "binance":
            assert tr.trade_id == "binance_t1"
            assert tr.price == 50000.5
        else:
            assert tr.trade_id == "bybit_t1"
            assert tr.price == 49990.5


@pytest.mark.asyncio
async def test_signal_routing_isolation_bybit_and_binance() -> None:
    """A signal generated by a strategy configured for 'bybit' never reaches

    the Binance adapter, and vice versa (routing correctness test).
    """
    bus = AsyncEventBus()
    clock = SystemClock()

    config = ConfigManager(
        defaults={
            "exchanges": [
                {
                    "exchange_id": "binance",
                    "type": "binance",
                    "symbols": {"BTC/USDT": "BTCUSDT"},
                },
                {
                    "exchange_id": "bybit",
                    "type": "bybit",
                    "symbols": {"BTC/USDT": "BTCUSDT"},
                },
            ],
            "risk": {
                "max_order_quantity": 10.0,
                "max_drawdown_pct": 0.5,
            },
        }
    )
    symbol_mapper = SymbolMapper(config)

    binance_adapter = MockStreamAdapter("binance", sink=MagicMock())
    bybit_adapter = MockStreamAdapter("bybit", sink=MagicMock())

    registry = ExchangeRegistry(config, clock)
    await registry.register("binance", binance_adapter)
    await registry.register("bybit", bybit_adapter)

    # Set up Execution Handler with registry
    execution = PaperExecutionHandler(
        config=config,
        event_bus=bus,
        order_books={},
        clock=clock,
        registry=registry,
        symbol_mapper=symbol_mapper,
    )
    await execution.start()

    # Set up RiskEngine
    risk = RiskEngine(config=config, event_bus=bus, execution=execution, clock=clock)
    await risk.start()

    # Strategy 1: Configured specifically for Bybit
    strat_bybit = SimpleMomentumStrategy(
        event_bus=bus,
        config={
            "symbol": "BTC/USDT",
            "exchange_id": "bybit",
            "period": 2,
            "threshold": 0.01,
        },
        clock=clock,
    )
    await strat_bybit.initialize()

    # Strategy 2: Configured specifically for Binance
    strat_binance = SimpleMomentumStrategy(
        event_bus=bus,
        config={
            "symbol": "BTC/USDT",
            "exchange_id": "binance",
            "period": 2,
            "threshold": 0.01,
        },
        clock=clock,
    )
    await strat_binance.initialize()

    # 1. Send tick stream tagged for Bybit (rising prices: 100 -> 101 -> 103)
    # This should trigger Bybit strategy ONLY
    await bus.publish(
        TickEvent(
            symbol="BTC/USDT",
            exchange_id="bybit",
            last_price=100.0,
            bid_price=99.9,
            ask_price=100.1,
            bid_size=1.0,
            ask_size=1.0,
            last_size=1.0,
        )
    )
    await asyncio.sleep(0.01)
    await bus.publish(
        TickEvent(
            symbol="BTC/USDT",
            exchange_id="bybit",
            last_price=101.0,
            bid_price=100.9,
            ask_price=101.1,
            bid_size=1.0,
            ask_size=1.0,
            last_size=1.0,
        )
    )
    await asyncio.sleep(0.01)
    await bus.publish(
        TickEvent(
            symbol="BTC/USDT",
            exchange_id="bybit",
            last_price=103.0,
            bid_price=102.9,
            ask_price=103.1,
            bid_size=1.0,
            ask_size=1.0,
            last_size=1.0,
        )
    )
    await asyncio.sleep(0.05)

    # Assert: Bybit adapter received the order, Binance adapter received NOTHING
    assert len(bybit_adapter.placed_orders) == 1
    assert bybit_adapter.placed_orders[0].exchange_id == "bybit"
    assert len(binance_adapter.placed_orders) == 0

    # 2. Now send tick stream tagged for Binance (falling prices: 100 -> 99 -> 97)
    # This should trigger Binance strategy ONLY
    await bus.publish(
        TickEvent(
            symbol="BTC/USDT",
            exchange_id="binance",
            last_price=100.0,
            bid_price=99.9,
            ask_price=100.1,
            bid_size=1.0,
            ask_size=1.0,
            last_size=1.0,
        )
    )
    await asyncio.sleep(0.01)
    await bus.publish(
        TickEvent(
            symbol="BTC/USDT",
            exchange_id="binance",
            last_price=99.0,
            bid_price=98.9,
            ask_price=99.1,
            bid_size=1.0,
            ask_size=1.0,
            last_size=1.0,
        )
    )
    await asyncio.sleep(0.01)
    await bus.publish(
        TickEvent(
            symbol="BTC/USDT",
            exchange_id="binance",
            last_price=97.0,
            bid_price=96.9,
            ask_price=97.1,
            bid_size=1.0,
            ask_size=1.0,
            last_size=1.0,
        )
    )
    await asyncio.sleep(0.05)

    # Assert: Binance adapter received its order, Bybit adapter count did not change
    assert len(binance_adapter.placed_orders) == 1
    assert binance_adapter.placed_orders[0].exchange_id == "binance"
    assert len(bybit_adapter.placed_orders) == 1

    await risk.stop()

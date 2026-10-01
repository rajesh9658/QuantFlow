"""Tests for BybitAdapter: reconnect state machine, event mapping, and paper guard."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quantflow.common.events import (
    OrderBookEvent,
    OrderEvent,
    SystemEvent,
    TickEvent,
    TradeEvent,
)
from quantflow.core.event_bus import AsyncEventBus
from quantflow.exchanges.bybit.adapter import (
    BybitAdapter,
    ConnectionState,
    _orderbook_to_event,
    _ticker_to_event,
    _trade_to_event,
)

SAMPLE_TICKER = {
    "bid": 42000.5,
    "ask": 42001.0,
    "bidVolume": 1.2,
    "askVolume": 0.8,
    "last": 42000.75,
    "baseVolume": 350.0,
}

SAMPLE_ORDERBOOK = {
    "bids": [[42000.0, 1.5], [41999.0, 2.0]],
    "asks": [[42001.0, 0.8], [42002.0, 1.1]],
}

SAMPLE_TRADE = {
    "price": 42000.5,
    "amount": 0.25,
    "id": "t_bybit_123456",
}


@pytest.fixture
def bus() -> AsyncEventBus:
    return AsyncEventBus()


def _mock_exchange() -> MagicMock:
    """Return a mock ccxt.bybit instance with async methods."""
    ex = MagicMock()
    ex.load_markets = AsyncMock()
    ex.close = AsyncMock()
    ex.watch_ticker = AsyncMock(return_value=SAMPLE_TICKER)
    ex.watch_order_book = AsyncMock(return_value=SAMPLE_ORDERBOOK)
    ex.watch_trades = AsyncMock(return_value=[SAMPLE_TRADE])
    ex.fetch_balance = AsyncMock(return_value={"free": {"BTC": 0.5, "USDT": 10000.0}})
    ex.create_order = AsyncMock(return_value={"id": "bybit_order_abc"})
    ex.cancel_order = AsyncMock()
    return ex


@pytest.mark.asyncio
async def test_bybit_connect_emits_connected(bus: AsyncEventBus) -> None:
    events: list[SystemEvent] = []

    async def capture(ev: SystemEvent) -> None:
        events.append(ev)

    await bus.subscribe(SystemEvent, capture)

    adapter = BybitAdapter(bus, mode="paper")
    mock_ex = _mock_exchange()

    with patch.object(adapter, "_make_exchange", return_value=mock_ex):
        await adapter.connect()

    assert adapter.state == ConnectionState.CONNECTED
    assert len(events) == 1
    assert events[0].source == "bybit"
    assert events[0].state == "CONNECTED"


@pytest.mark.asyncio
async def test_bybit_disconnect_emits_disconnected(bus: AsyncEventBus) -> None:
    events: list[SystemEvent] = []

    async def capture(ev: SystemEvent) -> None:
        events.append(ev)

    await bus.subscribe(SystemEvent, capture)

    adapter = BybitAdapter(bus, mode="paper")
    mock_ex = _mock_exchange()

    with patch.object(adapter, "_make_exchange", return_value=mock_ex):
        await adapter.connect()
        await adapter.disconnect()

    assert adapter.state == ConnectionState.DISCONNECTED
    assert len(events) == 2
    assert events[1].source == "bybit"
    assert events[1].state == "DISCONNECTED"


@pytest.mark.asyncio
async def test_bybit_reconnect_retry_exhaustion(bus: AsyncEventBus) -> None:
    events: list[SystemEvent] = []

    async def capture(ev: SystemEvent) -> None:
        events.append(ev)

    await bus.subscribe(SystemEvent, capture)

    adapter = BybitAdapter(
        bus, mode="paper", max_retries=2, base_delay=0.01, max_delay=0.01
    )
    mock_ex = _mock_exchange()
    mock_ex.load_markets = AsyncMock(side_effect=ConnectionError("fail"))

    with patch.object(adapter, "_make_exchange", return_value=mock_ex):
        adapter._running = True
        reconnected = await adapter._handle_reconnect()

    assert reconnected is False
    assert adapter.state == ConnectionState.DISCONNECTED


@pytest.mark.asyncio
async def test_bybit_paper_orders(bus: AsyncEventBus) -> None:
    adapter = BybitAdapter(bus, mode="paper")
    mock_ex = _mock_exchange()
    with patch.object(adapter, "_make_exchange", return_value=mock_ex):
        await adapter.connect()

        order = OrderEvent(
            strategy_id="s1",
            symbol="BTC/USDT",
            exchange_id="bybit",
            side="BUY",
            order_type="LIMIT",
            quantity=0.1,
            price=40000.0,
        )
        oid = await adapter.place_order(order)
        assert oid == "bybit_order_abc"

        cancelled = await adapter.cancel_order("bybit_order_abc")
        assert cancelled is True

        balances = await adapter.get_balances()
        assert balances["BTC"] == 0.5
        assert balances["USDT"] == 10000.0


@pytest.mark.asyncio
async def test_bybit_live_mode_guard(bus: AsyncEventBus) -> None:
    adapter = BybitAdapter(bus, mode="live")
    order = OrderEvent(
        strategy_id="s1",
        symbol="BTC/USDT",
        exchange_id="bybit",
        side="BUY",
        order_type="MARKET",
        quantity=0.1,
    )
    with pytest.raises(NotImplementedError, match="Live trading not available"):
        await adapter.place_order(order)

    with pytest.raises(NotImplementedError, match="Live trading not available"):
        await adapter.cancel_order("any_id")


def test_bybit_event_converters() -> None:
    tick = _ticker_to_event("BTC/USDT", SAMPLE_TICKER, exchange_id="bybit")
    assert isinstance(tick, TickEvent)
    assert tick.exchange == "bybit"
    assert tick.exchange_id == "bybit"
    assert tick.source == "bybit"

    ob = _orderbook_to_event("BTC/USDT", SAMPLE_ORDERBOOK, exchange_id="bybit")
    assert isinstance(ob, OrderBookEvent)
    assert ob.exchange == "bybit"
    assert ob.exchange_id == "bybit"

    trade = _trade_to_event("BTC/USDT", SAMPLE_TRADE, exchange_id="bybit")
    assert isinstance(trade, TradeEvent)
    assert trade.exchange == "bybit"
    assert trade.exchange_id == "bybit"

"""Tests for BinanceAdapter: reconnect state machine, event mapping, paper guard."""

from __future__ import annotations

import asyncio
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
from quantflow.exchanges.binance.adapter import (
    BinanceAdapter,
    ConnectionState,
    _orderbook_to_event,
    _ticker_to_event,
    _trade_to_event,
)

# ── fixtures ────────────────────────────────────────────────────

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
    "id": "t_123456",
}


@pytest.fixture
def bus() -> AsyncEventBus:
    return AsyncEventBus()


def _mock_exchange() -> MagicMock:
    """Return a mock ccxt.binance instance with async methods."""
    ex = MagicMock()
    ex.load_markets = AsyncMock()
    ex.close = AsyncMock()
    ex.watch_ticker = AsyncMock(return_value=SAMPLE_TICKER)
    ex.watch_order_book = AsyncMock(return_value=SAMPLE_ORDERBOOK)
    ex.watch_trades = AsyncMock(return_value=[SAMPLE_TRADE])
    ex.fetch_balance = AsyncMock(
        return_value={"free": {"BTC": 0.5, "USDT": 10000.0}}
    )
    ex.create_order = AsyncMock(return_value={"id": "order_abc"})
    ex.cancel_order = AsyncMock()
    return ex


# ── 1. Reconnect state machine ──────────────────────────────────


@pytest.mark.asyncio
async def test_connect_emits_connected(bus: AsyncEventBus) -> None:
    events: list[SystemEvent] = []

    async def capture(ev: SystemEvent) -> None:
        events.append(ev)

    await bus.subscribe(SystemEvent, capture)

    adapter = BinanceAdapter(bus, mode="paper")
    mock_ex = _mock_exchange()

    with patch.object(adapter, "_make_exchange", return_value=mock_ex):
        await adapter.connect()

    assert adapter.state == ConnectionState.CONNECTED
    assert len(events) == 1
    assert events[0].state == "CONNECTED"


@pytest.mark.asyncio
async def test_disconnect_emits_disconnected(bus: AsyncEventBus) -> None:
    events: list[SystemEvent] = []

    async def capture(ev: SystemEvent) -> None:
        events.append(ev)

    await bus.subscribe(SystemEvent, capture)

    adapter = BinanceAdapter(bus, mode="paper")
    mock_ex = _mock_exchange()

    with patch.object(adapter, "_make_exchange", return_value=mock_ex):
        await adapter.connect()
        await adapter.disconnect()

    assert adapter.state == ConnectionState.DISCONNECTED
    states = [e.state for e in events]
    assert states == ["CONNECTED", "DISCONNECTED"]


@pytest.mark.asyncio
async def test_reconnect_on_watch_failure(bus: AsyncEventBus) -> None:
    """Simulate watch_ticker dropping mid-stream and verify
    RECONNECTING → CONNECTED transitions with fresh snapshot request."""
    events: list[SystemEvent] = []

    async def capture(ev: SystemEvent) -> None:
        events.append(ev)

    await bus.subscribe(SystemEvent, capture)

    adapter = BinanceAdapter(bus, mode="paper", base_delay=0.01, max_delay=0.01)
    mock_ex = _mock_exchange()

    call_count = 0

    async def flaky_watch_ticker(symbol: str) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise ConnectionError("ws dropped")
        if call_count > 3:
            # Stop after reconnect succeeds and one more tick
            adapter._running = False
            return SAMPLE_TICKER
        return SAMPLE_TICKER

    mock_ex.watch_ticker = AsyncMock(side_effect=flaky_watch_ticker)
    # watch_order_book and watch_trades: just stop immediately
    mock_ex.watch_order_book = AsyncMock(side_effect=asyncio.CancelledError)
    mock_ex.watch_trades = AsyncMock(side_effect=asyncio.CancelledError)

    # Second exchange instance for reconnect
    mock_ex2 = _mock_exchange()
    mock_ex2.watch_ticker = AsyncMock(side_effect=flaky_watch_ticker)
    mock_ex2.watch_order_book = AsyncMock(side_effect=asyncio.CancelledError)
    mock_ex2.watch_trades = AsyncMock(side_effect=asyncio.CancelledError)

    exchange_instances = iter([mock_ex, mock_ex2])

    with patch.object(
        adapter, "_make_exchange", side_effect=lambda: next(exchange_instances)
    ):
        await adapter.connect()
        await adapter.subscribe_market_data(["BTC/USDT"])
        # Wait for tasks to finish (flaky watch triggers reconnect then stops)
        await asyncio.sleep(0.3)

    states = [e.state for e in events]
    # Must see CONNECTED (initial), RECONNECTING, CONNECTED (reconnected)
    assert "CONNECTED" in states
    assert "RECONNECTING" in states
    # After RECONNECTING we should see CONNECTED again
    idx_recon = states.index("RECONNECTING")
    assert "CONNECTED" in states[idx_recon + 1 :]

    # Verify fresh load_markets was called on reconnect
    assert mock_ex2.load_markets.call_count >= 1


@pytest.mark.asyncio
async def test_max_retries_leads_to_disconnected(bus: AsyncEventBus) -> None:
    events: list[SystemEvent] = []

    async def capture(ev: SystemEvent) -> None:
        events.append(ev)

    await bus.subscribe(SystemEvent, capture)

    adapter = BinanceAdapter(
        bus, mode="paper", max_retries=1, base_delay=0.01, max_delay=0.01
    )
    mock_ex = _mock_exchange()
    mock_ex.watch_ticker = AsyncMock(side_effect=ConnectionError("dead"))
    mock_ex.watch_order_book = AsyncMock(side_effect=asyncio.CancelledError)
    mock_ex.watch_trades = AsyncMock(side_effect=asyncio.CancelledError)

    # Reconnect also fails
    mock_ex_fail = _mock_exchange()
    mock_ex_fail.load_markets = AsyncMock(side_effect=ConnectionError("still dead"))

    instances = iter([mock_ex, mock_ex_fail, mock_ex_fail])

    with patch.object(
        adapter, "_make_exchange", side_effect=lambda: next(instances)
    ):
        await adapter.connect()
        await adapter.subscribe_market_data(["BTC/USDT"])
        await asyncio.sleep(0.5)

    states = [e.state for e in events]
    assert states[-1] == "DISCONNECTED"


# ── 2. Message-to-event mapping ──────────────────────────────────


def test_ticker_mapping() -> None:
    ev = _ticker_to_event("BTC/USDT", SAMPLE_TICKER)
    assert isinstance(ev, TickEvent)
    assert ev.symbol == "BTC/USDT"
    assert ev.exchange == "binance"
    assert ev.bid_price == 42000.5
    assert ev.ask_price == 42001.0
    assert ev.last_price == 42000.75
    assert ev.bid_size == 1.2
    assert ev.ask_size == 0.8


def test_orderbook_mapping() -> None:
    ev = _orderbook_to_event("BTC/USDT", SAMPLE_ORDERBOOK)
    assert isinstance(ev, OrderBookEvent)
    assert ev.bids == [[42000.0, 1.5], [41999.0, 2.0]]
    assert ev.asks == [[42001.0, 0.8], [42002.0, 1.1]]


def test_trade_mapping() -> None:
    ev = _trade_to_event("BTC/USDT", SAMPLE_TRADE)
    assert isinstance(ev, TradeEvent)
    assert ev.price == 42000.5
    assert ev.size == 0.25
    assert ev.trade_id == "t_123456"


# ── 3. Paper-mode guards & balances ─────────────────────────────


@pytest.mark.asyncio
async def test_place_order_paper_mode(bus: AsyncEventBus) -> None:
    adapter = BinanceAdapter(bus, mode="paper")
    mock_ex = _mock_exchange()

    with patch.object(adapter, "_make_exchange", return_value=mock_ex):
        await adapter.connect()

    order = OrderEvent(
        strategy_id="test",
        symbol="BTC/USDT",
        side="BUY",
        order_type="LIMIT",
        quantity=0.1,
        price=40000.0,
    )
    oid = await adapter.place_order(order)
    assert oid == "order_abc"
    mock_ex.create_order.assert_called_once()


@pytest.mark.asyncio
async def test_place_order_live_raises(bus: AsyncEventBus) -> None:
    adapter = BinanceAdapter(bus, mode="live")
    mock_ex = _mock_exchange()

    with patch.object(adapter, "_make_exchange", return_value=mock_ex):
        await adapter.connect()

    order = OrderEvent(
        strategy_id="test",
        symbol="BTC/USDT",
        side="BUY",
        order_type="MARKET",
        quantity=0.1,
    )
    with pytest.raises(NotImplementedError, match="Sprint 15"):
        await adapter.place_order(order)


@pytest.mark.asyncio
async def test_cancel_order_live_raises(bus: AsyncEventBus) -> None:
    adapter = BinanceAdapter(bus, mode="live")
    mock_ex = _mock_exchange()

    with patch.object(adapter, "_make_exchange", return_value=mock_ex):
        await adapter.connect()

    with pytest.raises(NotImplementedError, match="Sprint 15"):
        await adapter.cancel_order("some_id")


@pytest.mark.asyncio
async def test_get_balances(bus: AsyncEventBus) -> None:
    adapter = BinanceAdapter(bus, mode="paper")
    mock_ex = _mock_exchange()

    with patch.object(adapter, "_make_exchange", return_value=mock_ex):
        await adapter.connect()

    bals = await adapter.get_balances()
    assert bals == {"BTC": 0.5, "USDT": 10000.0}
    mock_ex.fetch_balance.assert_called_once()

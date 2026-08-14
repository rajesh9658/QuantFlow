"""Tests for MarketDataEngine: passthrough, rejection, sequence, burst."""

from __future__ import annotations

import asyncio
import random

import pytest

from quantflow.common.events import OrderBookEvent, TickEvent, TradeEvent
from quantflow.core.event_bus import AsyncEventBus
from quantflow.market_data.engine import MarketDataEngine


@pytest.fixture
def bus() -> AsyncEventBus:
    return AsyncEventBus()


@pytest.fixture
def engine(bus: AsyncEventBus) -> MarketDataEngine:
    return MarketDataEngine(bus)


# ── helpers ──────────────────────────────────────────────────────

def _ticker_raw(
    bid: float = 100.0,
    ask: float = 101.0,
    last: float = 100.5,
    volume: float = 500.0,
) -> dict:
    return {"bid": bid, "ask": ask, "last": last, "volume": volume}


def _orderbook_raw(
    bids: list | None = None,
    asks: list | None = None,
    u: int | None = None,
    pu: int | None = None,
) -> dict:
    raw: dict = {
        "bids": bids if bids is not None else [[100.0, 1.0]],
        "asks": asks if asks is not None else [[101.0, 1.0]],
    }
    if u is not None:
        raw["u"] = u
    if pu is not None:
        raw["pu"] = pu
    return raw


def _trade_raw(price: float = 100.0, size: float = 0.5) -> dict:
    return {"price": price, "size": size, "trade_id": "t1"}


# ── 1. Valid messages pass through unchanged in structure ────────


@pytest.mark.asyncio
async def test_valid_ticker_published(bus: AsyncEventBus, engine: MarketDataEngine) -> None:
    q = await bus.subscribe_queue(TickEvent, maxsize=10)
    await engine.process_ticker("BTC/USDT", _ticker_raw())
    ev = await asyncio.wait_for(q.get(), timeout=1)
    assert isinstance(ev, TickEvent)
    assert ev.symbol == "BTC/USDT"
    assert ev.bid_price == 100.0
    assert ev.ask_price == 101.0
    assert ev.last_price == 100.5


@pytest.mark.asyncio
async def test_valid_orderbook_published(bus: AsyncEventBus, engine: MarketDataEngine) -> None:
    q = await bus.subscribe_queue(OrderBookEvent, maxsize=10)
    await engine.process_orderbook("BTC/USDT", _orderbook_raw())
    ev = await asyncio.wait_for(q.get(), timeout=1)
    assert isinstance(ev, OrderBookEvent)
    assert ev.bids == [[100.0, 1.0]]
    assert ev.asks == [[101.0, 1.0]]


@pytest.mark.asyncio
async def test_valid_trade_published(bus: AsyncEventBus, engine: MarketDataEngine) -> None:
    q = await bus.subscribe_queue(TradeEvent, maxsize=10)
    await engine.process_trade("BTC/USDT", _trade_raw())
    ev = await asyncio.wait_for(q.get(), timeout=1)
    assert isinstance(ev, TradeEvent)
    assert ev.price == 100.0
    assert ev.size == 0.5
    assert ev.trade_id == "t1"


# ── 2. Out-of-order / duplicate sequence dropped ────────────────


@pytest.mark.asyncio
async def test_stale_sequence_dropped(
    bus: AsyncEventBus, engine: MarketDataEngine
) -> None:
    q = await bus.subscribe_queue(OrderBookEvent, maxsize=10)

    # u=5 accepted (first)
    await engine.process_orderbook("BTC/USDT", _orderbook_raw(u=5, pu=None))
    # u=3 stale → dropped
    await engine.process_orderbook("BTC/USDT", _orderbook_raw(u=3, pu=5))
    # u=5 duplicate → dropped
    await engine.process_orderbook("BTC/USDT", _orderbook_raw(u=5, pu=5))
    # u=6 clean → accepted
    await engine.process_orderbook("BTC/USDT", _orderbook_raw(u=6, pu=5))

    ev1 = await asyncio.wait_for(q.get(), timeout=1)
    ev2 = await asyncio.wait_for(q.get(), timeout=1)
    assert ev1.symbol == "BTC/USDT"
    assert ev2.symbol == "BTC/USDT"
    # Only 2 events should have been published
    assert q.empty()


@pytest.mark.asyncio
async def test_sequence_gap_triggers_resync(
    bus: AsyncEventBus, engine: MarketDataEngine
) -> None:
    """pu doesn't match last_u → dropped + snapshot callback invoked."""
    resync_calls: list[str] = []

    async def snapshot_cb(symbol: str) -> None:
        resync_calls.append(symbol)

    engine.register_snapshot_callback("BTC/USDT", snapshot_cb)
    q = await bus.subscribe_queue(OrderBookEvent, maxsize=10)

    await engine.process_orderbook("BTC/USDT", _orderbook_raw(u=10, pu=None))
    # gap: pu=15 but last_u=10
    await engine.process_orderbook("BTC/USDT", _orderbook_raw(u=20, pu=15))

    # Only first event published
    ev = await asyncio.wait_for(q.get(), timeout=1)
    assert ev.symbol == "BTC/USDT"
    assert q.empty()
    # Snapshot callback was called
    assert resync_calls == ["BTC/USDT"]


# ── 3. Negative price / size rejected ────────────────────────────


@pytest.mark.asyncio
async def test_negative_price_ticker_rejected(
    bus: AsyncEventBus, engine: MarketDataEngine
) -> None:
    q = await bus.subscribe_queue(TickEvent, maxsize=10)
    await engine.process_ticker("BTC/USDT", _ticker_raw(bid=-1.0))
    assert q.empty()


@pytest.mark.asyncio
async def test_zero_price_ticker_rejected(
    bus: AsyncEventBus, engine: MarketDataEngine
) -> None:
    q = await bus.subscribe_queue(TickEvent, maxsize=10)
    await engine.process_ticker("BTC/USDT", _ticker_raw(last=0.0))
    assert q.empty()


@pytest.mark.asyncio
async def test_negative_price_trade_rejected(
    bus: AsyncEventBus, engine: MarketDataEngine
) -> None:
    q = await bus.subscribe_queue(TradeEvent, maxsize=10)
    await engine.process_trade("BTC/USDT", _trade_raw(price=-5.0))
    assert q.empty()


@pytest.mark.asyncio
async def test_negative_size_trade_rejected(
    bus: AsyncEventBus, engine: MarketDataEngine
) -> None:
    q = await bus.subscribe_queue(TradeEvent, maxsize=10)
    await engine.process_trade("BTC/USDT", _trade_raw(size=-1.0))
    assert q.empty()


@pytest.mark.asyncio
async def test_negative_price_orderbook_rejected(
    bus: AsyncEventBus, engine: MarketDataEngine
) -> None:
    q = await bus.subscribe_queue(OrderBookEvent, maxsize=10)
    await engine.process_orderbook(
        "BTC/USDT", _orderbook_raw(bids=[[-1.0, 1.0]])
    )
    assert q.empty()


@pytest.mark.asyncio
async def test_empty_orderbook_rejected(
    bus: AsyncEventBus, engine: MarketDataEngine
) -> None:
    q = await bus.subscribe_queue(OrderBookEvent, maxsize=10)
    await engine.process_orderbook("BTC/USDT", _orderbook_raw(bids=[], asks=[]))
    assert q.empty()


@pytest.mark.asyncio
async def test_bad_symbol_rejected(
    bus: AsyncEventBus, engine: MarketDataEngine
) -> None:
    q_tick = await bus.subscribe_queue(TickEvent, maxsize=10)
    q_trade = await bus.subscribe_queue(TradeEvent, maxsize=10)
    await engine.process_ticker("btc-usdt", _ticker_raw())  # lowercase
    await engine.process_trade("", _trade_raw())  # empty
    assert q_tick.empty()
    assert q_trade.empty()


# ── 4. Burst of 1000 ticks across symbols — no cross-symbol leak ─


@pytest.mark.asyncio
async def test_burst_1000_ticks_per_symbol(
    bus: AsyncEventBus, engine: MarketDataEngine
) -> None:
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT"]
    ticks_per_symbol = 250  # 250 × 4 = 1000

    queues: dict[str, asyncio.Queue[TickEvent]] = {}
    # subscribe per-symbol by using a single queue and filtering
    q = await bus.subscribe_queue(TickEvent, maxsize=1200)

    # Build all raw messages with identifiable prices
    messages: list[tuple[str, dict]] = []
    for sym_idx, sym in enumerate(symbols):
        for i in range(ticks_per_symbol):
            # price encodes symbol index and tick number
            price = float(1000 * (sym_idx + 1) + i)
            messages.append((sym, _ticker_raw(bid=price, ask=price + 1, last=price + 0.5)))

    # Shuffle to randomize order
    random.shuffle(messages)

    # Process all
    for sym, raw in messages:
        await engine.process_ticker(sym, raw)

    # Drain queue and bucket by symbol
    received: dict[str, list[TickEvent]] = {s: [] for s in symbols}
    while not q.empty():
        ev = q.get_nowait()
        received[ev.symbol].append(ev)

    # Each symbol got exactly its ticks
    for sym in symbols:
        assert len(received[sym]) == ticks_per_symbol, (
            f"{sym}: expected {ticks_per_symbol}, got {len(received[sym])}"
        )

    # Verify no cross-symbol contamination: each symbol's prices
    # fall in its expected range
    for sym_idx, sym in enumerate(symbols):
        base = 1000 * (sym_idx + 1)
        for ev in received[sym]:
            assert base <= ev.bid_price < base + ticks_per_symbol, (
                f"{sym}: unexpected bid_price {ev.bid_price}"
            )

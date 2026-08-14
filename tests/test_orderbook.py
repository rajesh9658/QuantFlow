"""Tests for LocalOrderBook: snapshot, diff, gap resync, property-based."""

from __future__ import annotations

import asyncio
import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from quantflow.market_data.orderbook import LocalOrderBook


# ── helpers ──────────────────────────────────────────────────────


def _snap(
    bids: list[list[float]] | None = None,
    asks: list[list[float]] | None = None,
    uid: int = 100,
) -> tuple[list[list[float]], list[list[float]], int]:
    return (
        bids if bids is not None else [[100.0, 1.0], [99.0, 2.0], [98.0, 3.0]],
        asks if asks is not None else [[101.0, 1.5], [102.0, 2.5], [103.0, 3.5]],
        uid,
    )


# ── 1. Snapshot correctly initializes ────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_initializes_book() -> None:
    book = LocalOrderBook("BTC/USDT")
    assert not book.initialized
    assert book.best_bid() is None

    bids, asks, uid = _snap()
    await book.apply_snapshot(bids, asks, uid)

    assert book.initialized
    assert book.best_bid() == (100.0, 1.0)
    assert book.best_ask() == (101.0, 1.5)


@pytest.mark.asyncio
async def test_snapshot_overwrites_previous() -> None:
    book = LocalOrderBook("BTC/USDT")
    await book.apply_snapshot(*_snap(uid=100))
    assert book.best_bid() == (100.0, 1.0)

    # New snapshot with different prices
    await book.apply_snapshot([[200.0, 5.0]], [[201.0, 6.0]], 200)
    assert book.best_bid() == (200.0, 5.0)
    assert book.best_ask() == (201.0, 6.0)
    # Old levels gone
    b, a = book.depth(10)
    assert len(b) == 1
    assert len(a) == 1


# ── 2. Sequential diffs apply correctly ──────────────────────────


@pytest.mark.asyncio
async def test_sequential_diffs() -> None:
    book = LocalOrderBook("BTC/USDT")
    await book.apply_snapshot(*_snap(uid=100))

    # Update existing level size
    ok = await book.apply_diff([[100.0, 10.0]], [], u=101, pu=100)
    assert ok
    assert book.best_bid() == (100.0, 10.0)

    # Add new higher bid
    ok = await book.apply_diff([[105.0, 0.5]], [], u=102, pu=101)
    assert ok
    assert book.best_bid() == (105.0, 0.5)

    # Delete a level (size=0)
    ok = await book.apply_diff([[105.0, 0.0]], [], u=103, pu=102)
    assert ok
    assert book.best_bid() == (100.0, 10.0)

    # Update ask side
    ok = await book.apply_diff([], [[100.5, 0.2]], u=104, pu=103)
    assert ok
    assert book.best_ask() == (100.5, 0.2)


@pytest.mark.asyncio
async def test_stale_diff_dropped() -> None:
    book = LocalOrderBook("BTC/USDT")
    await book.apply_snapshot(*_snap(uid=100))

    ok = await book.apply_diff([[99.0, 50.0]], [], u=99, pu=98)
    assert not ok
    # Original value unchanged
    b, _ = book.depth(10)
    assert any(p == 99.0 and s == 2.0 for p, s in b)


# ── 3. Sequence gap → resync ────────────────────────────────────


@pytest.mark.asyncio
async def test_gap_triggers_resync() -> None:
    resync_calls: list[str] = []

    async def on_resync(symbol: str) -> None:
        resync_calls.append(symbol)

    book = LocalOrderBook("ETH/USDT", snapshot_callback=on_resync)
    await book.apply_snapshot(*_snap(uid=100))

    # Gap: pu=150 but last_u=100
    ok = await book.apply_diff([[99.0, 5.0]], [], u=200, pu=150)
    assert not ok
    assert resync_calls == ["ETH/USDT"]
    # Book is now un-initialized (stale state discarded)
    assert not book.initialized


@pytest.mark.asyncio
async def test_diffs_rejected_until_new_snapshot() -> None:
    """After a gap, subsequent diffs are rejected until a fresh snapshot."""
    resync_calls: list[str] = []

    async def on_resync(symbol: str) -> None:
        resync_calls.append(symbol)

    book = LocalOrderBook("ETH/USDT", snapshot_callback=on_resync)
    await book.apply_snapshot(*_snap(uid=100))

    # Trigger gap
    await book.apply_diff([], [], u=200, pu=150)
    assert not book.initialized

    # Further diffs should all fail
    ok = await book.apply_diff([], [], u=201, pu=200)
    assert not ok

    # Apply fresh snapshot → back in business
    await book.apply_snapshot([[50.0, 1.0]], [[51.0, 1.0]], 300)
    assert book.initialized
    ok = await book.apply_diff([[50.0, 2.0]], [], u=301, pu=300)
    assert ok
    assert book.best_bid() == (50.0, 2.0)


@pytest.mark.asyncio
async def test_uninitialized_diff_triggers_resync() -> None:
    resync_calls: list[str] = []

    async def on_resync(symbol: str) -> None:
        resync_calls.append(symbol)

    book = LocalOrderBook("SOL/USDT", snapshot_callback=on_resync)
    ok = await book.apply_diff([[10.0, 1.0]], [], u=5, pu=4)
    assert not ok
    assert resync_calls == ["SOL/USDT"]


# ── 4. best_bid/best_ask/depth under randomized sequences ───────


@pytest.mark.asyncio
async def test_depth_returns_sorted() -> None:
    book = LocalOrderBook("BTC/USDT")
    prices = list(range(90, 100))
    random.shuffle(prices)
    bids = [[float(p), float(p % 5 + 1)] for p in prices]
    asks = [[float(p + 10), float(p % 3 + 1)] for p in prices]
    await book.apply_snapshot(bids, asks, 1)

    b, a = book.depth(5)
    # Bids descending
    assert [p for p, _ in b] == sorted([p for p, _ in b], reverse=True)
    # Asks ascending
    assert [p for p, _ in a] == sorted([p for p, _ in a])
    assert len(b) <= 5
    assert len(a) <= 5


@pytest.mark.asyncio
async def test_mid_and_spread() -> None:
    book = LocalOrderBook("BTC/USDT")
    await book.apply_snapshot([[100.0, 1.0]], [[102.0, 1.0]], 1)
    assert book.mid_price() == 101.0
    assert book.spread() == 2.0


# ── 5. Property-based (hypothesis) ──────────────────────────────

# Strategy: generate a snapshot of K levels, then N random diffs
_price_st = st.floats(min_value=0.01, max_value=100000.0, allow_nan=False, allow_infinity=False)
_size_st = st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False)
_level_st = st.tuples(_price_st, _size_st).map(lambda t: [round(t[0], 2), round(t[1], 4)])


@given(
    bid_levels=st.lists(_level_st, min_size=1, max_size=50),
    ask_levels=st.lists(_level_st, min_size=1, max_size=50),
    diff_ops=st.lists(
        st.tuples(
            st.sampled_from(["bid", "ask"]),
            _price_st.map(lambda x: round(x, 2)),
            st.one_of(st.just(0.0), _size_st.map(lambda x: round(x, 4))),
        ),
        min_size=0,
        max_size=100,
    ),
)
@settings(max_examples=50, deadline=2000)
@pytest.mark.asyncio
async def test_property_depth_invariants(
    bid_levels: list[list[float]],
    ask_levels: list[list[float]],
    diff_ops: list[tuple[str, float, float]],
) -> None:
    """After any sequence of valid ops, depth(n) returns sorted, positive-size levels."""
    book = LocalOrderBook("PROP/TEST")
    await book.apply_snapshot(bid_levels, ask_levels, 0)

    seq = 0
    for side, price, size in diff_ops:
        seq += 1
        b_diff = [[price, size]] if side == "bid" else []
        a_diff = [[price, size]] if side == "ask" else []
        await book.apply_diff(b_diff, a_diff, u=seq, pu=seq - 1)

    bids, asks = book.depth(100)

    # All sizes > 0
    for _, s in bids:
        assert s > 0
    for _, s in asks:
        assert s > 0

    # Bids descending
    bid_prices = [p for p, _ in bids]
    assert bid_prices == sorted(bid_prices, reverse=True)

    # Asks ascending
    ask_prices = [p for p, _ in asks]
    assert ask_prices == sorted(ask_prices)

    # best_bid/ask consistent with depth
    if bids:
        bb = book.best_bid()
        assert bb is not None
        assert bb[0] == bids[0][0]
    if asks:
        ba = book.best_ask()
        assert ba is not None
        assert ba[0] == asks[0][0]

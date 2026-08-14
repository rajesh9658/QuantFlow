"""Unit tests for Paper Execution Engine and pure fill simulator."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from quantflow.common.events import (
    ApprovedSignalEvent,
    FillEvent,
    OrderEvent,
)
from quantflow.config.manager import ConfigManager
from quantflow.core.event_bus import AsyncEventBus
from quantflow.execution.fill_simulator import (
    FeeSchedule,
    simulate_fill,
)
from quantflow.execution.paper import PaperExecutionHandler
from quantflow.market_data.orderbook import LocalOrderBook

# ── 1. Pure Fill Simulator Tests ──────────────────────────────────


def test_market_order_walks_book_full_fill() -> None:
    """Market BUY order walks multiple ask levels to fill full quantity."""
    order = OrderEvent(
        strategy_id="test_strat",
        symbol="BTC/USDT",
        side="BUY",
        order_type="MARKET",
        quantity=3.0,
    )
    # Asks: 1.0 @ 100.0, 1.0 @ 101.0, 2.0 @ 102.0
    orderbook = {
        "bids": [[99.0, 10.0]],
        "asks": [[100.0, 1.0], [101.0, 1.0], [102.0, 2.0]],
    }
    fees = FeeSchedule(taker_rate=0.001, maker_rate=0.0005, flat_fee_per_order=0.0)
    ts = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)

    result = simulate_fill(order, orderbook, fees, timestamp=ts)

    assert result.remaining_quantity == 0.0
    assert len(result.fills) == 3

    # Level 1: 1.0 @ 100.0
    assert result.fills[0].quantity == 1.0
    assert result.fills[0].fill_price == 100.0
    assert result.fills[0].commission == pytest.approx(100.0 * 0.001)

    # Level 2: 1.0 @ 101.0
    assert result.fills[1].quantity == 1.0
    assert result.fills[1].fill_price == 101.0

    # Level 3: 1.0 @ 102.0 (out of 2.0 available)
    assert result.fills[2].quantity == 1.0
    assert result.fills[2].fill_price == 102.0

    # Total cost = 100 + 101 + 102 = 303.0; Avg price = 101.0
    assert result.total_cost == pytest.approx(303.0)
    assert result.avg_price == pytest.approx(101.0)
    assert result.total_commission == pytest.approx(303.0 * 0.001)


def test_order_larger_than_depth_partially_fills() -> None:
    """Order larger than available book depth executes partial fill."""
    order = OrderEvent(
        strategy_id="test_strat",
        symbol="BTC/USDT",
        side="BUY",
        order_type="MARKET",
        quantity=5.0,
    )
    # Total available ask liquidity = 1.0 + 2.0 = 3.0
    orderbook = {
        "bids": [[99.0, 5.0]],
        "asks": [[100.0, 1.0], [101.0, 2.0]],
    }
    fees = FeeSchedule(taker_rate=0.001, maker_rate=0.0005)
    ts = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)

    result = simulate_fill(order, orderbook, fees, timestamp=ts)

    # Remaining quantity should be 5.0 - 3.0 = 2.0
    assert result.remaining_quantity == pytest.approx(2.0)
    assert len(result.fills) == 2

    # Filled 3.0 units total: 1.0 @ 100.0 + 2.0 @ 101.0 = 302.0 cost
    assert result.total_cost == pytest.approx(302.0)
    assert result.avg_price == pytest.approx(302.0 / 3.0)


def test_limit_order_respects_price_cap() -> None:
    """Limit BUY order only consumes levels at or below limit_price."""
    order = OrderEvent(
        strategy_id="test_strat",
        symbol="ETH/USDT",
        side="BUY",
        order_type="LIMIT",
        quantity=3.0,
        price=100.5,
    )
    # Asks: 100.0 (<= 100.5), 101.0 (> 100.5), 102.0 (> 100.5)
    orderbook = {
        "bids": [[99.0, 10.0]],
        "asks": [[100.0, 1.0], [101.0, 2.0], [102.0, 2.0]],
    }
    fees = FeeSchedule(taker_rate=0.001, maker_rate=0.0005)

    result = simulate_fill(order, orderbook, fees)

    # Only 1.0 @ 100.0 filled, remaining 2.0 unfilled
    assert result.remaining_quantity == pytest.approx(2.0)
    assert len(result.fills) == 1
    assert result.fills[0].fill_price == 100.0
    assert result.fills[0].quantity == 1.0


def test_sell_order_walks_bids() -> None:
    """Market SELL order consumes bids descending."""
    order = OrderEvent(
        strategy_id="test_strat",
        symbol="BTC/USDT",
        side="SELL",
        order_type="MARKET",
        quantity=2.0,
    )
    # Bids: 1.0 @ 100.0, 2.0 @ 99.0, 5.0 @ 98.0
    orderbook = {
        "bids": [[100.0, 1.0], [99.0, 2.0], [98.0, 5.0]],
        "asks": [[101.0, 5.0]],
    }
    fees = FeeSchedule(taker_rate=0.001)

    result = simulate_fill(order, orderbook, fees)

    assert result.remaining_quantity == 0.0
    assert len(result.fills) == 2
    assert result.fills[0].fill_price == 100.0
    assert result.fills[0].quantity == 1.0
    assert result.fills[1].fill_price == 99.0
    assert result.fills[1].quantity == 1.0
    # Total cost = 100 + 99 = 199; avg_price = 99.5
    assert result.avg_price == pytest.approx(99.5)


def test_fee_schedule_calculation_and_config() -> None:
    """Verify FeeSchedule calculation logic and ConfigManager loading."""
    fees = FeeSchedule(taker_rate=0.002, maker_rate=0.001, flat_fee_per_order=2.5)

    notional = 10000.0
    assert fees.calculate_fee(notional, is_maker=False) == (10000.0 * 0.002) + 2.5
    assert fees.calculate_fee(notional, is_maker=True) == (10000.0 * 0.001) + 2.5

    config = ConfigManager(
        defaults={
            "execution": {
                "paper": {
                    "fees": {
                        "default": {"taker": 0.0015, "maker": 0.0008, "flat": 1.0},
                        "symbols": {
                            "BTC/USDT": {"taker": 0.0004, "maker": 0.0002, "flat": 0.0}
                        },
                    }
                }
            }
        }
    )

    # Symbol-specific override
    btc_fees = FeeSchedule.from_config(config, "BTC/USDT")
    assert btc_fees.taker_rate == 0.0004
    assert btc_fees.maker_rate == 0.0002
    assert btc_fees.flat_fee_per_order == 0.0

    # Default fallback for unlisted symbol
    eth_fees = FeeSchedule.from_config(config, "ETH/USDT")
    assert eth_fees.taker_rate == 0.0015
    assert eth_fees.maker_rate == 0.0008
    assert eth_fees.flat_fee_per_order == 1.0


def test_simulate_fill_is_deterministic() -> None:
    """Calling simulate_fill twice with identical inputs produces identical results."""
    order = OrderEvent(
        order_id="deterministic_order_1",
        strategy_id="test_strat",
        symbol="BTC/USDT",
        side="BUY",
        order_type="MARKET",
        quantity=2.5,
    )
    orderbook = {
        "bids": [[99.0, 10.0]],
        "asks": [[100.0, 1.0], [101.0, 2.0], [102.0, 3.0]],
    }
    fees = FeeSchedule(taker_rate=0.001, maker_rate=0.0005, flat_fee_per_order=0.5)
    ts = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)

    res1 = simulate_fill(order, orderbook, fees, timestamp=ts)
    res2 = simulate_fill(order, orderbook, fees, timestamp=ts)

    assert res1.remaining_quantity == res2.remaining_quantity
    assert res1.total_cost == res2.total_cost
    assert res1.total_commission == res2.total_commission
    assert res1.avg_price == res2.avg_price
    assert len(res1.fills) == len(res2.fills)

    for f1, f2 in zip(res1.fills, res2.fills, strict=True):
        assert f1.fill_id == f2.fill_id
        assert f1.quantity == f2.quantity
        assert f1.fill_price == f2.fill_price
        assert f1.commission == f2.commission
        assert f1.timestamp == f2.timestamp


# ── 2. PaperExecutionHandler Integration Tests ────────────────────


@pytest.mark.asyncio
async def test_paper_execution_handler_full_fill() -> None:
    """Test PaperExecutionHandler executes order against LocalOrderBook."""
    bus = AsyncEventBus()
    book = LocalOrderBook("BTC/USDT")
    await book.apply_snapshot(
        bids=[[99.0, 5.0]],
        asks=[[100.0, 1.0], [101.0, 2.0]],
        update_id=1,
    )

    handler = PaperExecutionHandler(
        event_bus=bus, order_books={"BTC/USDT": book}
    )
    await handler.start()

    published_fills: list[FillEvent] = []

    async def on_fill(f: FillEvent) -> None:
        published_fills.append(f)

    await bus.subscribe(FillEvent, on_fill)

    order = OrderEvent(
        order_id="order_101",
        strategy_id="strat_a",
        symbol="BTC/USDT",
        side="BUY",
        order_type="MARKET",
        quantity=1.0,
    )
    await handler.submit_order(order)
    await asyncio.sleep(0.05)

    assert handler.get_order_status("order_101") == "FILLED"
    assert len(published_fills) == 1
    assert published_fills[0].order_id == "order_101"
    assert published_fills[0].fill_price == 100.0
    assert published_fills[0].quantity == 1.0

    await handler.stop()


@pytest.mark.asyncio
async def test_paper_execution_handler_handles_approved_signal() -> None:
    """Test handler subscribes to ApprovedSignalEvent and submits order."""
    bus = AsyncEventBus()
    book = LocalOrderBook("ETH/USDT")
    await book.apply_snapshot(
        bids=[[2000.0, 10.0]],
        asks=[[2005.0, 5.0]],
        update_id=1,
    )

    handler = PaperExecutionHandler(
        event_bus=bus, order_books={"ETH/USDT": book}
    )
    await handler.start()

    published_fills: list[FillEvent] = []

    async def on_fill(f: FillEvent) -> None:
        published_fills.append(f)

    await bus.subscribe(FillEvent, on_fill)

    sig = ApprovedSignalEvent(
        signal_id="sig_1",
        strategy_id="momentum",
        symbol="ETH/USDT",
        side="BUY",
        quantity=2.0,
        price=None,
    )
    await bus.publish(sig)
    await asyncio.sleep(0.05)

    assert len(published_fills) == 1
    assert published_fills[0].symbol == "ETH/USDT"
    assert published_fills[0].quantity == 2.0
    assert published_fills[0].fill_price == 2005.0

    await handler.stop()


@pytest.mark.asyncio
async def test_paper_execution_handler_partial_fill_and_cancel() -> None:
    """Partial fill leaves order open/pending; cancel_order removes it."""
    bus = AsyncEventBus()
    book = LocalOrderBook("SOL/USDT")
    await book.apply_snapshot(
        bids=[[150.0, 10.0]],
        asks=[[155.0, 1.0]],  # Only 1.0 available
        update_id=1,
    )

    handler = PaperExecutionHandler(
        event_bus=bus, order_books={"SOL/USDT": book}
    )
    await handler.start()

    order = OrderEvent(
        order_id="sol_order_1",
        strategy_id="strat_s",
        symbol="SOL/USDT",
        side="BUY",
        order_type="MARKET",
        quantity=3.0,
    )
    await handler.submit_order(order)

    assert handler.get_order_status("sol_order_1") == "PARTIALLY_FILLED"
    open_orders = handler.get_open_orders()
    assert len(open_orders) == 1
    assert open_orders[0]["id"] == "sol_order_1"

    # Cancel open order
    await handler.cancel_order("sol_order_1")
    assert handler.get_order_status("sol_order_1") == "CANCELLED"
    assert len(handler.get_open_orders()) == 0

    await handler.stop()

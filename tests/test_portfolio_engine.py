"""Unit tests for PortfolioEngine, PositionState, and financial state tracking."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from quantflow.common.events import FillEvent, PortfolioUpdateEvent
from quantflow.core.event_bus import AsyncEventBus
from quantflow.portfolio.engine import PortfolioEngine

# ── 1. Single Fill Tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_buy_fill_updates_cash_and_position() -> None:
    """Single BUY fill debits cash (cost + fee) and opens long position."""
    bus = AsyncEventBus()
    engine = PortfolioEngine(event_bus=bus, initial_cash=100000.0)
    await engine.start()

    fill = FillEvent(
        fill_id="f1",
        order_id="o1",
        symbol="BTC/USDT",
        side="BUY",
        quantity=2.0,
        fill_price=50000.0,
        commission=15.0,
        timestamp=datetime.now(UTC),
    )

    await bus.publish(fill)
    await asyncio.sleep(0.05)

    # Cash = 100000 - (2 * 50000 + 15) = -15
    assert engine.get_cash() == pytest.approx(-15.0)

    pos = engine.get_position("BTC/USDT")
    assert pos is not None
    assert pos.quantity == 2.0
    assert pos.avg_entry_price == 50000.0
    assert pos.total_cost_basis() == 100000.0
    assert not pos.is_empty()

    assert engine.get_positions() == {"BTC/USDT": 2.0}
    assert engine.get_realized_pnl() == 0.0

    await engine.stop()


@pytest.mark.asyncio
async def test_single_sell_short_fill_updates_cash_and_position() -> None:
    """Single SELL fill from flat credits cash and opens short position."""
    bus = AsyncEventBus()
    engine = PortfolioEngine(event_bus=bus, initial_cash=50000.0)
    await engine.start()

    fill = FillEvent(
        fill_id="f_short_1",
        order_id="o_short_1",
        symbol="ETH/USDT",
        side="SELL",
        quantity=10.0,
        fill_price=3000.0,
        commission=30.0,
        timestamp=datetime.now(UTC),
    )

    await bus.publish(fill)
    await asyncio.sleep(0.05)

    # Cash = 50000 + (10 * 3000 - 30) = 79970
    assert engine.get_cash() == pytest.approx(79970.0)

    pos = engine.get_position("ETH/USDT")
    assert pos is not None
    assert pos.quantity == -10.0
    assert pos.avg_entry_price == 3000.0
    assert engine.get_positions() == {"ETH/USDT": -10.0}

    await engine.stop()


# ── 2. Sequential Position Additions (WAC) ────────────────────────


@pytest.mark.asyncio
async def test_adding_to_position_recomputes_weighted_average_entry() -> None:
    """3 sequential BUY fills at different prices compute exact WAC entry."""
    bus = AsyncEventBus()
    engine = PortfolioEngine(event_bus=bus, initial_cash=500000.0)
    await engine.start()

    # Fill 1: 1.0 @ 100.0
    await bus.publish(
        FillEvent(
            order_id="o1",
            symbol="BTC/USDT",
            side="BUY",
            quantity=1.0,
            fill_price=100.0,
            commission=0.0,
        )
    )
    await asyncio.sleep(0.02)
    pos1 = engine.get_position("BTC/USDT")
    assert pos1 is not None
    assert pos1.quantity == 1.0
    assert pos1.avg_entry_price == 100.0

    # Fill 2: 2.0 @ 110.0 (total = 1*100 + 2*110 = 320; qty = 3.0; avg = 320/3)
    await bus.publish(
        FillEvent(
            order_id="o2",
            symbol="BTC/USDT",
            side="BUY",
            quantity=2.0,
            fill_price=110.0,
            commission=0.0,
        )
    )
    await asyncio.sleep(0.02)
    pos2 = engine.get_position("BTC/USDT")
    assert pos2 is not None
    assert pos2.quantity == 3.0
    assert pos2.avg_entry_price == pytest.approx(320.0 / 3.0)

    # Fill 3: 1.0 @ 120.0 (total = 320 + 1*120 = 440; qty = 4.0; avg = 110.0)
    await bus.publish(
        FillEvent(
            order_id="o3",
            symbol="BTC/USDT",
            side="BUY",
            quantity=1.0,
            fill_price=120.0,
            commission=0.0,
        )
    )
    await asyncio.sleep(0.02)
    pos3 = engine.get_position("BTC/USDT")
    assert pos3 is not None
    assert pos3.quantity == 4.0
    assert pos3.avg_entry_price == pytest.approx(110.0)

    # Fill 4: 6.0 @ 100.0 (total = 440 + 6*100 = 1040; qty = 10.0; avg = 104.0)
    await bus.publish(
        FillEvent(
            order_id="o4",
            symbol="BTC/USDT",
            side="BUY",
            quantity=6.0,
            fill_price=100.0,
            commission=0.0,
        )
    )
    await asyncio.sleep(0.02)
    pos4 = engine.get_position("BTC/USDT")
    assert pos4 is not None
    assert pos4.quantity == 10.0
    assert pos4.avg_entry_price == pytest.approx(104.0)

    await engine.stop()


@pytest.mark.asyncio
async def test_adding_to_short_position_recomputes_wac_entry() -> None:
    """3 sequential SELL fills to build a short position compute exact WAC."""
    bus = AsyncEventBus()
    engine = PortfolioEngine(event_bus=bus, initial_cash=100000.0)
    await engine.start()

    # Short 1: 1.0 @ 200.0
    await bus.publish(
        FillEvent(
            order_id="s1",
            symbol="SOL/USDT",
            side="SELL",
            quantity=1.0,
            fill_price=200.0,
        )
    )
    # Short 2: 2.0 @ 170.0 (total = 1*200 + 2*170 = 540; qty = -3; avg = 180.0)
    await bus.publish(
        FillEvent(
            order_id="s2",
            symbol="SOL/USDT",
            side="SELL",
            quantity=2.0,
            fill_price=170.0,
        )
    )
    # Short 3: 1.0 @ 140.0 (total = 540 + 1*140 = 680; qty = -4; avg = 170.0)
    await bus.publish(
        FillEvent(
            order_id="s3",
            symbol="SOL/USDT",
            side="SELL",
            quantity=1.0,
            fill_price=140.0,
        )
    )
    await asyncio.sleep(0.05)

    pos = engine.get_position("SOL/USDT")
    assert pos is not None
    assert pos.quantity == -4.0
    assert pos.avg_entry_price == pytest.approx(170.0)

    await engine.stop()


# ── 3. Position Reductions, Full Closes, and Flips ────────────────


@pytest.mark.asyncio
async def test_partial_reduction_and_full_close_computes_realized_pnl() -> None:
    """Partial reduction realizes PnL & preserves avg; close clears position."""
    bus = AsyncEventBus()
    engine = PortfolioEngine(event_bus=bus, initial_cash=100000.0)
    await engine.start()

    # 1. Buy 2.0 BTC @ 50,000 (commission 10.0)
    await bus.publish(
        FillEvent(
            order_id="buy1",
            symbol="BTC/USDT",
            side="BUY",
            quantity=2.0,
            fill_price=50000.0,
            commission=10.0,
        )
    )
    await asyncio.sleep(0.02)
    assert engine.get_cash() == pytest.approx(-10.0)

    # 2. Sell 1.0 BTC @ 55,000 -> Realized PnL = (55000 - 50000) * 1.0 = +5000.0
    await bus.publish(
        FillEvent(
            order_id="sell1",
            symbol="BTC/USDT",
            side="SELL",
            quantity=1.0,
            fill_price=55000.0,
            commission=5.0,
        )
    )
    await asyncio.sleep(0.02)

    # Cash = -10 + (55000 - 5) = 54985.0
    assert engine.get_cash() == pytest.approx(54985.0)
    assert engine.get_realized_pnl() == pytest.approx(5000.0)

    # Remaining position is 1.0 @ 50,000 (avg entry price unchanged)
    pos = engine.get_position("BTC/USDT")
    assert pos is not None
    assert pos.quantity == 1.0
    assert pos.avg_entry_price == 50000.0

    # 3. Sell remaining 1.0 BTC @ 60,000 -> Realized PnL = +10000.0
    await bus.publish(
        FillEvent(
            order_id="sell2",
            symbol="BTC/USDT",
            side="SELL",
            quantity=1.0,
            fill_price=60000.0,
            commission=6.0,
        )
    )
    await asyncio.sleep(0.02)

    # Cumulative Realized PnL = 5000 + 10000 = 15000.0
    assert engine.get_realized_pnl() == pytest.approx(15000.0)
    # Cash = 54985 + (60000 - 6) = 114979.0 (Net gain: 15000 PnL - 21 total fees)
    assert engine.get_cash() == pytest.approx(114979.0)
    # Position is fully closed and removed
    assert engine.get_position("BTC/USDT") is None
    assert engine.get_positions() == {}

    await engine.stop()


@pytest.mark.asyncio
async def test_position_side_flip_long_to_short() -> None:
    """Selling more than current long flips position to short at the fill price."""
    bus = AsyncEventBus()
    engine = PortfolioEngine(event_bus=bus, initial_cash=100000.0)
    await engine.start()

    # Buy 1.0 BTC @ 50,000
    await bus.publish(
        FillEvent(
            order_id="b1",
            symbol="BTC/USDT",
            side="BUY",
            quantity=1.0,
            fill_price=50000.0,
            commission=0.0,
        )
    )
    await asyncio.sleep(0.02)

    # Sell 3.0 BTC @ 55,000 (closes 1.0 long with +5000 PnL, opens -2.0 short @ 55000)
    await bus.publish(
        FillEvent(
            order_id="s1",
            symbol="BTC/USDT",
            side="SELL",
            quantity=3.0,
            fill_price=55000.0,
            commission=0.0,
        )
    )
    await asyncio.sleep(0.02)

    assert engine.get_realized_pnl() == pytest.approx(5000.0)
    pos = engine.get_position("BTC/USDT")
    assert pos is not None
    assert pos.quantity == -2.0
    assert pos.avg_entry_price == 55000.0

    # Total equity = Cash (100k - 50k + 165k = 215k) + MTM (-2 * 55k = -110k) = 105k
    assert engine.get_cash() == pytest.approx(215000.0)
    assert engine.get_total_equity() == pytest.approx(105000.0)

    await engine.stop()


@pytest.mark.asyncio
async def test_short_position_reduction_and_close() -> None:
    """Short position reduction and close computes correct realized profit/loss."""
    bus = AsyncEventBus()
    engine = PortfolioEngine(event_bus=bus, initial_cash=100000.0)
    await engine.start()

    # Open short: Sell 2.0 ETH @ 3000.0 (Cash = 100k + 6k = 106k)
    await bus.publish(
        FillEvent(
            order_id="s1",
            symbol="ETH/USDT",
            side="SELL",
            quantity=2.0,
            fill_price=3000.0,
        )
    )
    await asyncio.sleep(0.02)

    # Buy to cover 1.0 ETH @ 2800.0 -> Profit = (3000 - 2800) * 1.0 = +200.0
    await bus.publish(
        FillEvent(
            order_id="b1",
            symbol="ETH/USDT",
            side="BUY",
            quantity=1.0,
            fill_price=2800.0,
        )
    )
    await asyncio.sleep(0.02)

    assert engine.get_realized_pnl() == pytest.approx(200.0)
    pos = engine.get_position("ETH/USDT")
    assert pos is not None
    assert pos.quantity == -1.0
    assert pos.avg_entry_price == 3000.0

    # Buy to cover remaining 1.0 ETH @ 3100.0 -> Loss = (3000 - 3100) * 1.0 = -100.0
    await bus.publish(
        FillEvent(
            order_id="b2",
            symbol="ETH/USDT",
            side="BUY",
            quantity=1.0,
            fill_price=3100.0,
        )
    )
    await asyncio.sleep(0.02)

    # Net realized PnL = 200 - 100 = +100.0
    assert engine.get_realized_pnl() == pytest.approx(100.0)
    assert engine.get_position("ETH/USDT") is None

    await engine.stop()


# ── 4. Mark-to-Market Unrealized PnL Updates ─────────────────────


@pytest.mark.asyncio
async def test_unrealized_pnl_updates_on_mark_price_change_without_new_fill() -> None:
    """Mark price changes update UPL and equity without any new fills."""
    bus = AsyncEventBus()
    engine = PortfolioEngine(event_bus=bus, initial_cash=100000.0)
    await engine.start()

    # Buy 2.0 BTC @ 50,000
    await bus.publish(
        FillEvent(
            order_id="f1",
            symbol="BTC/USDT",
            side="BUY",
            quantity=2.0,
            fill_price=50000.0,
        )
    )
    await asyncio.sleep(0.02)
    assert engine.get_cash() == 0.0

    # 1. Price moves to 55,000
    await engine.update_mark_price("BTC/USDT", 55000.0)
    # UPL = (55000 - 50000) * 2 = +10,000.0
    assert engine.get_unrealized_pnl() == pytest.approx(10000.0)
    # Total equity = Cash (0) + 2 * 55000 = 110,000.0
    assert engine.get_total_equity() == pytest.approx(110000.0)
    # Gross exposure = 2 * 55000 = 110,000.0
    assert engine.get_total_exposure() == pytest.approx(110000.0)

    # 2. Price drops to 45,000
    await engine.update_mark_price("BTC/USDT", 45000.0)
    # UPL = (45000 - 50000) * 2 = -10,000.0
    assert engine.get_unrealized_pnl() == pytest.approx(-10000.0)
    assert engine.get_total_equity() == pytest.approx(90000.0)
    assert engine.get_total_exposure() == pytest.approx(90000.0)

    await engine.stop()


@pytest.mark.asyncio
async def test_short_unrealized_pnl_updates_on_mark_price() -> None:
    """Short position UPL increases when price drops and decreases when price rises."""
    bus = AsyncEventBus()
    engine = PortfolioEngine(event_bus=bus, initial_cash=100000.0)
    await engine.start()

    # Short 5.0 ETH @ 3000.0
    await bus.publish(
        FillEvent(
            order_id="f_s1",
            symbol="ETH/USDT",
            side="SELL",
            quantity=5.0,
            fill_price=3000.0,
        )
    )
    await asyncio.sleep(0.02)

    # Mark price drops to 2800.0 -> UPL = (3000 - 2800) * 5.0 = +1000.0
    await engine.update_mark_price("ETH/USDT", 2800.0)
    assert engine.get_unrealized_pnl() == pytest.approx(1000.0)
    # Total equity = Cash (115k) + (-5 * 2800 = -14k) = 101,000.0
    assert engine.get_total_equity() == pytest.approx(101000.0)
    assert engine.get_total_exposure() == pytest.approx(14000.0)

    await engine.stop()


# ── 5. PortfolioUpdateEvent Exact Single Emission ────────────────


@pytest.mark.asyncio
async def test_portfolio_update_event_fires_exactly_once_per_state_change() -> None:
    """PortfolioUpdateEvent fires exactly once per fill or mark price change."""
    bus = AsyncEventBus()
    engine = PortfolioEngine(event_bus=bus, initial_cash=50000.0)

    published_events: list[PortfolioUpdateEvent] = []

    async def on_portfolio_update(event: PortfolioUpdateEvent) -> None:
        published_events.append(event)

    await bus.subscribe(PortfolioUpdateEvent, on_portfolio_update)
    await engine.start()

    # 1. First Fill
    await bus.publish(
        FillEvent(
            order_id="op1",
            symbol="BTC/USDT",
            side="BUY",
            quantity=1.0,
            fill_price=40000.0,
            commission=5.0,
        )
    )
    await asyncio.sleep(0.03)

    assert len(published_events) == 1
    ev1 = published_events[0]
    assert ev1.cash == pytest.approx(50000.0 - 40005.0)
    assert ev1.positions == {"BTC/USDT": 1.0}
    assert ev1.realized_pnl == 0.0

    # 2. Mark price update without fill
    await engine.update_mark_price("BTC/USDT", 42000.0)
    await asyncio.sleep(0.03)

    assert len(published_events) == 2
    ev2 = published_events[1]
    assert ev2.unrealized_pnl == pytest.approx(2000.0)
    assert ev2.total_value == pytest.approx(ev1.cash + 42000.0)

    # 3. Second Fill (Sell 1.0 @ 42000)
    await bus.publish(
        FillEvent(
            order_id="op2",
            symbol="BTC/USDT",
            side="SELL",
            quantity=1.0,
            fill_price=42000.0,
            commission=5.0,
        )
    )
    await asyncio.sleep(0.03)

    assert len(published_events) == 3
    ev3 = published_events[2]
    assert ev3.positions == {}
    assert ev3.realized_pnl == pytest.approx(2000.0)
    assert ev3.unrealized_pnl == 0.0

    await engine.stop()


# ── 6. Price Provider Integration & Synchronous API ──────────────


@pytest.mark.asyncio
async def test_price_provider_callable_integration() -> None:
    """Engine queries custom price_provider callback during valuation."""
    price_map = {"BTC/USDT": 52000.0, "ETH/USDT": 3100.0}

    async def mock_price_provider(symbol: str) -> float | None:
        return price_map.get(symbol)

    bus = AsyncEventBus()
    engine = PortfolioEngine(
        event_bus=bus, price_provider=mock_price_provider, initial_cash=100000.0
    )
    await engine.start()

    # Fill BTC @ 50,000 (provider will price it at 52,000)
    await bus.publish(
        FillEvent(
            order_id="pp1",
            symbol="BTC/USDT",
            side="BUY",
            quantity=1.0,
            fill_price=50000.0,
        )
    )
    await asyncio.sleep(0.03)

    assert engine.get_unrealized_pnl() == pytest.approx(2000.0)
    assert engine.get_total_equity() == pytest.approx(102000.0)

    # Change price map dynamically
    price_map["BTC/USDT"] = 54000.0
    await engine.update_mark_price("BTC/USDT", 54000.0)
    await asyncio.sleep(0.03)

    assert engine.get_unrealized_pnl() == pytest.approx(4000.0)
    assert engine.get_total_equity() == pytest.approx(104000.0)

    await engine.stop()


def test_synchronous_portfolio_manager_update_position() -> None:
    """PortfolioEngine satisfies synchronous PortfolioManager interface."""
    engine = PortfolioEngine(initial_cash=50000.0)

    fill1 = FillEvent(
        order_id="sync_1",
        symbol="ADA/USDT",
        side="BUY",
        quantity=1000.0,
        fill_price=0.50,
        commission=1.0,
    )
    engine.update_position(fill1)

    assert engine.get_cash() == pytest.approx(50000.0 - 501.0)
    assert engine.get_positions() == {"ADA/USDT": 1000.0}

    fill2 = FillEvent(
        order_id="sync_2",
        symbol="ADA/USDT",
        side="SELL",
        quantity=1000.0,
        fill_price=0.60,
        commission=1.0,
    )
    engine.update_position(fill2)

    assert engine.get_realized_pnl() == pytest.approx(100.0)
    assert engine.get_positions() == {}
    assert engine.get_cash() == pytest.approx(50000.0 - 501.0 + 599.0)

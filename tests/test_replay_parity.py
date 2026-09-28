"""Integration test for Replay vs Live parity.

Guarantees that strategies, risk, execution, and portfolio engines cannot
distinguish replay from live, producing identical signals, fills, and portfolio
states.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from quantflow.analytics.engine import AnalyticsEngine
from quantflow.common.events import (
    FillEvent,
    SignalEvent,
    TickEvent,
)
from quantflow.config.manager import ConfigManager
from quantflow.core.clock import Clock, SimulatedClock, SystemClock
from quantflow.core.event_bus import AsyncEventBus, InMemoryEventBus
from quantflow.exchanges.null import NullExchangeAdapter
from quantflow.execution.paper import PaperExecutionHandler
from quantflow.market_data.orderbook import LocalOrderBook
from quantflow.portfolio.engine import PortfolioEngine, PortfolioState
from quantflow.replay.engine import ReplayEngine, ReplaySpeed
from quantflow.replay.event_store import InMemoryEventStoreReader
from quantflow.risk.engine import RiskEngine
from quantflow.strategies.momentum.strategy import SimpleMomentumStrategy


def _generate_btc_fixture_events(start: datetime) -> list[TickEvent]:
    """Generate a series of ticks producing a BUY signal followed by a SELL signal."""
    # Period is 5, threshold is 0.01 (1%)
    # Initial ramp up: 50000 -> 50800 (+1.6% return over 5 periods) -> triggers BUY
    # Then drop: 50800 -> 49800 (-1.9% return over 5 periods) -> triggers SELL
    prices = [
        50000.0, 50100.0, 50200.0, 50300.0, 50500.0, 50800.0,  # BUY trigger index 5
        50600.0, 50400.0, 50200.0, 50000.0, 49800.0,  # SELL trigger index 10
        49800.0, 49800.0,
    ]
    events = []
    for i, p in enumerate(prices):
        t = start + timedelta(seconds=i * 10)
        events.append(
            TickEvent(
                event_id=f"tick_{i:03d}",
                symbol="BTC/USDT",
                exchange="binance",
                bid_price=p - 1.0,
                ask_price=p + 1.0,
                bid_size=10.0,
                ask_size=10.0,
                last_price=p,
                last_size=1.0,
                timestamp=t,
                timestamp_received=t,
            )
        )
    return events


async def run_pipeline(
    clock: Clock,
    event_source: ReplayEngine | list[TickEvent],
    event_bus: AsyncEventBus,
    historical_events: list[TickEvent],
) -> dict[str, Any]:
    """Run the complete strategy + risk + execution + portfolio + analytics pipeline."""
    config = ConfigManager(
        defaults={
            "risk": {
                "allowed_symbols": ["BTC/USDT"],
                "max_position_qty": 100.0,
                "max_daily_loss": 100000.0,
            },
            "portfolio": {"initial_cash": 100000.0},
            "analytics": {"risk_free_rate": 0.0, "annualization_factor": 252.0},
        }
    )

    # 1. Order book setup for paper execution fills
    order_book = LocalOrderBook("BTC/USDT")
    await order_book.apply_snapshot(
        bids=[[49500.0, 50.0], [49000.0, 50.0]],
        asks=[[51000.0, 50.0], [51500.0, 50.0]],
        update_id=1,
    )

    # 2. Engines wiring
    strategy = SimpleMomentumStrategy(
        event_bus=event_bus,
        config={"symbol": "BTC/USDT", "period": 5, "threshold": 0.01},
        clock=clock,
    )
    await strategy.initialize(clock=clock)

    exchange = NullExchangeAdapter(clock=clock)
    exec_handler = PaperExecutionHandler(
        config=config,
        event_bus=event_bus,
        order_books={"BTC/USDT": order_book},
        clock=clock,
    )
    risk = RiskEngine(
        config=config,
        event_bus=event_bus,
        exchange_adapter=exchange,
        execution_handler=exec_handler,
        clock=clock,
    )
    portfolio = PortfolioEngine(
        config=config,
        event_bus=event_bus,
        price_provider=lambda s: 50000.0,
        initial_cash_or_clock=clock,
        clock=clock,
    )
    analytics = AnalyticsEngine(config=config, event_bus=event_bus, clock=clock)

    # 3. Capture outputs
    captured_signals: list[SignalEvent] = []
    captured_fills: list[FillEvent] = []

    async def record_signal(s: SignalEvent) -> None:
        captured_signals.append(s)

    async def record_fill(f: FillEvent) -> None:
        captured_fills.append(f)

    await event_bus.subscribe(SignalEvent, record_signal)
    await event_bus.subscribe(FillEvent, record_fill)

    # 4. Start engines
    await risk.start()
    await exec_handler.start()
    await portfolio.start()
    await analytics.start()

    # 5. Feed events
    if isinstance(event_source, ReplayEngine):
        start = historical_events[0].timestamp_received
        end = historical_events[-1].timestamp_received + timedelta(seconds=1)
        await event_source.run(start, end)
    else:
        # Live-like: publish events sequentially directly to event_bus
        for ev in historical_events:
            await event_bus.publish(ev)
            await asyncio.sleep(0)  # let async handlers complete

    # Small yield to let final asynchronous callbacks settle
    await asyncio.sleep(0.01)

    res = {
        "signals": captured_signals,
        "fills": captured_fills,
        "portfolio": portfolio.get_state(),
        "metrics": analytics.get_metrics(),
    }

    # 6. Graceful teardown
    await risk.stop()
    await exec_handler.stop()
    await portfolio.stop()
    await analytics.stop()

    return res


@pytest.mark.asyncio
async def test_replay_live_parity() -> None:
    """Critical Parity Test:

    Run the same pipeline once against live-shaped events (SystemClock)
    and once through the replay engine (SimulatedClock) with identical data.
    Assert identical resulting signals, fills, and portfolio state.
    """
    start_time = datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC)
    historical_events = _generate_btc_fixture_events(start_time)

    # ── Run 1: Simulated replay ───────────────────────────────────
    sim_clock = SimulatedClock(start_time=start_time)
    bus_replay = InMemoryEventBus(clock=sim_clock)
    store = InMemoryEventStoreReader(historical_events)
    replay = ReplayEngine(store, bus_replay, sim_clock, speed=ReplaySpeed.INSTANT)
    result_replay = await run_pipeline(
        sim_clock, replay, bus_replay, historical_events
    )

    # ── Run 2: Direct injection (mimics live) ─────────────────────
    sys_clock = SystemClock()
    bus_live = InMemoryEventBus(clock=sys_clock)
    result_live = await run_pipeline(
        sys_clock, historical_events, bus_live, historical_events
    )

    # ── Assert Structural Parity ──────────────────────────────────
    # 1. Signals
    assert len(result_replay["signals"]) == len(result_live["signals"])
    assert len(result_replay["signals"]) >= 2  # BUY and SELL occurred

    assert [s.payload.direction for s in result_replay["signals"]] == [
        s.payload.direction for s in result_live["signals"]
    ]
    assert [s.quantity for s in result_replay["signals"]] == [
        s.quantity for s in result_live["signals"]
    ]
    assert [s.strategy_id for s in result_replay["signals"]] == [
        s.strategy_id for s in result_live["signals"]
    ]

    # 2. Fills
    assert len(result_replay["fills"]) == len(result_live["fills"])
    assert len(result_replay["fills"]) >= 2

    assert [f.payload.price for f in result_replay["fills"]] == [
        f.payload.price for f in result_live["fills"]
    ]
    assert [f.quantity for f in result_replay["fills"]] == [
        f.quantity for f in result_live["fills"]
    ]
    assert [f.side for f in result_replay["fills"]] == [
        f.side for f in result_live["fills"]
    ]
    assert [f.commission for f in result_replay["fills"]] == [
        f.commission for f in result_live["fills"]
    ]

    # 3. Portfolio State
    replay_state: PortfolioState = result_replay["portfolio"]
    live_state: PortfolioState = result_live["portfolio"]

    assert replay_state.cash == pytest.approx(live_state.cash)
    assert replay_state.realized_pnl == pytest.approx(live_state.realized_pnl)
    assert replay_state.total_equity == pytest.approx(live_state.total_equity)
    assert replay_state.total_exposure == pytest.approx(live_state.total_exposure)
    assert {k: v.quantity for k, v in replay_state.positions.items()} == {
        k: v.quantity for k, v in live_state.positions.items()
    }

    # 4. Analytics Metrics
    replay_metrics = result_replay["metrics"]
    live_metrics = result_live["metrics"]
    assert replay_metrics["total_trades"] == live_metrics["total_trades"]
    assert replay_metrics["win_rate"] == pytest.approx(live_metrics["win_rate"])

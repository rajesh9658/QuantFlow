"""Unit tests for ReplayEngine and EventStoreReader."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from quantflow.common.events import Event, OrderBookEvent, TickEvent
from quantflow.core.clock import SimulatedClock
from quantflow.core.event_bus import AsyncEventBus
from quantflow.replay.engine import ReplayEngine, ReplaySpeed
from quantflow.replay.event_store import InMemoryEventStoreReader


def _make_fixture_ticks(
    start: datetime, count: int = 5, step_seconds: int = 10, symbol: str = "BTC/USDT"
) -> list[TickEvent]:
    events = []
    for i in range(count):
        t = start + timedelta(seconds=i * step_seconds)
        events.append(
            TickEvent(
                event_id=f"tick_{i}",
                symbol=symbol,
                exchange="binance",
                bid_price=50000.0 + i,
                ask_price=50001.0 + i,
                bid_size=1.0,
                ask_size=1.0,
                last_price=50000.5 + i,
                last_size=0.5,
                timestamp=t,
                timestamp_received=t,
            )
        )
    return events


@pytest.mark.asyncio
async def test_replay_publishes_in_chronological_order() -> None:
    """ReplayEngine publishes events in strictly chronological order
    even if store was unordered.
    """
    start = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    ticks = _make_fixture_ticks(start, count=6, step_seconds=10)

    # Scramble ordering in store
    shuffled = [ticks[3], ticks[0], ticks[5], ticks[1], ticks[4], ticks[2]]
    store = InMemoryEventStoreReader(shuffled)

    bus = AsyncEventBus()
    clock = SimulatedClock(start)
    published: list[Event] = []

    async def on_event(ev: Event) -> None:
        published.append(ev)

    await bus.subscribe(TickEvent, on_event)

    engine = ReplayEngine(store, bus, clock, speed=ReplaySpeed.INSTANT)
    end = start + timedelta(seconds=100)
    await engine.run(start, end)

    assert len(published) == 6
    assert [e.event_id for e in published] == [f"tick_{i}" for i in range(6)]
    # Verify strict ascending order of arrival timestamps
    timestamps = [e.timestamp_received for e in published]
    assert timestamps == sorted(timestamps)


@pytest.mark.asyncio
async def test_simulated_clock_advances_only_as_events_processed() -> None:
    """SimulatedClock advances in lockstep with the arrival time of each event."""
    start = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    ticks = _make_fixture_ticks(start, count=4, step_seconds=15)
    store = InMemoryEventStoreReader(ticks)

    bus = AsyncEventBus()
    clock = SimulatedClock(start)
    clock_at_event: list[datetime] = []

    async def on_event(ev: Event) -> None:
        clock_at_event.append(clock.now())

    await bus.subscribe(TickEvent, on_event)

    engine = ReplayEngine(store, bus, clock, speed=ReplaySpeed.INSTANT)
    await engine.run(start, start + timedelta(seconds=60))

    assert clock_at_event == [
        start,
        start + timedelta(seconds=15),
        start + timedelta(seconds=30),
        start + timedelta(seconds=45),
    ]
    # Clock ends at last event virtual arrival
    assert clock.now() == start + timedelta(seconds=45)


@pytest.mark.asyncio
async def test_replay_filtering_by_event_type_and_symbol() -> None:
    """ReplayEngine filters events according to configured event_types and symbols."""
    start = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    t1 = TickEvent(
        event_id="btc_tick",
        symbol="BTC/USDT",
        bid_price=50000.0,
        ask_price=50001.0,
        bid_size=1.0,
        ask_size=1.0,
        last_price=50000.5,
        last_size=0.1,
        timestamp=start,
        timestamp_received=start,
    )
    t2 = TickEvent(
        event_id="eth_tick",
        symbol="ETH/USDT",
        bid_price=3000.0,
        ask_price=3001.0,
        bid_size=1.0,
        ask_size=1.0,
        last_price=3000.5,
        last_size=0.5,
        timestamp=start + timedelta(seconds=5),
        timestamp_received=start + timedelta(seconds=5),
    )
    ob1 = OrderBookEvent(
        event_id="btc_ob",
        symbol="BTC/USDT",
        bids=[[50000.0, 1.0]],
        asks=[[50001.0, 1.0]],
        timestamp=start + timedelta(seconds=10),
        timestamp_received=start + timedelta(seconds=10),
    )

    store = InMemoryEventStoreReader([t1, t2, ob1])
    bus = AsyncEventBus()
    clock = SimulatedClock(start)
    published: list[Event] = []

    async def on_event(ev: Event) -> None:
        published.append(ev)

    await bus.subscribe(Event, on_event)

    # Filter: only TICK events for BTC/USDT
    engine = ReplayEngine(
        store,
        bus,
        clock,
        speed=ReplaySpeed.INSTANT,
        event_types=["TICK"],
        symbols=["BTC/USDT"],
    )
    await engine.run(start, start + timedelta(seconds=30))

    assert len(published) == 1
    assert published[0].event_id == "btc_tick"


@pytest.mark.asyncio
async def test_discrete_event_simulation_interleaved_clock_sleep() -> None:
    """Wakeups scheduled via clock.sleep inside an event handler are resolved

    before subsequent historical events arriving after the wakeup time.
    """
    start = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    # Event 1 at t=0s, Event 2 at t=20s
    ev1 = TickEvent(
        event_id="ev_0s",
        symbol="BTC/USDT",
        bid_price=50000.0,
        ask_price=50001.0,
        bid_size=1.0,
        ask_size=1.0,
        last_price=50000.5,
        last_size=1.0,
        timestamp=start,
        timestamp_received=start,
    )
    ev2 = TickEvent(
        event_id="ev_20s",
        symbol="BTC/USDT",
        bid_price=50010.0,
        ask_price=50011.0,
        bid_size=1.0,
        ask_size=1.0,
        last_price=50010.5,
        last_size=1.0,
        timestamp=start + timedelta(seconds=20),
        timestamp_received=start + timedelta(seconds=20),
    )

    store = InMemoryEventStoreReader([ev1, ev2])
    bus = AsyncEventBus()
    clock = SimulatedClock(start)

    execution_log: list[tuple[str, datetime]] = []

    async def on_event(ev: Event) -> None:
        execution_log.append((f"event:{ev.event_id}", clock.now()))
        if ev.event_id == "ev_0s":
            # Schedule a background virtual sleep for 8 seconds (lands at t=8s < t=20s)
            asyncio.create_task(periodic_strategy_task())

    async def periodic_strategy_task() -> None:
        await clock.sleep(8.0)
        execution_log.append(("strategy_wake_8s", clock.now()))

    await bus.subscribe(TickEvent, on_event)

    engine = ReplayEngine(store, bus, clock, speed=ReplaySpeed.INSTANT)
    await engine.run(start, start + timedelta(seconds=30))

    # The order MUST be:
    # 1. ev_0s at t=0s
    # 2. strategy_wake_8s at t=8s (resolved BEFORE ev_20s!)
    # 3. ev_20s at t=20s
    assert len(execution_log) == 3
    assert execution_log[0] == ("event:ev_0s", start)
    assert execution_log[1] == ("strategy_wake_8s", start + timedelta(seconds=8))
    assert execution_log[2] == ("event:ev_20s", start + timedelta(seconds=20))


@pytest.mark.asyncio
async def test_replay_speed_wall_delay() -> None:
    """When speed is finite (e.g. 100x), wall-clock sleep is proportioned."""
    start = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    # Virtual delta = 2.0s. At 100x, wall sleep = 0.02s
    t1 = TickEvent(
        event_id="t1",
        symbol="BTC/USDT",
        bid_price=100.0,
        ask_price=101.0,
        bid_size=1.0,
        ask_size=1.0,
        last_price=100.5,
        last_size=1.0,
        timestamp=start,
        timestamp_received=start,
    )
    t2 = TickEvent(
        event_id="t2",
        symbol="BTC/USDT",
        bid_price=100.0,
        ask_price=101.0,
        bid_size=1.0,
        ask_size=1.0,
        last_price=100.5,
        last_size=1.0,
        timestamp=start + timedelta(seconds=2),
        timestamp_received=start + timedelta(seconds=2),
    )

    store = InMemoryEventStoreReader([t1, t2])
    bus = AsyncEventBus()
    clock = SimulatedClock(start)

    engine = ReplayEngine(store, bus, clock, speed=100.0)

    loop = asyncio.get_running_loop()
    t_before = loop.time()
    await engine.run(start, start + timedelta(seconds=10))
    t_after = loop.time()

    elapsed = t_after - t_before
    # Expected wall delay ~0.02s
    assert elapsed >= 0.015


@pytest.mark.asyncio
async def test_replay_stop_aborts_loop() -> None:
    """Calling stop() halts event publishing before end."""
    start = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    ticks = _make_fixture_ticks(start, count=10, step_seconds=5)
    store = InMemoryEventStoreReader(ticks)
    bus = AsyncEventBus()
    clock = SimulatedClock(start)
    count = 0

    engine = ReplayEngine(store, bus, clock, speed=ReplaySpeed.INSTANT)

    async def on_event(ev: Event) -> None:
        nonlocal count
        count += 1
        if count == 3:
            await engine.stop()

    await bus.subscribe(TickEvent, on_event)
    await engine.run(start, start + timedelta(seconds=100))

    assert count == 3
    assert engine.events_published == 3

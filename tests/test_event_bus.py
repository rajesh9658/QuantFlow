"""Unit tests for AsyncEventBus in quantflow/core/event_bus.py."""

import asyncio

import pytest

from quantflow.common.events import Event, SignalEvent, TickEvent
from quantflow.core.event_bus import AsyncEventBus


@pytest.mark.asyncio
async def test_publish_subscribe_single() -> None:
    """Test single subscriber callback receives published event."""
    bus = AsyncEventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    await bus.subscribe(TickEvent, handler)

    tick = TickEvent(
        symbol="BTC-USD",
        bid_price=50000.0,
        ask_price=50005.0,
        bid_size=1.5,
        ask_size=2.0,
        last_price=50002.0,
        last_size=0.5,
    )
    await bus.publish(tick)

    assert len(received) == 1
    assert received[0] == tick


@pytest.mark.asyncio
async def test_multiple_subscribers() -> None:
    """Test fan-out publication to multiple callback handlers and subscriber queues."""
    bus = AsyncEventBus()
    received_1: list[Event] = []
    received_2: list[Event] = []

    async def handler1(event: Event) -> None:
        received_1.append(event)

    async def handler2(event: Event) -> None:
        received_2.append(event)

    await bus.subscribe(SignalEvent, handler1)
    await bus.subscribe(SignalEvent, handler2)

    q = await bus.subscribe_queue(SignalEvent, maxsize=10)

    sig = SignalEvent(
        strategy_id="MA_CROSS",
        symbol="ETH-USD",
        side="BUY",
        quantity=2.0,
    )
    await bus.publish(sig)

    assert len(received_1) == 1
    assert len(received_2) == 1
    assert received_1[0] == sig
    assert received_2[0] == sig

    queue_event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert queue_event == sig


@pytest.mark.asyncio
async def test_concurrent_publish_no_event_loss() -> None:
    """Test no event loss under heavy concurrent publishes across subscribers."""

    bus = AsyncEventBus()
    num_publishers = 10
    events_per_publisher = 50
    total_events = num_publishers * events_per_publisher

    q1 = await bus.subscribe_queue(TickEvent, maxsize=total_events)
    q2 = await bus.subscribe_queue(TickEvent, maxsize=total_events)

    async def publisher(pub_id: int) -> None:
        for i in range(events_per_publisher):
            tick = TickEvent(
                symbol=f"SYM-{pub_id}",
                bid_price=100.0 + i,
                ask_price=101.0 + i,
                bid_size=1.0,
                ask_size=1.0,
                last_price=100.5,
                last_size=1.0,
            )
            await bus.publish(tick)

    publish_tasks = [asyncio.create_task(publisher(i)) for i in range(num_publishers)]
    await asyncio.gather(*publish_tasks)

    received_q1: list[TickEvent] = []
    received_q2: list[TickEvent] = []

    for _ in range(total_events):
        ev1 = await asyncio.wait_for(q1.get(), timeout=2.0)
        ev2 = await asyncio.wait_for(q2.get(), timeout=2.0)
        received_q1.append(ev1)
        received_q2.append(ev2)

    assert len(received_q1) == total_events
    assert len(received_q2) == total_events


@pytest.mark.asyncio
async def test_unsubscribe() -> None:
    """Test handler unsubscription stops receiving subsequent events."""
    bus = AsyncEventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    await bus.subscribe(SignalEvent, handler)

    sig1 = SignalEvent(strategy_id="s1", symbol="BTC", side="BUY", quantity=1.0)
    await bus.publish(sig1)
    assert len(received) == 1

    await bus.unsubscribe(SignalEvent, handler)

    sig2 = SignalEvent(strategy_id="s1", symbol="BTC", side="SELL", quantity=1.0)
    await bus.publish(sig2)
    assert len(received) == 1

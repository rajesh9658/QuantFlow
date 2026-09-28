"""Unit tests for Clock abstractions (RealClock / SystemClock and SimulatedClock)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from quantflow.core.clock import Clock, RealClock, SimulatedClock, SystemClock


def test_real_clock_interface() -> None:
    clock = RealClock()
    assert isinstance(clock, Clock)
    now = clock.now()
    assert now.tzinfo is not None
    assert now.tzinfo in (UTC, UTC)

    m1 = clock.monotonic()
    m2 = clock.monotonic()
    assert m2 >= m1


def test_system_clock_alias() -> None:
    assert SystemClock is RealClock
    clock = SystemClock()
    assert isinstance(clock, Clock)


@pytest.mark.asyncio
async def test_real_clock_sleep() -> None:
    clock = RealClock()
    t0 = clock.monotonic()
    await clock.sleep(0.01)
    t1 = clock.monotonic()
    assert t1 - t0 >= 0.005


def test_simulated_clock_requires_timezone_aware() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SimulatedClock(datetime(2026, 1, 1))  # naive

    with pytest.raises(ValueError, match="timezone-aware"):
        clock = SimulatedClock(datetime(2026, 1, 1, tzinfo=UTC))
        clock.set_start(datetime(2026, 1, 2))  # naive


def test_simulated_clock_now_and_monotonic() -> None:
    start = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    clock = SimulatedClock(start)
    assert clock.now() == start
    assert clock.monotonic() == 0.0

    target = start + timedelta(seconds=120)
    clock.advance_to(target)
    assert clock.now() == target
    assert clock.monotonic() == 120.0


def test_simulated_clock_cannot_move_backwards() -> None:
    start = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    clock = SimulatedClock(start)

    with pytest.raises(ValueError, match="Cannot move simulated clock backwards"):
        clock.advance_to(start - timedelta(seconds=1))


def test_simulated_clock_requires_tz_on_advance() -> None:
    start = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    clock = SimulatedClock(start)

    with pytest.raises(ValueError, match="timezone-aware"):
        clock.advance_to(datetime(2026, 8, 1, 11, 0, 0))


@pytest.mark.asyncio
async def test_simulated_clock_sleep_zero() -> None:
    start = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    clock = SimulatedClock(start)
    # Sleeping <= 0 returns immediately
    await clock.sleep(0)
    await clock.sleep(-5)
    assert clock.peek_next_wakeup() is None


@pytest.mark.asyncio
async def test_simulated_clock_sleep_and_advance() -> None:
    start = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    clock = SimulatedClock(start)

    completed = []

    async def sleeper(delay: float, name: str) -> None:
        await clock.sleep(delay)
        completed.append((name, clock.now()))

    task1 = asyncio.create_task(sleeper(10, "task1"))
    task2 = asyncio.create_task(sleeper(20, "task2"))
    await asyncio.sleep(0)  # let tasks register sleeps

    assert clock.peek_next_wakeup() == start + timedelta(seconds=10)

    # Advance to 5s — neither task should wake up
    clock.advance_to(start + timedelta(seconds=5))
    await asyncio.sleep(0)
    assert len(completed) == 0

    # Advance to 10s — task1 wakes up
    clock.advance_to(start + timedelta(seconds=10))
    await asyncio.sleep(0)
    assert len(completed) == 1
    assert completed[0] == ("task1", start + timedelta(seconds=10))
    assert clock.peek_next_wakeup() == start + timedelta(seconds=20)

    # Advance to 25s — task2 wakes up
    clock.advance_to(start + timedelta(seconds=25))
    await asyncio.sleep(0)
    assert len(completed) == 2
    assert completed[1] == ("task2", start + timedelta(seconds=25))
    assert clock.peek_next_wakeup() is None

    await task1
    await task2


@pytest.mark.asyncio
async def test_simulated_clock_sleep_cancellation() -> None:
    start = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    clock = SimulatedClock(start)

    async def sleeper() -> None:
        await clock.sleep(100)

    task = asyncio.create_task(sleeper())
    await asyncio.sleep(0)

    assert clock.peek_next_wakeup() == start + timedelta(seconds=100)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Pending list should now be empty
    assert clock.peek_next_wakeup() is None

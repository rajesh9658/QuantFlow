"""Clock abstraction and implementations for live and simulated time."""

from __future__ import annotations

import asyncio
import bisect
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta


class Clock(ABC):
    """Abstract time source. All components must use this instead of
    datetime.now(), time.time(), or time.monotonic() directly.
    """

    @abstractmethod
    def now(self) -> datetime:
        """Return current timezone-aware UTC datetime."""
        ...

    @abstractmethod
    def monotonic(self) -> float:
        """Return a monotonic seconds counter (for latency measurement)."""
        ...

    @abstractmethod
    async def sleep(self, seconds: float) -> None:
        """Sleep for `seconds` of virtual time."""
        ...


class RealClock(Clock):
    """Live clock backed by the OS."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


# Alias for spec compatibility
SystemClock = RealClock


class SimulatedClock(Clock):
    """Virtual clock driven by the Replay Engine.

    - `now()` returns the simulated time.
    - `sleep(s)` registers a wakeup at `now() + s` and blocks until
      the replay engine advances simulated time to that point.
    - `advance_to(t)` moves time forward and resolves any pending wakeups.
    Thread-safe for a single-threaded asyncio event loop.
    """

    def __init__(self, start_time: datetime) -> None:
        if start_time.tzinfo is None:
            raise ValueError("SimulatedClock requires timezone-aware start_time")
        self._start_time: datetime = start_time
        self._current: datetime = start_time
        self._monotonic_base: float = 0.0
        self._wall_start: float = time.monotonic()
        # Sorted list of (wakeup_time, future)
        self._pending: list[tuple[datetime, asyncio.Future[None]]] = []

    def now(self) -> datetime:
        return self._current

    def monotonic(self) -> float:
        return self._monotonic_base + (self._current - self._start).total_seconds()

    @property
    def _start(self) -> datetime:
        return self._start_time

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        target = self._current + timedelta(seconds=seconds)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[None] = loop.create_future()
        # Insert keeping sorted order by target datetime
        idx = bisect.bisect_left(self._pending, target, key=lambda x: x[0])
        self._pending.insert(idx, (target, fut))
        try:
            await fut
        except asyncio.CancelledError:
            self._pending = [(t, f) for t, f in self._pending if f is not fut]
            raise

    def advance_to(self, target: datetime) -> None:
        """Advance simulated time to `target`.

        Resolves any pending sleeps whose wakeup time is <= target.
        """
        if target.tzinfo is None:
            raise ValueError("SimulatedClock requires timezone-aware target datetime")
        if target < self._current:
            raise ValueError(
                f"Cannot move simulated clock backwards: {target} < {self._current}"
            )
        self._current = target

        remaining: list[tuple[datetime, asyncio.Future[None]]] = []
        to_resolve: list[asyncio.Future[None]] = []
        for wake_time, fut in self._pending:
            if wake_time <= target:
                to_resolve.append(fut)
            else:
                remaining.append((wake_time, fut))
        self._pending = remaining

        for fut in to_resolve:
            if not fut.done():
                fut.set_result(None)

    def peek_next_wakeup(self) -> datetime | None:
        """Return the earliest pending wakeup, if any."""
        return self._pending[0][0] if self._pending else None

    def set_start(self, start_time: datetime) -> None:
        """Initialize the epoch. Called once by ReplayEngine before events."""
        if start_time.tzinfo is None:
            raise ValueError("SimulatedClock requires timezone-aware start_time")
        self._start_time = start_time
        self._current = start_time

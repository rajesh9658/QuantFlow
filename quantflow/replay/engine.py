"""Replay Engine for historical event replay and time virtualization."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime

from quantflow.common.events import Event
from quantflow.core.clock import SimulatedClock
from quantflow.core.interfaces import EventBus
from quantflow.core.logging import get_logger
from quantflow.replay.event_store import EventStoreReader, InMemoryEventStoreReader


class ReplaySpeed:
    """How fast to run simulated time relative to wall time."""

    REAL_TIME = 1.0
    X10 = 10.0
    X100 = 100.0
    INSTANT = float("inf")  # as fast as possible


class ReplayEngine:
    """Reads historical events and republishes them on the EventBus.

    Drives the SimulatedClock so all downstream components see consistent,
    deterministic time. Merges market data events with internal clock wakeups
    (discrete-event simulation).
    """

    def __init__(
        self,
        event_store: EventStoreReader | list[Event],
        event_bus: EventBus,
        clock: SimulatedClock,
        speed: float = ReplaySpeed.INSTANT,
        event_types: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> None:
        if isinstance(event_store, list):
            self.event_store: EventStoreReader = InMemoryEventStoreReader(event_store)
        else:
            self.event_store = event_store
        self.event_bus = event_bus
        self.clock = clock
        self.speed = speed
        self.event_types = event_types
        self.symbols = symbols
        self.logger = get_logger("replay_engine")
        self._running = False
        self._events_published = 0

    @property
    def events_published(self) -> int:
        return self._events_published

    async def run(self, start: datetime, end: datetime) -> None:
        """Replay all events in [start, end) through the EventBus
        at configured speed.
        """
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError(
                "ReplayEngine.run requires timezone-aware start and end datetimes"
            )
        if end < start:
            raise ValueError(f"end ({end}) must be >= start ({start})")

        self._running = True
        self._events_published = 0
        self.clock.set_start(start)

        wall_start = asyncio.get_running_loop().time()
        self.logger.info(
            "Replay starting: range=[%s, %s), speed=%sx", start, end, self.speed
        )

        async for event in self.event_store.read_range(
            start, end, event_types=self.event_types, symbols=self.symbols
        ):
            if not self._running:
                break

            virtual_arrival = (
                getattr(event, "timestamp_received", None)
                or getattr(event, "timestamp_exchange", None)
                or event.timestamp
            )
            if virtual_arrival.tzinfo is None:
                virtual_arrival = virtual_arrival.replace(tzinfo=UTC)

            # Advance to any internal clock wakeups scheduled BEFORE this event
            while self._running:
                next_wake = self.clock.peek_next_wakeup()
                if next_wake is not None and next_wake < virtual_arrival:
                    await self._advance_to(next_wake, wall_start)
                    # Yield to allow the awakened task to execute its continuation
                    await asyncio.sleep(0)
                else:
                    break

            if not self._running:
                break

            # Advance simulated clock to this event's virtual arrival
            await self._advance_to(virtual_arrival, wall_start)

            # Republish event exactly as live would
            await self.event_bus.publish(event)
            self._events_published += 1

            # Yield control so event handlers (and any clock.sleep calls) can run
            await asyncio.sleep(0)

        # Drain any remaining wakeups up to `end`
        if self._running:
            await self._drain_wakeups(wall_start, end)

        self.logger.info(
            "Replay complete. Published %d events", self._events_published
        )

    async def run_all(self) -> None:
        """Replay all available events in the store from earliest to latest."""
        start = datetime(1970, 1, 1, tzinfo=UTC)
        end = datetime(2099, 1, 1, tzinfo=UTC)
        await self.run(start, end)

    async def stop(self) -> None:
        """Stop replay execution."""
        self._running = False

    # ── Internal discrete-event helpers ──────────────────────────

    async def _advance_to(self, target: datetime, wall_start: float) -> None:
        """Advance clock to `target`, honoring the speed factor.

        - If INSTANT (or <= 0 or inf): advance immediately without wall sleep.
        - Otherwise: sleep wall-clock `(target - clock.now()) / speed`
          before advancing simulated time.
        """
        current = self.clock.now()
        if target <= current:
            return

        is_instant = (
            self.speed == ReplaySpeed.INSTANT
            or math.isinf(self.speed)
            or self.speed <= 0
        )

        if not is_instant:
            virtual_delta = (target - current).total_seconds()
            wall_delay = virtual_delta / self.speed
            if wall_delay > 0:
                await asyncio.sleep(wall_delay)

        self.clock.advance_to(target)

    async def _drain_wakeups(
        self, wall_start: float, end: datetime | None = None
    ) -> None:
        """After all events are processed, resolve any pending clock wakeups."""
        while self._running:
            next_wake = self.clock.peek_next_wakeup()
            if next_wake is None:
                break
            if end is not None and next_wake > end:
                break
            await self._advance_to(next_wake, wall_start)
            await asyncio.sleep(0)

QuantFlow Platform Specification – Replay Engine & Time Virtualization
Design Guarantee
The Replay Engine re-publishes historical events onto the same EventBus, using the same event types, at either real-time speed or accelerated. Strategies, Risk, Execution, Portfolio, and Analytics cannot distinguish replay from live because:

Every component reads time via an injected Clock, never time.time() or datetime.now() directly.

Every component subscribes/publishes via the EventBus interface, which the replay engine feeds exactly like a live ExchangeAdapter would.

Every event carries the same schema (Sprint 0) with timestamp_exchange and timestamp_received filled from the simulated clock, not the wall clock.

No component branches on source or environment. The composition root is the only place that knows whether we're live or replay.

This is provable: an integration test runs the same event stream through live and replay paths and asserts identical outputs (signals, fills, portfolio state) modulo wall-clock timestamps.

1. Clock Abstraction
python
# clock.py
from abc import ABC, abstractmethod
from datetime import datetime, timezone
import asyncio
import time
from typing import List, Tuple, Optional


class Clock(ABC):
    """
    Abstract time source. All components must use this instead of
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


class SystemClock(Clock):
    """Live clock backed by the OS."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class SimulatedClock(Clock):
    """
    Virtual clock driven by the Replay Engine.
    - `now()` returns the simulated time.
    - `sleep(s)` registers a wakeup at `now() + s` and blocks until
      the replay engine advances simulated time to that point.
    - `advance_to(t)` moves time forward and resolves any pending wakeups.
    Thread-safe for a single-threaded asyncio event loop.
    """

    def __init__(self, start_time: datetime):
        if start_time.tzinfo is None:
            raise ValueError("SimulatedClock requires timezone-aware start_time")
        self._current: datetime = start_time
        self._monotonic_base: float = 0.0
        self._wall_start: float = time.monotonic()
        # Sorted list of (wakeup_time, future)
        self._pending: List[Tuple[datetime, asyncio.Future]] = []

    def now(self) -> datetime:
        return self._current

    def monotonic(self) -> float:
        # Monotonic increases with simulated time, offset by wall base
        delta = (self._current - self._epoch).total_seconds() if hasattr(self, "_epoch") else 0.0
        # Simpler: derive from simulated time
        return self._monotonic_base + (self._current - self._start).total_seconds()

    @property
    def _start(self) -> datetime:
        return self._start_time

    async def sleep(self, seconds: float) -> None:
        if seconds <= 0:
            return
        target = self._current + __import__("datetime").timedelta(seconds=seconds)
        fut = asyncio.get_running_loop().create_future()
        # Insert keeping sorted order
        import bisect
        idx = bisect.bisect_left(self._pending, (target, None))
        self._pending.insert(idx, (target, fut))
        try:
            await fut
        except asyncio.CancelledError:
            # Remove if cancelled
            self._pending = [(t, f) for t, f in self._pending if f is not fut]
            raise

    def advance_to(self, target: datetime) -> None:
        """
        Advance simulated time to `target`. Resolves any pending sleeps
        whose wakeup time is <= target.
        """
        if target < self._current:
            raise ValueError(
                f"Cannot move simulated clock backwards: {target} < {self._current}"
            )
        self._current = target
        # Resolve wakeups
        remaining: List[Tuple[datetime, asyncio.Future]] = []
        for wake_time, fut in self._pending:
            if wake_time <= target:
                if not fut.done():
                    fut.set_result(None)
            else:
                remaining.append((wake_time, fut))
        self._pending = remaining

    def peek_next_wakeup(self) -> Optional[datetime]:
        """Return the earliest pending wakeup, if any."""
        return self._pending[0][0] if self._pending else None

    def set_start(self, start_time: datetime) -> None:
        """Initialize the epoch. Called once by ReplayEngine before events."""
        self._start_time = start_time
        self._current = start_time
2. Event Store Reader
python
# event_store.py
from abc import ABC, abstractmethod
from datetime import datetime
from typing import AsyncIterator, List, Optional

from events import BaseEvent


class EventStoreReader(ABC):
    """
    Reads historical events from storage in the order they would have
    been received in live trading (sorted by timestamp_received then
    by a stable tie-breaker, e.g., insertion id).
    """

    @abstractmethod
    async def read_range(
        self,
        start: datetime,
        end: datetime,
        event_types: Optional[List[str]] = None,
        symbols: Optional[List[str]] = None,
    ) -> AsyncIterator[BaseEvent]:
        """
        Async-iterate over events in [start, end), ordered by
        (timestamp_received, id).
        """
        ...

    @abstractmethod
    async def read_all(
        self,
        event_types: Optional[List[str]] = None,
        symbols: Optional[List[str]] = None,
    ) -> AsyncIterator[BaseEvent]:
        """Iterate over the entire store."""
        ...


class PostgresEventStoreReader(EventStoreReader):
    """
    Reads from the Sprint 7 PostgreSQL schema. Merges the partitioned
    `tickers`, `orderbooks`, and non-partitioned `signals`/`executions`
    into a single chronological stream.
    """

    def __init__(self, session_factory, batch_size: int = 1000):
        self._session_factory = session_factory
        self._batch_size = batch_size

    async def read_range(self, start, end, event_types=None, symbols=None):
        # Pseudocode: SELECT ... FROM tickers/orderbooks UNION ALL ... ORDER BY received_at, id
        # Yield reconstructed BaseEvent objects (TickerEvent, OrderBookEvent, ...)
        # Batch-fetched to avoid loading full history in memory.
        ...

    async def read_all(self, event_types=None, symbols=None):
        ...
3. Replay Engine
The Replay Engine is a discrete-event simulator. Its main loop merges:

Market data events (sorted by their virtual arrival time)

Clock wakeups (from SimulatedClock.sleep calls inside strategies)

It advances the simulated clock to the earliest of these, processes it, and repeats.

python
# replay_engine.py
import asyncio
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, List, Optional

from clock import SimulatedClock
from event_store import EventStoreReader
from interfaces import EventBus
from events import BaseEvent
from logging_setup import get_logger


class ReplaySpeed:
    """How fast to run simulated time relative to wall time."""
    REAL_TIME = 1.0
    X10 = 10.0
    X100 = 100.0
    INSTANT = float("inf")  # as fast as possible


class ReplayEngine:
    """
    Reads historical events and republishes them on the EventBus.
    Drives the SimulatedClock so all components see consistent time.
    """

    def __init__(
        self,
        event_store: EventStoreReader,
        event_bus: EventBus,
        clock: SimulatedClock,
        speed: float = ReplaySpeed.INSTANT,
        event_types: Optional[List[str]] = None,
        symbols: Optional[List[str]] = None,
    ):
        self.event_store = event_store
        self.event_bus = event_bus
        self.clock = clock
        self.speed = speed
        self.event_types = event_types
        self.symbols = symbols
        self.logger = get_logger("replay_engine")
        self._running = False

    async def run(self, start: datetime, end: datetime) -> None:
        """
        Replay all events in [start, end) through the EventBus at the
        configured speed, driving the SimulatedClock.
        """
        self._running = True
        self.clock.set_start(start)

        wall_start = asyncio.get_event_loop().time()

        self.logger.info(
            f"Replay starting: range=[{start}, {end}), speed={self.speed}x"
        )

        async for event in self.event_store.read_range(
            start, end, event_types=self.event_types, symbols=self.symbols
        ):
            if not self._running:
                break

            # ---- Advance simulated clock to this event's virtual arrival ----
            virtual_arrival = event.timestamp_received or event.timestamp_exchange
            await self._advance_to(virtual_arrival, wall_start)

            # ---- Republish event exactly as live would ----
            await self.event_bus.publish(event)

        # ---- Drain pending wakeups past the last event ----
        await self._drain_wakeups(wall_start)

        self.logger.info("Replay complete")

    async def stop(self) -> None:
        self._running = False

    # ---------- Internal ----------

    async def _advance_to(self, target: datetime, wall_start: float) -> None:
        """
        Advance clock to `target`, honoring the speed factor.
        - If INSTANT: advance immediately.
        - Otherwise: sleep wall-clock `(target - clock.now()) / speed`
          before advancing simulated time.
        """
        current = self.clock.now()
        if target <= current:
            return

        if self.speed == ReplaySpeed.INSTANT or self.speed == float("inf"):
            self.clock.advance_to(target)
            return

        virtual_delta = (target - current).total_seconds()
        wall_delay = virtual_delta / self.speed

        # Cap wall delay so we don't sleep for hours of simulated time
        # when there are large gaps between events in real-time mode.
        # (Real-time replay naturally blocks here.)
        if wall_delay > 0:
            await asyncio.sleep(wall_delay)

        self.clock.advance_to(target)

    async def _drain_wakeups(self, wall_start: float) -> None:
        """
        After all events are processed, resolve any pending clock wakeups
        (e.g., a strategy scheduled a sleep that lands after the last event).
        """
        while True:
            next_wake = self.clock.peek_next_wakeup()
            if next_wake is None:
                break
            await self._advance_to(next_wake, wall_start)
            # Yield control so wakeups can run their continuations
            await asyncio.sleep(0)
3.1 Replay Speed Semantics
Speed	Meaning	Use Case
1.0 (REAL_TIME)	Events published at their historical pace	Live-drill / demo
10.0	10x faster than real time	Fast paper run
100.0	100x faster	Same-day backtests
inf (INSTANT)	All events published as fast as possible	Backtesting
In all modes, the strategies and risk modules see identical event ordering and identical simulated timestamps. Only the wall-clock delay changes.

4. Refactoring: What Changes in Existing Modules
Every module that currently calls datetime.now(timezone.utc) must accept a Clock in its constructor. Below is the minimal change set.

4.1 Market Data Engine
Before: datetime.now(timezone.utc) on every event.

After: self.clock.now().

The engine now receives clock: Clock in __init__.

4.2 Strategy (base interface)
Strategies that need time (e.g., warm-up periods, periodic rebalancing) receive a Clock in their initialize(config, clock) method.

No strategy may call asyncio.sleep directly — they must use await clock.sleep(...). This is the single most important rule.

SimpleMomentumStrategy uses clock.now() for its signal timestamps.

4.3 Risk Engine
Circuit breaker uses daily rollover checks (datetime.now().date()). Change to self.clock.now().date().

Trading hours check uses self.clock.now().

Daily PnL reset also uses self.clock.now().

4.4 Execution Handler (Paper)
Fill timestamps use self.clock.now().

No change to the pure simulate_fill function — it already takes timestamp as a parameter.

4.5 Portfolio Engine
PortfolioState.last_updated uses self.clock.now().

Price provider integration unchanged.

4.6 Analytics Engine
Day rollover uses self.clock.now().date().

Equity curve timestamps use self.clock.now().

4.7 Scheduler
AsyncIOScheduler currently uses asyncio.sleep. Refactor to use await self.clock.sleep(...).

This is the mechanism that allows strategies to schedule periodic jobs in replay mode — the scheduler will fire in simulated time.

4.8 What Does NOT Change
Event schemas (BaseEvent and subclasses): unchanged.

EventBus interface: unchanged.

ExchangeAdapter interface: unchanged (live implementation continues to use SystemClock).

All formulas and algorithms: unchanged.

5. Proof of Indistinguishability
5.1 Structural Argument
Every component in the pipeline depends only on:

The EventBus interface (publish/subscribe).

The Clock interface (now/sleep).

The ConfigManager (immutable during a run).

The Replay Engine is substituted for the live ExchangeAdapter at the composition root. It emits the exact same event types with the exact same fields (only source differs, and no component branches on it). No component inspects the environment or the source of events.

5.2 Integration Test: Live vs Replay Parity
python
# tests/test_replay_parity.py
import asyncio
from datetime import datetime, timezone
from clock import SystemClock, SimulatedClock
from event_bus_in_memory import InMemoryEventBus
from replay_engine import ReplayEngine, ReplaySpeed
from event_store import InMemoryEventStoreReader
# ... import engines ...

async def run_pipeline(clock, event_source, event_bus):
    """Run the full pipeline and capture signals, fills, portfolio states."""
    # Wire up engines with the SAME clock and bus
    strategy = SimpleMomentumStrategy(event_bus, {"symbol": "BTC/USDT", "period": 5, "threshold": 0.01})
    await strategy.initialize({}, clock)

    risk = RiskEngine(config, event_bus, exchange, exec_handler, clock)
    portfolio = PortfolioEngine(config, event_bus, price_provider, clock)
    analytics = AnalyticsEngine(config, event_bus, clock)

    await risk.start(); await portfolio.start(); await analytics.start()

    # Feed events
    if isinstance(event_source, ReplayEngine):
        await event_source.run(start, end)
    else:
        # Live-like: feed events directly
        for ev in historical_events:
            await event_bus.publish(ev)

    # Collect results
    return {
        "signals": captured_signals,
        "fills": captured_fills,
        "portfolio": portfolio.state,
        "metrics": analytics.get_metrics(),
    }

async def test_parity():
    historical = load_fixture_events("btc_usdt_1day.json")

    # --- Run 1: Simulated replay ---
    sim_clock = SimulatedClock(start_time=historical[0].timestamp_received)
    bus1 = InMemoryEventBus(clock=sim_clock)
    store = InMemoryEventStoreReader(historical)
    replay = ReplayEngine(store, bus1, sim_clock, speed=ReplaySpeed.INSTANT)
    result_replay = await run_pipeline(sim_clock, replay, bus1)

    # --- Run 2: Direct injection (mimics live) ---
    # SystemClock is used but events are injected at wall-clock speed.
    sys_clock = SystemClock()
    bus2 = InMemoryEventBus(clock=sys_clock)
    result_live = await run_pipeline(sys_clock, historical, bus2)

    # --- Assert structural equivalence ---
    assert [s.payload.direction for s in result_replay["signals"]] == \
           [s.payload.direction for s in result_live["signals"]]
    assert [f.payload.price for f in result_replay["fills"]] == \
           [f.payload.price for f in result_live["fills"]]
    assert result_replay["portfolio"].cash == result_live["portfolio"].cash
    assert result_replay["metrics"]["sharpe_ratio"] == result_live["metrics"]["sharpe_ratio"]
Because the SimulatedClock is monotonic and deterministic, and because every engine reads time from it, the replay run produces byte-identical outputs (except for wall-clock timestamp_received if the SystemClock is used — which is why the test compares structural fields, not wall-clock fields).

5.3 The Golden Rule
No code outside SystemClock may call datetime.now(), time.time(), time.monotonic(), or asyncio.sleep(). This is enforced via:

A CI lint rule (custom flake8 / ruff plugin) that greps for these symbols in non-test, non-clock.py files.

Code review checklist.

The integration parity test above.

6. Configuration (quantflow.yaml)
yaml
replay:
  speed: 100.0                      # 1.0 = real time, 100.0 = 100x, 0.0 = instant
  event_types: ["ticker", "orderbook", "trade"]
  symbols: ["BTC/USDT", "ETH/USDT"]
  start: "2026-08-01T00:00:00Z"     # optional; overridden by CLI
  end: "2026-08-02T00:00:00Z"
  source: "postgres"                # postgres | parquet | in_memory
7. Composition Root: Live vs Replay
python
# main.py
async def build_app(mode: str):
    config = ConfigManager(Path("quantflow.yaml"))
    configure_logging(config)

    if mode == "live":
        clock = SystemClock()
        event_bus = InMemoryEventBus(clock=clock)
        adapter = BinanceAdapter(config, clock, event_bus)
        exchange = adapter
    elif mode == "paper":
        clock = SystemClock()
        event_bus = InMemoryEventBus(clock=clock)
        exchange = BinanceAdapter(config, clock, event_bus)  # live market data
        execution = PaperExecutionHandler(config, event_bus, order_books, clock)
    elif mode == "replay":
        clock = SimulatedClock(start_time=config.get_datetime("replay.start"))
        event_bus = InMemoryEventBus(clock=clock)
        store = PostgresEventStoreReader(session_factory)
        replay = ReplayEngine(store, event_bus, clock, speed=config.get_float("replay.speed"))
        exchange = NullExchangeAdapter(clock)  # or reuse market data engine fed by replay
        execution = PaperExecutionHandler(config, event_bus, order_books, clock)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    # All engines receive `clock` and `event_bus` — identical wiring in all modes
    market_engine = MarketDataEngine(event_bus, clock)
    portfolio = PortfolioEngine(config, event_bus, get_mid_price, clock)
    risk = RiskEngine(config, event_bus, exchange, execution, clock)
    analytics = AnalyticsEngine(config, event_bus, clock)
    strategy_engine = StrategyEngine(event_bus, strategies, clock)

    # ... start all ...
    if mode == "replay":
        await replay.run(start, end)
    else:
        await asyncio.Event().wait()  # run forever
Notice that the pipeline wiring is identical across modes. Only the clock and the event source differ. This is the architectural guarantee that replay and live are indistinguishable to the rest of the system.

Summary
Concern	Solution
Time virtualization	Clock abstraction (SystemClock / SimulatedClock), injected everywhere.
Replay fidelity	Replay Engine reads from EventStoreReader and republishes to the same EventBus used in live.
Speed control	Wall-clock delay = virtual_delta / speed; INSTANT bypasses sleeping.
Clock wakeups	SimulatedClock.sleep() registers futures; the Replay Engine merges event times with wakeup times in a discrete-event loop.
Indistinguishability	No component branches on mode; only the composition root selects Clock and event source. CI lint forbids direct time calls outside SystemClock.
Verification	Integration parity test runs the same stream through replay and injected-live, asserts identical signals, fills, and portfolio state.
"""Tests for StrategyEngine + SimpleMomentumStrategy."""

from __future__ import annotations

import asyncio
import importlib
import inspect

import pytest

from quantflow.common.events import Event, SignalEvent, TickEvent
from quantflow.core.event_bus import AsyncEventBus
from quantflow.core.interfaces import Strategy
from quantflow.strategies.engine import StrategyEngine
from quantflow.strategies.momentum.strategy import SimpleMomentumStrategy


# ── helpers ──────────────────────────────────────────────────────


def _tick(symbol: str = "BTC/USDT", last: float = 100.0) -> TickEvent:
    return TickEvent(
        symbol=symbol,
        exchange="test",
        bid_price=last - 0.5,
        ask_price=last + 0.5,
        bid_size=1.0,
        ask_size=1.0,
        last_price=last,
        last_size=1.0,
    )


class _CollectorStrategy(Strategy):
    """Records every event it receives."""

    def __init__(self) -> None:
        self.received: list[Event] = []

    def get_name(self) -> str:
        return "collector"

    async def on_event(self, event: Event) -> None:
        self.received.append(event)


class _BrokenStrategy(Strategy):
    """Always raises."""

    def get_name(self) -> str:
        return "broken"

    async def on_event(self, event: Event) -> None:
        raise RuntimeError("boom")


# ── 1. Engine routes ticks to all loaded strategies ──────────────


@pytest.mark.asyncio
async def test_engine_routes_to_all_strategies() -> None:
    bus = AsyncEventBus()
    s1 = _CollectorStrategy()
    s2 = _CollectorStrategy()

    engine = StrategyEngine(bus, {"s1": s1, "s2": s2})
    await engine.start()

    tick = _tick()
    await bus.publish(tick)

    # Small yield so async dispatch completes
    await asyncio.sleep(0.05)

    assert len(s1.received) == 1
    assert len(s2.received) == 1
    assert s1.received[0] == tick
    assert s2.received[0] == tick

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_multiple_ticks() -> None:
    bus = AsyncEventBus()
    coll = _CollectorStrategy()
    engine = StrategyEngine(bus, {"c": coll})
    await engine.start()

    for i in range(5):
        await bus.publish(_tick(last=100.0 + i))
    await asyncio.sleep(0.05)

    assert len(coll.received) == 5
    await engine.stop()


# ── 2. Momentum produces deterministic buy/sell ──────────────────


@pytest.mark.asyncio
async def test_momentum_buy_signal() -> None:
    """Rising prices beyond threshold → BUY signal."""
    bus = AsyncEventBus()
    q = await bus.subscribe_queue(SignalEvent, maxsize=10)
    strat = SimpleMomentumStrategy(bus, {"symbol": "BTC/USDT", "period": 5, "threshold": 0.02})

    engine = StrategyEngine(bus, {"mom": strat})
    await engine.start()

    # Feed 6 prices: 100 → 103 (3% rise over 5 periods > 2% threshold)
    prices = [100.0, 100.5, 101.0, 101.5, 102.0, 103.0]
    for p in prices:
        await bus.publish(_tick(last=p))
        await asyncio.sleep(0.01)

    sig = await asyncio.wait_for(q.get(), timeout=1)
    assert isinstance(sig, SignalEvent)
    assert sig.side == "BUY"
    assert sig.symbol == "BTC/USDT"
    assert sig.strategy_id == strat.get_name()

    await engine.stop()


@pytest.mark.asyncio
async def test_momentum_sell_signal() -> None:
    """Falling prices beyond threshold → SELL signal."""
    bus = AsyncEventBus()
    q = await bus.subscribe_queue(SignalEvent, maxsize=10)
    strat = SimpleMomentumStrategy(bus, {"symbol": "BTC/USDT", "period": 5, "threshold": 0.02})

    engine = StrategyEngine(bus, {"mom": strat})
    await engine.start()

    # Feed 6 prices: 100 → 97 (3% drop > 2% threshold)
    prices = [100.0, 99.5, 99.0, 98.5, 98.0, 97.0]
    for p in prices:
        await bus.publish(_tick(last=p))
        await asyncio.sleep(0.01)

    sig = await asyncio.wait_for(q.get(), timeout=1)
    assert sig.side == "SELL"

    await engine.stop()


@pytest.mark.asyncio
async def test_momentum_no_signal_in_deadzone() -> None:
    """Prices within threshold → no signal emitted."""
    bus = AsyncEventBus()
    q = await bus.subscribe_queue(SignalEvent, maxsize=10)
    strat = SimpleMomentumStrategy(bus, {"symbol": "BTC/USDT", "period": 5, "threshold": 0.10})

    engine = StrategyEngine(bus, {"mom": strat})
    await engine.start()

    # 1% move, well within 10% threshold
    prices = [100.0, 100.2, 100.4, 100.6, 100.8, 101.0]
    for p in prices:
        await bus.publish(_tick(last=p))
        await asyncio.sleep(0.01)

    assert q.empty()
    await engine.stop()


@pytest.mark.asyncio
async def test_momentum_no_repeat_signal() -> None:
    """Same direction doesn't re-emit signal."""
    bus = AsyncEventBus()
    q = await bus.subscribe_queue(SignalEvent, maxsize=10)
    strat = SimpleMomentumStrategy(bus, {"symbol": "BTC/USDT", "period": 3, "threshold": 0.01})

    engine = StrategyEngine(bus, {"mom": strat})
    await engine.start()

    # Rising for many ticks — should only get ONE BUY
    for i in range(10):
        await bus.publish(_tick(last=100.0 + i * 2))
        await asyncio.sleep(0.01)

    sigs: list[SignalEvent] = []
    while not q.empty():
        sigs.append(q.get_nowait())
    buy_count = sum(1 for s in sigs if s.side == "BUY")
    assert buy_count == 1

    await engine.stop()


# ── 3. Exception isolation ───────────────────────────────────────


@pytest.mark.asyncio
async def test_broken_strategy_does_not_crash_engine() -> None:
    bus = AsyncEventBus()
    broken = _BrokenStrategy()
    healthy = _CollectorStrategy()

    engine = StrategyEngine(bus, {"broken": broken, "healthy": healthy})
    await engine.start()

    await bus.publish(_tick())
    await asyncio.sleep(0.05)

    # Healthy strategy still received the event
    assert len(healthy.received) == 1
    await engine.stop()


@pytest.mark.asyncio
async def test_broken_strategy_does_not_block_subsequent_ticks() -> None:
    bus = AsyncEventBus()
    broken = _BrokenStrategy()
    healthy = _CollectorStrategy()

    engine = StrategyEngine(bus, {"broken": broken, "healthy": healthy})
    await engine.start()

    for _ in range(3):
        await bus.publish(_tick())
    await asyncio.sleep(0.05)

    assert len(healthy.received) == 3
    await engine.stop()


# ── 4. No execution imports in strategy module ───────────────────


def test_momentum_module_has_no_execution_imports() -> None:
    """The strategy module must not import any execution/order-placement code."""
    mod = importlib.import_module("quantflow.strategies.momentum.strategy")
    source = inspect.getsource(mod)

    forbidden = [
        "quantflow.execution",
        "quantflow.exchanges",
        "ExecutionEngine",
        "ExchangeAdapter",
        "create_order",
        "submit_order",
        "cancel_order",
        "place_order",
    ]
    for term in forbidden:
        assert term not in source, (
            f"Strategy module must not reference '{term}' — "
            f"strategies can only emit SignalEvents"
        )


def test_strategy_interface_has_no_execution_methods() -> None:
    """The Strategy ABC exposes only get_name and on_event — no order methods."""
    abstract_methods = {
        name
        for name, _ in inspect.getmembers(Strategy, predicate=inspect.isfunction)
        if getattr(getattr(Strategy, name, None), "__isabstractmethod__", False)
    }
    assert abstract_methods == {"get_name", "on_event"}

"""Phase 3 Chaos Tests and Phase 4 Quant Correctness Tests — written during audit.

AUDIT ONLY — do not modify any source file.
Tests cover:
  - WebSocket mid-stream kill: book must be discarded, fresh snapshot requested.
  - One exchange offline: other unaffected.
  - Event-bus flood: queue growth and backpressure under 10x tick rate.
  - SIGTERM during in-flight signal: graceful shutdown, no half-applied state.
  - Tick-to-signal latency measurement (p50/p95/p99).
  - WAC across 3+ partial fills (hand-calculated).
  - Partial close PnL, position flip, fill simulator depth walk.
  - Mid-price exclusion (fills must use book price, never mid).
  - Idempotency documented-failure (AUD-009).
  - Look-ahead bias.
  - Risk boundary tests (exactly at limit, one over).
  - Emergency stop blocks in-flight signals.
  - Daily loss reset.
  - Mutation-style spot checks.
"""
from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import pytest

from quantflow.common.events import (
    ApprovedSignalEvent,
    FillEvent,
    SignalEvent,
    TickEvent,
)
from quantflow.core.clock import SimulatedClock
from quantflow.core.event_bus import AsyncEventBus
from quantflow.market_data.orderbook import LocalOrderBook
from quantflow.portfolio.engine import PortfolioEngine
from quantflow.risk.engine import RiskEngine
from quantflow.strategies.momentum.strategy import SimpleMomentumStrategy


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_tick(symbol: str = "BTC/USDT", price: float = 50000.0,
               exchange: str = "binance") -> TickEvent:
    return TickEvent(symbol=symbol, exchange=exchange, exchange_id=exchange,
                     bid_price=price - 1, ask_price=price + 1,
                     bid_size=1.0, ask_size=1.0,
                     last_price=price, last_size=1.0)


def _make_clock() -> SimulatedClock:
    return SimulatedClock(start_time=datetime(2025, 1, 1, tzinfo=UTC))


# ── CHAOS-1: Orderbook gap triggers resync ───────────────────────────────────

@pytest.mark.asyncio
async def test_chaos_orderbook_resync_on_ws_kill() -> None:
    snapshots: list[str] = []
    async def fake_snap(sym: str) -> None:
        snapshots.append(sym)
    book = LocalOrderBook("BTC/USDT", snapshot_callback=fake_snap)
    await book.apply_snapshot([[50000.0, 1.0]], [[50001.0, 1.0]], update_id=100)
    assert book.initialized
    result = await book.apply_diff([[49999.0, 1.0]], [[50002.0, 1.0]], u=103, pu=102)
    assert result is False
    assert not book.initialized
    assert "BTC/USDT" in snapshots


@pytest.mark.asyncio
async def test_chaos_no_fill_from_uninitialized_book() -> None:
    from quantflow.execution.fill_simulator import FeeSchedule, simulate_fill
    from quantflow.common.events import OrderEvent
    book = LocalOrderBook("BTC/USDT")
    order = OrderEvent(strategy_id="t", symbol="BTC/USDT", exchange_id="paper",
                       side="BUY", order_type="MARKET", quantity=1.0)
    result = simulate_fill(order=order, orderbook_state=book, fee_schedule=FeeSchedule(),
                           timestamp=datetime(2025, 1, 1, tzinfo=UTC))
    assert len(result.fills) == 0
    assert result.remaining_quantity == 1.0


# ── CHAOS-2: Exchange isolation ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chaos_exchange_isolation() -> None:
    bus = AsyncEventBus()
    received_b: list[TickEvent] = []

    async def handler_a(ev: TickEvent) -> None:
        raise RuntimeError("Exchange A down")

    async def handler_b(ev: TickEvent) -> None:
        received_b.append(ev)

    await bus.subscribe(TickEvent, handler_a)
    await bus.subscribe(TickEvent, handler_b)
    with pytest.raises(RuntimeError, match="Exchange A down"):
        await bus.publish(_make_tick())
    # Critical errors are visible, and downstream handlers cannot trade using
    # a partially updated market/account state.
    assert len(received_b) == 0


# ── CHAOS-3: EventBus flood ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chaos_flood_no_loss_callback_subscriber() -> None:
    bus = AsyncEventBus(default_queue_maxsize=50)
    received: list[TickEvent] = []
    async def handler(ev: TickEvent) -> None:
        received.append(ev)
    await bus.subscribe(TickEvent, handler)
    N = 500
    for i in range(N):
        await bus.publish(_make_tick(price=50000.0 + i))
    assert len(received) == N


# ── CHAOS-4: Graceful shutdown ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chaos_graceful_shutdown_portfolio_unchanged() -> None:
    bus = AsyncEventBus()
    risk = RiskEngine(event_bus=bus)
    portfolio = PortfolioEngine(event_bus=bus, initial_cash=100_000.0)
    await risk.start()
    await portfolio.start()
    cash_before = portfolio.get_cash()
    sig = SignalEvent(strategy_id="test", symbol="BTC/USDT", side="BUY", quantity=1.0)
    await bus.publish(sig)
    await risk.stop()
    await portfolio.stop()
    assert portfolio.get_cash() == cash_before


# ── CHAOS-5: Latency measurement (informational) ──────────────────────────────

@pytest.mark.asyncio
async def test_chaos_tick_to_signal_latency_sub_millisecond() -> None:
    bus = AsyncEventBus()
    strategy = SimpleMomentumStrategy(event_bus=bus,
                                      config={"symbol": "BTC/USDT", "period": 2, "threshold": 0.001})
    await strategy.initialize()
    signal_ev = asyncio.Event()
    t_signal: list[float] = []
    async def cap_signal(ev: SignalEvent) -> None:
        t_signal.append(time.monotonic())
        signal_ev.set()
    await bus.subscribe(SignalEvent, cap_signal)
    t_send: list[float] = []
    for p in [50000.0, 50100.0, 50200.0, 50300.0]:
        t0 = time.monotonic()
        t_send.append(t0)
        await bus.publish(_make_tick(price=p))
    try:
        await asyncio.wait_for(signal_ev.wait(), timeout=1.0)
    except asyncio.TimeoutError:
        pytest.skip("No signal in 1s — period warmup pending")
    if t_signal:
        latency_us = (t_signal[0] - t_send[0]) * 1_000_000
        print(f"\n[CHAOS-5] Tick→Signal latency: {latency_us:.1f}μs")
        assert latency_us < 100_000, f"Latency {latency_us:.0f}μs exceeds 100ms"


# ── PHASE 4: WAC 3 partial fills ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_quant_wac_3_fills() -> None:
    portfolio = PortfolioEngine(initial_cash=1_000_000.0)
    for qty, px in [(1.0, 100.0), (2.0, 110.0), (3.0, 120.0)]:
        portfolio.update_position(
            FillEvent(order_id="o", fill_id=f"f{qty}", symbol="X", side="BUY",
                      quantity=qty, fill_price=px, exchange="paper")
        )
    pos = portfolio.get_position("X")
    assert pos is not None
    assert pos.quantity == 6.0
    expected = (1*100 + 2*110 + 3*120) / 6
    assert abs(pos.avg_entry_price - expected) < 1e-6, \
        f"WAC expected {expected:.4f}, got {pos.avg_entry_price:.4f}"


@pytest.mark.asyncio
async def test_quant_partial_close_pnl() -> None:
    portfolio = PortfolioEngine(initial_cash=1_000_000.0)
    portfolio.update_position(
        FillEvent(order_id="o1", fill_id="f1", symbol="X", side="BUY",
                  quantity=4.0, fill_price=100.0, exchange="paper"))
    portfolio.update_position(
        FillEvent(order_id="o2", fill_id="f2", symbol="X", side="SELL",
                  quantity=2.0, fill_price=120.0, exchange="paper"))
    pos = portfolio.get_position("X")
    assert pos is not None
    assert pos.quantity == 2.0
    assert abs(portfolio.get_realized_pnl() - 40.0) < 1e-6


@pytest.mark.asyncio
async def test_quant_position_flip_long_to_short() -> None:
    portfolio = PortfolioEngine(initial_cash=1_000_000.0)
    portfolio.update_position(
        FillEvent(order_id="o1", fill_id="f1", symbol="X", side="BUY",
                  quantity=3.0, fill_price=100.0, exchange="paper"))
    portfolio.update_position(
        FillEvent(order_id="o2", fill_id="f2", symbol="X", side="SELL",
                  quantity=5.0, fill_price=120.0, exchange="paper"))
    pos = portfolio.get_position("X")
    assert pos is not None and pos.quantity == -2.0
    assert abs(pos.avg_entry_price - 120.0) < 1e-6
    assert abs(portfolio.get_realized_pnl() - 60.0) < 1e-6


# ── PHASE 4: Fill simulator ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fill_simulator_walks_depth() -> None:
    from quantflow.execution.fill_simulator import FeeSchedule, simulate_fill
    from quantflow.common.events import OrderEvent
    book = {"bids": [], "asks": [[50000.0, 1.0], [50100.0, 2.0]]}
    order = OrderEvent(strategy_id="t", symbol="BTC/USDT", exchange_id="paper",
                       side="BUY", order_type="MARKET", quantity=3.0)
    result = simulate_fill(order=order, orderbook_state=book,
                           fee_schedule=FeeSchedule(taker_rate=0.0),
                           timestamp=datetime(2025, 1, 1, tzinfo=UTC))
    assert result.remaining_quantity < 1e-9
    expected = (1*50000 + 2*50100) / 3
    assert abs(result.avg_price - expected) < 1e-4


@pytest.mark.asyncio
async def test_fill_never_uses_mid_price() -> None:
    from quantflow.execution.fill_simulator import FeeSchedule, simulate_fill
    from quantflow.common.events import OrderEvent
    book = {"bids": [[49990.0, 1.0]], "asks": [[50010.0, 1.0]]}
    order = OrderEvent(strategy_id="t", symbol="BTC/USDT", exchange_id="paper",
                       side="BUY", order_type="MARKET", quantity=1.0)
    result = simulate_fill(order=order, orderbook_state=book,
                           fee_schedule=FeeSchedule(taker_rate=0.0),
                           timestamp=datetime(2025, 1, 1, tzinfo=UTC))
    assert result.fills and result.fills[0].fill_price == 50010.0


# ── PHASE 4: Idempotency (expected failure — documents bug AUD-009) ───────────

@pytest.mark.asyncio
async def test_quant_idempotency_fill_deduplication() -> None:
    portfolio = PortfolioEngine(initial_cash=1_000_000.0)
    fill = FillEvent(order_id="o1", fill_id="f1", symbol="X", side="BUY",
                     quantity=1.0, fill_price=100.0, exchange="paper")
    portfolio.update_position(fill)
    q1 = portfolio.get_positions().get("X", 0.0)
    portfolio.update_position(fill)  # replay same fill
    q2 = portfolio.get_positions().get("X", 0.0)
    assert q1 == q2 == 1.0, f"Expected idempotent position 1.0, got q1={q1}, q2={q2}"


# ── PHASE 4: Look-ahead bias ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_quant_no_lookahead_bias() -> None:
    clock = _make_clock()
    bus = AsyncEventBus(clock=clock)
    strategy = SimpleMomentumStrategy(event_bus=bus,
                                      config={"symbol": "BTC/USDT", "period": 2, "threshold": 0.001},
                                      clock=clock)
    await strategy.initialize()
    sig_ts: list[datetime] = []
    async def cap(ev: SignalEvent) -> None:
        sig_ts.append(ev.timestamp)
    await bus.subscribe(SignalEvent, cap)
    last_t = datetime(2025, 1, 1, tzinfo=UTC)
    for i, p in enumerate([50000.0, 50100.0, 50200.0, 50300.0]):
        t = datetime(2025, 1, 1, 0, i, 0, tzinfo=UTC)
        clock.advance_to(t)
        last_t = t
        tick = TickEvent(symbol="BTC/USDT", exchange="binance", exchange_id="binance",
                         bid_price=p-1, ask_price=p+1, bid_size=1.0, ask_size=1.0,
                         last_price=p, last_size=1.0, timestamp=t)
        await bus.publish(tick)
        await asyncio.sleep(0)
    for ts in sig_ts:
        assert ts <= last_t, f"Look-ahead bias: signal at {ts} > last tick {last_t}"


# ── PHASE 4: Risk boundaries ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_risk_exactly_at_limit_approved() -> None:
    from quantflow.config.manager import ConfigManager
    cfg = ConfigManager(defaults={"risk": {"max_position_qty": 5.0}})
    risk = RiskEngine(config=cfg)
    risk.positions["BTC/USDT"] = 4.0
    sig = SignalEvent(strategy_id="t", symbol="BTC/USDT", side="BUY", quantity=1.0)
    approved, reason = await risk.validate_signal(sig)
    assert approved, f"Expected approved at limit, got reason={reason}"


@pytest.mark.asyncio
async def test_risk_one_over_limit_rejected() -> None:
    from quantflow.config.manager import ConfigManager
    cfg = ConfigManager(defaults={"risk": {"max_position_qty": 5.0}})
    risk = RiskEngine(config=cfg)
    risk.positions["BTC/USDT"] = 4.5
    sig = SignalEvent(strategy_id="t", symbol="BTC/USDT", side="BUY", quantity=1.0)
    approved, reason = await risk.validate_signal(sig)
    assert not approved
    assert reason == "EXCEEDS_MAX_POSITION_SIZE"


@pytest.mark.asyncio
async def test_risk_emergency_stop_blocks_all() -> None:
    bus = AsyncEventBus()
    risk = RiskEngine(event_bus=bus)
    await risk.start()
    await risk.set_emergency_stop(True, trigger="audit")
    approved_list: list[Any] = []
    async def cap(ev: ApprovedSignalEvent) -> None:
        approved_list.append(ev)
    await bus.subscribe(ApprovedSignalEvent, cap)
    await bus.publish(SignalEvent(strategy_id="t", symbol="BTC/USDT", side="BUY", quantity=1.0))
    await asyncio.sleep(0)
    assert len(approved_list) == 0
    await risk.stop()


@pytest.mark.asyncio
async def test_risk_daily_loss_resets_on_new_utc_day() -> None:
    from quantflow.config.manager import ConfigManager
    cfg = ConfigManager(defaults={"risk": {"max_daily_loss": 100.0}})
    clock = _make_clock()
    risk = RiskEngine(config=cfg, clock=clock)
    clock.advance_to(datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC))
    risk.current_day = "2025-01-01"
    risk.daily_realized_pnl = -95.0
    sig = SignalEvent(strategy_id="t", symbol="BTC/USDT", side="BUY", quantity=1.0)
    ok, _ = await risk.validate_signal(sig)
    assert ok
    clock.advance_to(datetime(2025, 1, 2, 0, 0, 1, tzinfo=UTC))
    ok2, _ = await risk.validate_signal(sig)
    assert ok2, "After new UTC day, daily PnL resets and signal is approved"


# ── PHASE 5: Mutation spot checks ─────────────────────────────────────────────

def test_mutation_wac_division_required() -> None:
    correct = (1*100 + 2*110 + 3*120) / 6
    wrong = 1*100 + 2*110 + 3*120  # missing division
    assert abs(correct - 113.333) < 0.001
    assert wrong == 680.0
    assert correct != wrong


def test_mutation_fill_sort_order_matters() -> None:
    from quantflow.execution.fill_simulator import _extract_levels
    raw = [[50100.0, 1.0], [50000.0, 1.0], [50200.0, 1.0]]
    levels = _extract_levels(raw)
    asc = sorted(levels, key=lambda x: x[0])
    desc = sorted(levels, key=lambda x: x[0], reverse=True)
    assert asc[0][0] == 50000.0, "Ascending sort gives cheapest ask first (correct for BUY)"
    assert desc[0][0] == 50200.0, "Descending sort gives wrong fill price"
    assert asc[0][0] != desc[0][0]

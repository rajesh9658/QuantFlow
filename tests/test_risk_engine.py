"""Unit tests for RiskEngine and modular RiskChecks."""

from __future__ import annotations

import asyncio
import zoneinfo
from datetime import UTC, datetime

import pytest

from quantflow.common.events import (
    ApprovedSignalEvent,
    FillEvent,
    OrderEvent,
    PortfolioUpdateEvent,
    RejectedSignalEvent,
    SignalEvent,
)
from quantflow.config.manager import ConfigManager
from quantflow.core.event_bus import AsyncEventBus
from quantflow.risk.engine import (
    REASON_CIRCUIT_BREAKER,
    REASON_DAILY_LOSS_LIMIT,
    REASON_EMERGENCY_STOP,
    REASON_GLOBAL_HALT,
    REASON_MARKET_CLOSED,
    REASON_MAX_EXPOSURE,
    REASON_MAX_POSITION_SIZE,
    REASON_SYMBOL_NOT_ALLOWED,
    AllowedSymbolsCheck,
    CircuitBreakerCheck,
    DailyLossLimitCheck,
    EmergencyStopCheck,
    GlobalHaltCheck,
    MarketHoursCheck,
    MaxExposureCheck,
    PositionSizeLimitCheck,
    RiskEngine,
)


def _signal(
    symbol: str = "BTC/USDT",
    side: str = "BUY",
    quantity: float = 1.0,
    price: float | None = 50000.0,
) -> SignalEvent:
    return SignalEvent(
        strategy_id="test_strat",
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
    )


# ── 1. Individual Risk Checks ─────────────────────────────────────


@pytest.mark.asyncio
async def test_allowed_symbols_check() -> None:
    config = ConfigManager(
        defaults={"risk": {"allowed_symbols": ["BTC/USDT", "ETH/USDT"]}}
    )
    engine = RiskEngine(config=config)
    check = AllowedSymbolsCheck()

    # Allowed symbol
    passed, reason = await check.validate(_signal(symbol="BTC/USDT"), engine)
    assert passed is True
    assert reason is None

    # Disallowed symbol
    passed, reason = await check.validate(_signal(symbol="XRP/USDT"), engine)
    assert passed is False
    assert reason == REASON_SYMBOL_NOT_ALLOWED

    # Empty allowed_symbols -> all allowed
    empty_config = ConfigManager(defaults={"risk": {"allowed_symbols": []}})
    empty_engine = RiskEngine(config=empty_config)
    passed, reason = await check.validate(_signal(symbol="XRP/USDT"), empty_engine)
    assert passed is True


@pytest.mark.asyncio
async def test_market_hours_check() -> None:
    # Schedule: 09:30 to 16:00 in America/New_York
    config = ConfigManager(
        defaults={
            "risk": {
                "trading_schedule": {
                    "timezone": "America/New_York",
                    "start": "09:30",
                    "end": "16:00",
                }
            }
        }
    )
    engine = RiskEngine(config=config)
    ny_tz = zoneinfo.ZoneInfo("America/New_York")

    # Time inside market hours: 10:00 AM NY
    in_time = datetime(2026, 8, 15, 10, 0, 0, tzinfo=ny_tz)
    check_in = MarketHoursCheck(now_fn=lambda: in_time)
    passed, reason = await check_in.validate(_signal(), engine)
    assert passed is True
    assert reason is None

    # Time outside market hours: 08:00 AM NY
    out_time = datetime(2026, 8, 15, 8, 0, 0, tzinfo=ny_tz)
    check_out = MarketHoursCheck(now_fn=lambda: out_time)
    passed, reason = await check_out.validate(_signal(), engine)
    assert passed is False
    assert reason == REASON_MARKET_CLOSED

    # Overnight schedule: 22:00 to 06:00
    overnight_config = ConfigManager(
        defaults={
            "risk": {
                "trading_schedule": {
                    "timezone": "UTC",
                    "start": "22:00",
                    "end": "06:00",
                }
            }
        }
    )
    overnight_engine = RiskEngine(config=overnight_config)
    night_time = datetime(2026, 8, 15, 23, 30, 0, tzinfo=UTC)
    day_time = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)

    check_night = MarketHoursCheck(now_fn=lambda: night_time)
    passed, _ = await check_night.validate(_signal(), overnight_engine)
    assert passed is True

    check_day = MarketHoursCheck(now_fn=lambda: day_time)
    passed, reason = await check_day.validate(_signal(), overnight_engine)
    assert passed is False
    assert reason == REASON_MARKET_CLOSED


@pytest.mark.asyncio
async def test_global_halt_check() -> None:
    config_halted = ConfigManager(defaults={"risk": {"global_halt": True}})
    engine_halted = RiskEngine(config=config_halted)
    check = GlobalHaltCheck()

    passed, reason = await check.validate(_signal(), engine_halted)
    assert passed is False
    assert reason == REASON_GLOBAL_HALT

    config_normal = ConfigManager(defaults={"risk": {"global_halt": False}})
    engine_normal = RiskEngine(config=config_normal)
    passed, reason = await check.validate(_signal(), engine_normal)
    assert passed is True
    assert reason is None


@pytest.mark.asyncio
async def test_position_size_limit_check() -> None:
    config = ConfigManager(
        defaults={
            "risk": {
                "max_position_qty": 5.0,
                "max_position_notional": 100000.0,
            }
        }
    )
    engine = RiskEngine(config=config)
    engine.market_prices["BTC/USDT"] = 20000.0
    check = PositionSizeLimitCheck()

    # Existing 3.0 BTC + 1.0 BTC = 4.0 <= 5.0 Qty
    # and 80,000 <= 100,000 Notional -> Approve
    engine.positions["BTC/USDT"] = 3.0
    passed, reason = await check.validate(
        _signal(symbol="BTC/USDT", quantity=1.0), engine
    )
    assert passed is True

    # 3.0 BTC + 3.0 BTC = 6.0 > 5.0 Qty -> Reject
    passed, reason = await check.validate(
        _signal(symbol="BTC/USDT", quantity=3.0), engine
    )
    assert passed is False
    assert reason == REASON_MAX_POSITION_SIZE

    # 1.0 BTC + 4.0 BTC = 5.0 BTC * 25,000 = 125,000 > 100,000 Notional -> Reject
    engine.positions["BTC/USDT"] = 1.0
    engine.market_prices["BTC/USDT"] = 25000.0
    passed, reason = await check.validate(
        _signal(symbol="BTC/USDT", quantity=4.0), engine
    )
    assert passed is False
    assert reason == REASON_MAX_POSITION_SIZE


@pytest.mark.asyncio
async def test_max_exposure_check() -> None:
    config = ConfigManager(defaults={"risk": {"max_total_exposure": 50000.0}})
    engine = RiskEngine(config=config)
    engine.positions["ETH/USDT"] = 10.0
    engine.market_prices["ETH/USDT"] = 2000.0  # 20,000 exposure
    engine.market_prices["BTC/USDT"] = 20000.0
    check = MaxExposureCheck()

    # Buy 1.0 BTC (20,000) -> Total = 20,000 + 20,000 = 40,000 <= 50,000 -> Approve
    passed, reason = await check.validate(
        _signal(symbol="BTC/USDT", quantity=1.0), engine
    )
    assert passed is True

    # Buy 2.0 BTC (40,000) -> Total = 40,000 + 20,000 = 60,000 > 50,000 -> Reject
    passed, reason = await check.validate(
        _signal(symbol="BTC/USDT", quantity=2.0), engine
    )
    assert passed is False
    assert reason == REASON_MAX_EXPOSURE


@pytest.mark.asyncio
async def test_daily_loss_limit_check() -> None:
    config = ConfigManager(defaults={"risk": {"max_daily_loss": 500.0}})
    engine = RiskEngine(config=config)
    check = DailyLossLimitCheck()

    # Realized loss -300 > -500 -> Approve
    engine.daily_realized_pnl = -300.0
    passed, reason = await check.validate(_signal(), engine)
    assert passed is True

    # Realized loss -600 <= -500 -> Reject
    engine.daily_realized_pnl = -600.0
    passed, reason = await check.validate(_signal(), engine)
    assert passed is False
    assert reason == REASON_DAILY_LOSS_LIMIT

    # New day rolls over -> Reset and Approve
    engine.current_day = "2020-01-01"
    passed, reason = await check.validate(_signal(), engine)
    assert passed is True
    assert engine.daily_realized_pnl == 0.0


@pytest.mark.asyncio
async def test_circuit_breaker_check_and_reset() -> None:
    config = ConfigManager(
        defaults={
            "risk": {
                "circuit_breaker_loss_count": 3,
                "circuit_breaker_emergency_threshold": 10000.0,
            }
        }
    )
    engine = RiskEngine(config=config)
    check = CircuitBreakerCheck()

    # 2 losses (window is 3) -> Approve
    engine.trade_pnl_history.append(-10.0)
    engine.trade_pnl_history.append(-20.0)
    passed, _ = await check.validate(_signal(), engine)
    assert passed is True

    # 3rd consecutive loss -> Trips and Rejects
    engine.trade_pnl_history.append(-30.0)
    passed, reason = await check.validate(_signal(), engine)
    assert passed is False
    assert reason == REASON_CIRCUIT_BREAKER
    assert engine.is_circuit_breaker_tripped() is True

    # Remains tripped on subsequent signals
    passed, reason = await check.validate(_signal(), engine)
    assert passed is False
    assert reason == REASON_CIRCUIT_BREAKER

    # Manual reset -> Resumes approving
    engine.reset_circuit_breaker()
    assert engine.is_circuit_breaker_tripped() is False
    passed, reason = await check.validate(_signal(), engine)
    assert passed is True


@pytest.mark.asyncio
async def test_circuit_breaker_severe_loss_triggers_emergency_stop() -> None:
    config = ConfigManager(
        defaults={
            "risk": {
                "circuit_breaker_loss_count": 2,
                "circuit_breaker_emergency_threshold": 1000.0,
            }
        }
    )
    engine = RiskEngine(config=config)
    check = CircuitBreakerCheck()

    engine.trade_pnl_history.append(-600.0)
    engine.trade_pnl_history.append(-600.0)  # sum = -1200 < -1000 threshold

    passed, reason = await check.validate(_signal(), engine)
    assert passed is False
    assert reason == REASON_CIRCUIT_BREAKER
    assert engine.is_emergency_stop_active() is True


@pytest.mark.asyncio
async def test_emergency_stop_check() -> None:
    engine = RiskEngine()
    check = EmergencyStopCheck()

    passed, reason = await check.validate(_signal(), engine)
    assert passed is True

    await engine.set_emergency_stop(True)
    assert engine.is_emergency_stop_active() is True

    passed, reason = await check.validate(_signal(), engine)
    assert passed is False
    assert reason == REASON_EMERGENCY_STOP

    await engine.set_emergency_stop(False)
    passed, reason = await check.validate(_signal(), engine)
    assert passed is True


# ── 2. Full Pipeline & EventBus Integration ───────────────────────


@pytest.mark.asyncio
async def test_full_pipeline_all_pass_publishes_approved() -> None:
    bus = AsyncEventBus()
    config = ConfigManager(
        defaults={
            "risk": {
                "allowed_symbols": ["BTC/USDT"],
                "max_position_qty": 10.0,
                "global_halt": False,
            }
        }
    )
    engine = RiskEngine(config=config, event_bus=bus)
    await engine.start()

    approved_events: list[ApprovedSignalEvent] = []
    rejected_events: list[RejectedSignalEvent] = []

    await bus.subscribe(ApprovedSignalEvent, lambda ev: approved_events.append(ev))
    await bus.subscribe(RejectedSignalEvent, lambda ev: rejected_events.append(ev))

    sig = _signal(symbol="BTC/USDT", quantity=1.0)
    await bus.publish(sig)
    await asyncio.sleep(0.05)

    assert len(approved_events) == 1
    assert approved_events[0].signal_id == sig.event_id
    assert approved_events[0].symbol == "BTC/USDT"
    assert len(rejected_events) == 0

    await engine.stop()


@pytest.mark.asyncio
async def test_full_pipeline_one_check_fails_publishes_rejected() -> None:
    bus = AsyncEventBus()
    config = ConfigManager(
        defaults={
            "risk": {
                "allowed_symbols": ["BTC/USDT"],
                "max_position_qty": 2.0,
            }
        }
    )
    engine = RiskEngine(config=config, event_bus=bus)
    await engine.start()

    approved_events: list[ApprovedSignalEvent] = []
    rejected_events: list[RejectedSignalEvent] = []

    await bus.subscribe(ApprovedSignalEvent, lambda ev: approved_events.append(ev))
    await bus.subscribe(RejectedSignalEvent, lambda ev: rejected_events.append(ev))

    # Signal exceeds position qty limit (5.0 > 2.0)
    sig = _signal(symbol="BTC/USDT", quantity=5.0)
    await bus.publish(sig)
    await asyncio.sleep(0.05)

    assert len(approved_events) == 0
    assert len(rejected_events) == 1
    assert rejected_events[0].signal_id == sig.event_id
    assert rejected_events[0].reason == REASON_MAX_POSITION_SIZE

    await engine.stop()


@pytest.mark.asyncio
async def test_full_pipeline_emergency_stop_rejects_immediately() -> None:
    bus = AsyncEventBus()
    config = ConfigManager(defaults={"risk": {"allowed_symbols": ["BTC/USDT"]}})
    engine = RiskEngine(config=config, event_bus=bus)
    await engine.start()
    await engine.set_emergency_stop(True)

    rejected_events: list[RejectedSignalEvent] = []
    await bus.subscribe(RejectedSignalEvent, lambda ev: rejected_events.append(ev))

    sig = _signal(symbol="BTC/USDT", quantity=1.0)
    await bus.publish(sig)
    await asyncio.sleep(0.05)

    assert len(rejected_events) == 1
    assert rejected_events[0].reason == REASON_EMERGENCY_STOP

    await engine.stop()


# ── 3. Fill and Portfolio Event Handling ──────────────────────────


@pytest.mark.asyncio
async def test_fill_event_updates_position_and_pnl() -> None:
    bus = AsyncEventBus()
    engine = RiskEngine(event_bus=bus)
    await engine.start()

    # Buy 2.0 BTC
    fill1 = FillEvent(
        order_id="o1",
        symbol="BTC/USDT",
        side="BUY",
        quantity=2.0,
        fill_price=50000.0,
        realized_pnl=0.0,
    )
    await bus.publish(fill1)
    await asyncio.sleep(0.05)

    assert engine.positions.get("BTC/USDT") == 2.0

    # Sell 1.0 BTC with realized loss -150.0
    fill2 = FillEvent(
        order_id="o2",
        symbol="BTC/USDT",
        side="SELL",
        quantity=1.0,
        fill_price=49850.0,
        realized_pnl=-150.0,
    )
    await bus.publish(fill2)
    await asyncio.sleep(0.05)

    assert engine.positions.get("BTC/USDT") == 1.0
    assert engine.daily_realized_pnl == -150.0
    assert list(engine.trade_pnl_history) == [-150.0]

    await engine.stop()


@pytest.mark.asyncio
async def test_portfolio_update_event_sync() -> None:
    bus = AsyncEventBus()
    engine = RiskEngine(event_bus=bus)
    await engine.start()

    port_ev = PortfolioUpdateEvent(
        cash=25000.0,
        total_value=75000.0,
        positions={"BTC/USDT": 1.0, "ETH/USDT": 5.0},
    )
    await bus.publish(port_ev)
    await asyncio.sleep(0.05)

    assert engine.cash == 25000.0
    assert engine.portfolio_value == 75000.0
    assert engine.positions == {"BTC/USDT": 1.0, "ETH/USDT": 5.0}

    await engine.stop()


# ── 4. Synchronous validate_order ─────────────────────────────────


def test_validate_order() -> None:
    config = ConfigManager(
        defaults={"risk": {"max_position_qty": 3.0, "global_halt": False}}
    )
    engine = RiskEngine(config=config)
    engine.positions["BTC/USDT"] = 1.0

    # Order within limits -> True
    valid_order = OrderEvent(
        strategy_id="s1",
        symbol="BTC/USDT",
        side="BUY",
        order_type="LIMIT",
        quantity=1.5,
        price=50000.0,
    )
    assert engine.validate_order(valid_order) is True

    # Order exceeds limit (1.0 + 3.0 = 4.0 > 3.0) -> False
    invalid_order = OrderEvent(
        strategy_id="s1",
        symbol="BTC/USDT",
        side="BUY",
        order_type="LIMIT",
        quantity=3.0,
        price=50000.0,
    )
    assert engine.validate_order(invalid_order) is False

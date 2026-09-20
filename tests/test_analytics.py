"""Test suite for QuantFlow Analytics module."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from quantflow.analytics.aggregators import (
    DrawdownTracker,
    IncrementalAnalyticsCalculator,
    TradeStatsAggregator,
    WelfordOnline,
)
from quantflow.analytics.batch import BatchAnalyticsCalculator
from quantflow.analytics.engine import AnalyticsEngine
from quantflow.analytics.formulas import (
    calculate_avg_latency,
    calculate_avg_slippage,
    calculate_avg_trade,
    calculate_downside_deviation,
    calculate_drawdowns,
    calculate_mean,
    calculate_profit_factor,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_stddev,
    calculate_variance,
    calculate_win_rate,
    daily_return,
    daily_returns_from_equity_curve,
)
from quantflow.common.events import EventType, FillEvent, PortfolioUpdateEvent
from quantflow.config.manager import ConfigManager
from quantflow.core.event_bus import AsyncEventBus

# ── 1. Pure Formula Tests with Hand-Calculated Fixtures ────────────


def test_daily_returns_calculation() -> None:
    """Verify daily percentage return formula."""
    assert daily_return(1050.0, 1000.0) == pytest.approx(0.05)
    assert daily_return(1020.0, 1050.0) == pytest.approx(-30.0 / 1050.0)
    assert daily_return(100.0, 0.0) == 0.0

    equities = [1000.0, 1050.0, 1020.0, 1080.0, 1100.0]
    expected_returns = [
        0.05,
        -30.0 / 1050.0,
        60.0 / 1020.0,
        20.0 / 1080.0,
    ]
    computed = daily_returns_from_equity_curve(equities)
    assert len(computed) == 4
    for c, e in zip(computed, expected_returns, strict=True):
        assert c == pytest.approx(e)


def test_mean_variance_stddev_pure_formulas() -> None:
    """Verify pure mean, sample variance, and sample stddev against known values."""
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    # Sum = 40, Mean = 5.0
    # Squared diffs: (2-5)^2 + 3*(4-5)^2 + 2*(5-5)^2 + (7-5)^2 + (9-5)^2 = 32
    # Sample variance (N-1 = 7) = 32 / 7 = 4.571428571428571
    # Sample stddev = sqrt(32/7) = 2.138089935299395
    assert calculate_mean(values) == pytest.approx(5.0)
    assert calculate_variance(values, ddof=1) == pytest.approx(32.0 / 7.0)
    assert calculate_stddev(values, ddof=1) == pytest.approx(math.sqrt(32.0 / 7.0))


def test_drawdowns_pure_formula() -> None:
    """Verify running and max drawdown calculation for a known multi-peak curve."""
    # Peak: 100 -> 120 -> 90 (25% DD) -> 150 -> 120 (20% DD)
    equities = [100.0, 110.0, 120.0, 96.0, 90.0, 130.0, 150.0, 120.0]
    # Max DD is at 90: (120 - 90)/120 = 30/120 = 0.25 (25%)
    # Current DD is at 120: (150 - 120)/150 = 30/150 = 0.20 (20%)
    max_dd, current_dd = calculate_drawdowns(equities)
    assert max_dd == pytest.approx(0.25)
    assert current_dd == pytest.approx(0.20)


def test_sharpe_and_sortino_ratios() -> None:
    """Verify Sharpe and Sortino ratios with risk-free rate and annualization."""
    returns = [0.01, 0.02, -0.01, 0.03, -0.02, 0.01]
    mean_r = calculate_mean(returns)
    std_r = calculate_stddev(returns)
    downside_std = calculate_downside_deviation(returns, target=mean_r)

    rf = 0.001
    ann_factor = 252.0

    sharpe = calculate_sharpe_ratio(
        mean_r, std_r, risk_free_rate=rf, annualization_factor=ann_factor
    )
    sortino = calculate_sortino_ratio(
        mean_r,
        downside_std,
        risk_free_rate=rf,
        annualization_factor=ann_factor,
    )

    expected_sharpe = ((mean_r - rf) / std_r) * math.sqrt(ann_factor)
    expected_sortino = ((mean_r - rf) / downside_std) * math.sqrt(ann_factor)

    assert sharpe == pytest.approx(expected_sharpe)
    assert sortino == pytest.approx(expected_sortino)

    # Zero stddev fallback
    assert calculate_sharpe_ratio(0.05, 0.0) == 0.0
    assert calculate_sortino_ratio(0.05, 0.0) == 0.0


def test_trade_metrics_pure_formulas() -> None:
    """Verify trade performance formulas with hand-computed values."""
    # 5 trades: 3 wins (100, 80, 60), 2 losses (-40, -20)
    assert calculate_win_rate(3, 5) == pytest.approx(0.60)
    assert calculate_profit_factor(240.0, 60.0) == pytest.approx(4.0)
    assert calculate_avg_trade(180.0, 5) == pytest.approx(36.0)
    assert calculate_avg_slippage(1.5, 5) == pytest.approx(0.3)
    assert calculate_avg_latency(0.090, 5) == pytest.approx(0.018)

    # Edge cases
    assert calculate_win_rate(0, 0) == 0.0
    assert calculate_profit_factor(100.0, 0.0) == float("inf")
    assert calculate_profit_factor(0.0, 0.0) == 0.0
    assert calculate_avg_trade(0.0, 0) == 0.0
    assert calculate_avg_slippage(0.0, 0) == 0.0
    assert calculate_avg_latency(0.0, 0) == 0.0


# ── 2. Aggregators Unit Tests ─────────────────────────────────────


def test_welford_online_matches_exact_sample_statistics() -> None:
    """Verify WelfordOnline matches pure sample mean and standard deviation."""

    samples = [1.2, -0.5, 3.4, 0.8, -2.1, 4.5, 1.0, 0.2]
    welford = WelfordOnline()
    for x in samples:
        welford.update(x)

    assert welford.n == len(samples)
    assert welford.mean == pytest.approx(calculate_mean(samples))
    assert welford.variance() == pytest.approx(calculate_variance(samples, ddof=1))
    assert welford.stddev() == pytest.approx(calculate_stddev(samples, ddof=1))


def test_drawdown_tracker_incremental_updates() -> None:
    """Verify DrawdownTracker handles peak resets and max drawdown progression."""
    tracker = DrawdownTracker(initial_equity=100.0)
    assert tracker.peak == 100.0
    assert tracker.max_drawdown == 0.0

    tracker.update(120.0)
    assert tracker.peak == 120.0
    assert tracker.current_drawdown == 0.0

    tracker.update(90.0)
    assert tracker.peak == 120.0
    assert tracker.current_drawdown == pytest.approx(0.25)
    assert tracker.max_drawdown == pytest.approx(0.25)

    tracker.update(110.0)
    assert tracker.peak == 120.0
    assert tracker.current_drawdown == pytest.approx((120.0 - 110.0) / 120.0)
    assert tracker.max_drawdown == pytest.approx(0.25)


def test_trade_stats_aggregator() -> None:
    """Verify TradeStatsAggregator accumulators and computed properties."""
    agg = TradeStatsAggregator()
    agg.add_trade(pnl=100.0, slippage=0.5, latency=0.01)
    agg.add_trade(pnl=-40.0, slippage=0.2, latency=0.02)
    agg.add_trade(pnl=80.0, slippage=0.3, latency=0.015)
    agg.add_trade(pnl=-20.0, slippage=0.0, latency=0.035)
    agg.add_trade(pnl=60.0, slippage=0.5, latency=0.01)

    assert agg.total_trades == 5
    assert agg.winning_trades == 3
    assert agg.win_rate == pytest.approx(0.60)
    assert agg.profit_factor == pytest.approx(4.0)
    assert agg.avg_trade == pytest.approx(36.0)
    assert agg.avg_slippage == pytest.approx(0.30)
    assert agg.avg_latency == pytest.approx(0.018)


# ── 3. Critical Parity Test: Incremental vs Batch vs Engine ───────


def test_incremental_and_batch_exact_numerical_parity() -> None:
    """CRITICAL TEST: Verify incremental, batch, and engine parity."""
    base_time = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)

    # 10 days of historical equity with fluctuations
    equity_values = [
        100000.0,
        102500.0,
        101000.0,
        104000.0,
        103500.0,
        106000.0,
        105000.0,
        108000.0,
        107500.0,
        110000.0,
    ]
    equity_curve = [
        (base_time + timedelta(days=i), val) for i, val in enumerate(equity_values)
    ]

    trades: list[tuple[float, float | None, float | None]] = [
        (1500.0, 2.5, 0.012),
        (-600.0, 1.0, 0.015),
        (2200.0, 3.0, 0.010),
        (-800.0, 0.5, 0.020),
        (1800.0, 1.5, 0.014),
    ]

    rf_rate = 0.02
    ann_factor = 252.0

    # 1. Batch Calculator
    batch_calc = BatchAnalyticsCalculator(
        risk_free_rate=rf_rate, annualization_factor=ann_factor
    )
    batch_metrics = batch_calc.compute_metrics_from_history(
        equity_curve=equity_curve, trades=trades
    )

    # 2. Analytics Engine (Bulk Loading)
    config = ConfigManager(
        defaults={
            "analytics": {
                "risk_free_rate": rf_rate,
                "annualization_factor": ann_factor,
            }
        }
    )
    event_bus = AsyncEventBus()
    engine = AnalyticsEngine(config=config, event_bus=event_bus)
    engine.load_historical_equity(equity_curve)
    engine.load_historical_trades(trades)
    engine_metrics = engine.get_metrics()

    # 3. Incremental Calculator (Simulating live streaming ticks)
    incremental_calc = IncrementalAnalyticsCalculator(
        risk_free_rate=rf_rate, annualization_factor=ann_factor
    )
    for i, (_, eq) in enumerate(equity_curve):
        if i == 0:
            incremental_calc.update_equity(eq)
        else:
            prev = equity_curve[i - 1][1]
            ret = daily_return(eq, prev)
            incremental_calc.add_daily_return(ret)
            incremental_calc.update_equity(eq)

    for pnl, slip, lat in trades:
        incremental_calc.add_trade(pnl, slip, lat)

    incremental_metrics = incremental_calc.get_metrics()

    # Assert 100% equivalence across all computed metrics
    all_keys = (
        set(batch_metrics.keys())
        | set(engine_metrics.keys())
        | set(incremental_metrics.keys())
    )
    assert len(all_keys) >= 11

    for k in all_keys:
        assert k in batch_metrics, f"Missing {k} in batch_metrics"
        assert k in engine_metrics, f"Missing {k} in engine_metrics"
        assert k in incremental_metrics, f"Missing {k} in incremental_metrics"

        b_val = batch_metrics[k]
        e_val = engine_metrics[k]
        i_val = incremental_metrics[k]

        assert b_val == pytest.approx(e_val, abs=1e-9), (
            f"Batch vs Engine mismatch on {k}"
        )
        assert b_val == pytest.approx(i_val, abs=1e-9), (
            f"Batch vs Incremental mismatch on {k}"
        )


# ── 4. Live Event-Driven AnalyticsEngine Tests ─────────────────────


@pytest.mark.asyncio
async def test_analytics_engine_event_streaming() -> None:
    """Verify AnalyticsEngine processes PortfolioUpdateEvent and FillEvent."""
    config = ConfigManager(
        defaults={
            "analytics": {
                "risk_free_rate": 0.0,
                "annualization_factor": 252.0,
            }
        }
    )
    event_bus = AsyncEventBus()
    engine = AnalyticsEngine(config=config, event_bus=event_bus)

    await engine.start()

    base_time = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

    # Publish portfolio updates across days
    e0 = PortfolioUpdateEvent(
        cash=100000.0,
        total_value=100000.0,
        timestamp=base_time,
    )
    await event_bus.publish(e0)

    e1 = PortfolioUpdateEvent(
        cash=105000.0,
        total_value=105000.0,
        timestamp=base_time + timedelta(days=1),
    )
    await event_bus.publish(e1)

    e2 = PortfolioUpdateEvent(
        cash=102000.0,
        total_value=102000.0,
        timestamp=base_time + timedelta(days=2),
    )
    await event_bus.publish(e2)

    # Publish fills
    f1 = FillEvent(
        order_id="order-1",
        symbol="BTC/USDT",
        side="BUY",
        quantity=1.0,
        fill_price=50000.0,
        realized_pnl=500.0,
    )
    await event_bus.publish(f1)

    f2 = FillEvent(
        order_id="order-2",
        symbol="BTC/USDT",
        side="SELL",
        quantity=1.0,
        fill_price=50100.0,
        realized_pnl=-200.0,
    )
    await event_bus.publish(f2)

    metrics = engine.get_metrics()

    assert metrics["total_trades"] == 2.0
    assert metrics["win_rate"] == pytest.approx(0.5)
    assert metrics["profit_factor"] == pytest.approx(500.0 / 200.0)
    assert metrics["total_return"] == pytest.approx(0.02)
    assert metrics["max_drawdown"] == pytest.approx((105000.0 - 102000.0) / 105000.0)

    curve = engine.get_equity_curve()
    assert len(curve) == 3
    assert curve[0][1] == 100000.0
    assert curve[1][1] == 105000.0
    assert curve[2][1] == 102000.0

    await engine.stop()


@pytest.mark.asyncio
async def test_analytics_engine_slippage_and_latency() -> None:
    """Verify slippage and latency metrics through event streaming."""
    config = ConfigManager(
        defaults={
            "analytics": {
                "risk_free_rate": 0.01,
                "annualization_factor": 252.0,
            }
        }
    )
    event_bus = AsyncEventBus()
    engine = AnalyticsEngine(config=config, event_bus=event_bus)
    await engine.start()

    base_time = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)

    # Portfolio baseline
    await event_bus.publish(
        PortfolioUpdateEvent(cash=100000.0, total_value=100000.0, timestamp=base_time)
    )

    # Trade 1: Fill with expected_price in metadata and latency
    t_exch1 = base_time + timedelta(seconds=1)
    t_recv1 = t_exch1 + timedelta(milliseconds=25)  # 25ms latency
    f1 = FillEvent(
        order_id="o-1",
        symbol="BTC/USDT",
        side="BUY",
        quantity=1.0,
        fill_price=50005.0,
        realized_pnl=250.0,
        metadata={"expected_price": 50000.0},  # 5.0 slippage
        timestamp_exchange=t_exch1,
        timestamp_received=t_recv1,
    )
    await event_bus.publish(f1)

    # Trade 2: Fill with expected_price as direct field and latency
    t_exch2 = base_time + timedelta(seconds=2)
    t_recv2 = t_exch2 + timedelta(milliseconds=15)  # 15ms latency
    f2 = FillEvent(
        order_id="o-2",
        symbol="BTC/USDT",
        side="SELL",
        quantity=1.0,
        fill_price=49998.0,
        realized_pnl=150.0,
        expected_price=50000.0,  # -2.0 slippage
        timestamp_exchange=t_exch2,
        timestamp_received=t_recv2,
    )
    await event_bus.publish(f2)

    metrics = engine.get_metrics()
    assert metrics["total_trades"] == 2.0
    assert metrics["win_rate"] == 1.0
    # Average slippage: (5.0 + (-2.0)) / 2 = 1.5
    assert metrics["avg_slippage"] == pytest.approx(1.5)
    # Average latency: (0.025 + 0.015) / 2 = 0.020
    assert metrics["avg_latency"] == pytest.approx(0.020)

    await engine.stop()


def test_analytics_engine_reset() -> None:
    """Verify reset clears all accumulated metrics and equity curve."""
    config = ConfigManager()
    event_bus = AsyncEventBus()
    engine = AnalyticsEngine(config=config, event_bus=event_bus)

    base_time = datetime(2026, 8, 1, tzinfo=UTC)
    engine.load_historical_equity(
        [(base_time, 100000.0), (base_time + timedelta(days=1), 105000.0)]
    )
    engine.load_historical_trades([(500.0, 1.0, 0.02)])

    m1 = engine.get_metrics()
    assert m1["total_trades"] == 1.0
    assert len(engine.get_equity_curve()) == 2

    engine.reset()
    m2 = engine.get_metrics()
    assert m2["total_trades"] == 0.0
    assert m2["win_rate"] == 0.0
    assert len(engine.get_equity_curve()) == 0
    assert engine.initial_equity is None
    assert engine.last_equity is None


def test_config_manager_get_float_int_bool() -> None:
    """Verify ConfigManager typed getters for analytics and system configs."""
    cfg = ConfigManager(
        defaults={
            "analytics": {
                "risk_free_rate": "0.025",
                "annualization_factor": 252,
            },
            "enabled": "true",
            "disabled": "false",
        }
    )
    assert cfg.get_float("analytics.risk_free_rate") == 0.025
    assert cfg.get_float("analytics.missing", 0.05) == 0.05
    assert cfg.get_int("analytics.annualization_factor") == 252
    assert cfg.get_int("analytics.missing_int", 10) == 10
    assert cfg.get_bool("enabled") is True
    assert cfg.get_bool("disabled") is False
    assert cfg.get_bool("missing_bool", True) is True


@pytest.mark.asyncio
async def test_event_type_aliases_subscription() -> None:
    """Verify EventType constants match event classes for subscription."""
    assert EventType.PORTFOLIO_UPDATE is PortfolioUpdateEvent
    assert EventType.FILL is FillEvent

    event_bus = AsyncEventBus()
    received: list[PortfolioUpdateEvent] = []

    async def on_portfolio(event: PortfolioUpdateEvent) -> None:
        received.append(event)

    await event_bus.subscribe(EventType.PORTFOLIO_UPDATE, on_portfolio)
    e = PortfolioUpdateEvent(cash=1000.0, total_value=1000.0)
    await event_bus.publish(e)

    assert len(received) == 1
    assert received[0].payload.total_equity == 1000.0


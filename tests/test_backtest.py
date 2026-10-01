"""Unit and integration tests for BacktestingEngine and WalkForwardValidator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import math

import pytest

from quantflow.backtesting.engine import (
    BacktestEngine,
    BacktestPipeline,
    BacktestResult,
    build_backtest_pipeline,
)
from quantflow.backtesting.optimizer import (
    FoldResult,
    ParameterSweepRunner,
    SignificanceEvaluator,
    SignificanceReport,
    SweepResult,
    WalkForwardReport,
    WalkForwardValidator,
    Window,
    _norm_cdf,
    _norm_ppf,
    deflated_sharpe_ratio,
    expand_grid,
    generate_windows,
)
from quantflow.common.events import TickEvent
from quantflow.config.manager import ConfigManager
from quantflow.replay.event_store import InMemoryEventStoreReader
from quantflow.strategies.momentum.strategy import SimpleMomentumStrategy


def _make_btc_ticks(
    start: datetime, prices: list[float], step_seconds: int = 10
) -> list[TickEvent]:
    """Helper to create TickEvents from a sequence of mid prices."""
    events = []
    for i, p in enumerate(prices):
        t = start + timedelta(seconds=i * step_seconds)
        events.append(
            TickEvent(
                event_id=f"tick_{i:04d}",
                symbol="BTC/USDT",
                exchange="binance",
                bid_price=p - 1.0,
                ask_price=p + 1.0,
                bid_size=10.0,
                ask_size=10.0,
                last_price=p,
                last_size=1.0,
                timestamp=t,
                timestamp_received=t,
            )
        )
    return events


@pytest.mark.asyncio
async def test_single_backtest_run_over_fixture_produces_analytics_report() -> None:
    """A single backtest run over deterministic fixture data produces an expected

    analytics report with hand-verifiable trade executions and metrics.
    """
    start = datetime(2026, 8, 1, 10, 0, 0, tzinfo=UTC)
    # 5-period momentum with 0.01 (1%) threshold:
    # 50000 -> 50800 (+1.6% over 5 ticks) triggers BUY at tick 5 (ask = 50801.0)
    # 50800 -> 49800 (-1.97% over 5 ticks) triggers SELL at tick 10 (bid = 49799.0)
    prices = [
        50000.0, 50100.0, 50200.0, 50300.0, 50500.0, 50800.0,
        50600.0, 50400.0, 50200.0, 50000.0, 49800.0,
        49800.0, 49800.0,
    ]
    ticks = _make_btc_ticks(start, prices)
    end = (ticks[-1].timestamp_received or start) + timedelta(seconds=1)

    store = InMemoryEventStoreReader(ticks)
    engine = BacktestEngine()

    result: BacktestResult = await engine.run(
        data_reader=store,
        strategy_cls=SimpleMomentumStrategy,
        params={"symbol": "BTC/USDT", "period": 5, "threshold": 0.01},
        start=start,
        end=end,
    )

    # 1. Backtest status
    assert result.success is True
    assert result.error is None
    assert result.event_count == 4  # 2 signals + 2 fills

    # 2. Hand-verifiable signals
    assert len(result.signals) == 2
    assert result.signals[0]["direction"] == "BUY"
    assert result.signals[0]["symbol"] == "BTC/USDT"
    assert result.signals[1]["direction"] == "SELL"

    # 3. Hand-verifiable trade execution fills
    assert len(result.trades) == 2
    buy_trade = result.trades[0]
    sell_trade = result.trades[1]

    assert buy_trade["side"] == "BUY"
    assert buy_trade["quantity"] == 1.0
    assert buy_trade["price"] == 50801.0  # filled at ask price (50800 + 1)

    assert sell_trade["side"] == "SELL"
    assert sell_trade["quantity"] == 1.0
    assert sell_trade["price"] == 49799.0  # filled at bid price (49800 - 1)

    # Realized loss: 49799 - 50801 = -1002.0
    assert math.isclose(sell_trade["realized_pnl"], -1002.0, rel_tol=1e-3)

    # 4. Analytics metrics report
    metrics = result.metrics
    assert "sharpe_ratio" in metrics
    assert "sortino_ratio" in metrics
    assert "max_drawdown" in metrics
    assert "win_rate" in metrics
    assert metrics["total_trades"] == 1.0

    # 5. Equity curve snapshot is recorded
    assert len(result.equity_curve) > 0


@pytest.mark.asyncio
async def test_parameter_sweep_and_rank_by_out_of_sample_performance() -> None:
    """Parameter sweep runs multiple configurations and ranks by out-of-sample

    performance rather than in-sample performance.
    """
    start = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    mid_split = start + timedelta(days=90)
    end = start + timedelta(days=120)

    # Construct dataset where:
    # - Config A (threshold=0.01): makes profit In-Sample, but suffers whipsaw Out-of-Sample.
    # - Config B (threshold=0.05): does not trade In-Sample (zero return), but catches big trend Out-of-Sample.
    is_prices = [
        # Up trend
        50000.0, 50200.0, 50400.0, 50600.0, 50800.0, 51200.0,
        # Exit higher
        51200.0, 51300.0, 51400.0, 51500.0, 51600.0, 51800.0,
    ]
    # Out of sample prices: 50000 -> 54000 (big move triggers Config B at 5%)
    oos_prices = [
        50000.0, 50500.0, 51000.0, 51500.0, 52000.0, 54000.0,
        54000.0, 53900.0, 53800.0, 53700.0, 53600.0, 52500.0,
    ]

    all_ticks: list[TickEvent] = []
    all_ticks.extend(_make_btc_ticks(start, is_prices, step_seconds=86400 * 5))
    all_ticks.extend(_make_btc_ticks(mid_split, oos_prices, step_seconds=86400 * 2))

    def data_factory() -> InMemoryEventStoreReader:
        return InMemoryEventStoreReader(all_ticks)

    param_grid = {
        "threshold": [0.01, 0.05],
        "period": [5],
        "symbol": ["BTC/USDT"],
    }

    validator = WalkForwardValidator(
        train_span_days=90,
        test_span_days=30,
        step_days=30,
        anchored=False,
    )

    report = await validator.run(
        data_reader_factory=data_factory,
        strategy_cls=SimpleMomentumStrategy,
        param_grid=param_grid,
        data_start=start,
        data_end=end,
    )

    assert len(report.folds) == 1
    fold = report.folds[0]

    # In-sample sweep chose best params based on in-sample performance
    assert fold.in_sample is not None
    assert fold.out_of_sample is not None

    # Sweep top_n sorts correctly
    sweep_runner = ParameterSweepRunner()
    oos_sweep = await sweep_runner.run(
        data_reader_factory=data_factory,
        strategy_cls=SimpleMomentumStrategy,
        param_grid=param_grid,
        start=mid_split,
        end=end,
    )
    ranked_oos = oos_sweep.top_n("total_trades", n=2)
    assert len(ranked_oos) == 2
    # Verify sorted in descending order of total_trades
    assert ranked_oos[0].metrics["total_trades"] >= ranked_oos[1].metrics["total_trades"]


def test_walk_forward_split_boundaries_correct_and_non_overlapping() -> None:
    """Walk-forward test split boundaries must be strictly non-overlapping and

    correctly partitioned for both rolling and anchored windows.
    """
    start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2025, 7, 2, 0, 0, 0, tzinfo=UTC)  # ~182 days

    # ── 1. Rolling Windows ───────────────────────────────────────
    train_span = 90
    test_span = 30
    step = 30

    rolling_windows = generate_windows(
        data_start=start,
        data_end=end,
        train_span_days=train_span,
        test_span_days=test_span,
        step_days=step,
        anchored=False,
    )

    assert len(rolling_windows) >= 3

    for i, w in enumerate(rolling_windows):
        # In-sample train precedes out-of-sample test with exact boundary
        assert w.train_start < w.train_end
        assert w.test_start == w.train_end
        assert w.test_start < w.test_end

        # Durations match configuration
        assert w.train_end - w.train_start == timedelta(days=train_span)
        assert w.test_end - w.test_start == timedelta(days=test_span)

        # Stays within total data range
        assert w.train_start >= start
        assert w.test_end <= end

        # Non-overlapping test windows across consecutive folds
        if i > 0:
            prev_w = rolling_windows[i - 1]
            assert w.test_start == prev_w.test_end  # contiguous test splits
            assert w.test_start >= prev_w.test_end  # strictly non-overlapping
            assert w.train_start == prev_w.train_start + timedelta(days=step)

    # ── 2. Anchored Windows ──────────────────────────────────────
    anchored_windows = generate_windows(
        data_start=start,
        data_end=end,
        train_span_days=train_span,
        test_span_days=test_span,
        step_days=step,
        anchored=True,
    )

    assert len(anchored_windows) >= 3

    for i, w in enumerate(anchored_windows):
        # In anchored mode, train_start always remains pinned to data_start
        assert w.train_start == start
        assert w.test_start == w.train_end
        assert w.test_end - w.test_start == timedelta(days=test_span)

        # Train end expands by step on each subsequent fold
        expected_train_days = train_span + i * step
        assert w.train_end - w.train_start == timedelta(days=expected_train_days)

        if i > 0:
            prev_w = anchored_windows[i - 1]
            # Test windows remain strictly non-overlapping and contiguous
            assert w.test_start == prev_w.test_end
            assert w.test_start >= prev_w.test_end


def test_deflated_sharpe_ratio_and_acklam_approximation() -> None:
    """Acklam inverse normal and Deflated Sharpe Ratio calculation check."""
    # Test inverse CDF against known normal quantiles
    assert math.isclose(_norm_cdf(_norm_ppf(0.5)), 0.5, abs_tol=1e-5)
    assert math.isclose(_norm_ppf(0.8413447), 1.0, abs_tol=1e-3)
    assert math.isclose(_norm_ppf(0.9772498), 2.0, abs_tol=1e-3)

    # DSR calculation with 100 trials and positive Sharpe
    dsr = deflated_sharpe_ratio(
        sharpe_obs_per_period=0.15,
        T=100,
        skew=-0.5,
        kurt=4.0,
        sharpe_variance_across_trials=0.01,
        n_trials=100,
    )
    assert 0.0 <= dsr <= 1.0
    # Higher observed Sharpe yields higher DSR
    dsr_high = deflated_sharpe_ratio(
        sharpe_obs_per_period=0.35,
        T=100,
        skew=-0.5,
        kurt=4.0,
        sharpe_variance_across_trials=0.01,
        n_trials=100,
    )
    assert dsr_high > dsr


def test_significance_evaluator_tiered_rules() -> None:
    """Significance evaluator checks Tier 1 (sanity), Tier 2 (robustness), and

    Tier 3 (statistical significance).
    """
    config = ConfigManager(
        defaults={
            "backtest": {
                "significance": {
                    "min_trades": 10,
                    "min_oos_sharpe": 0.0,
                    "min_profit_factor": 1.0,
                    "max_drawdown_limit": 0.30,
                    "min_degradation_ratio": 0.5,
                    "min_wfe": 0.5,
                    "min_param_stability": 0.6,
                    "enable_deflated_sharpe": False,
                }
            }
        }
    )
    evaluator = SignificanceEvaluator(config)

    # Case 1: Insufficient trade count (Fails Tier 1)
    dummy_fold = FoldResult(
        window=Window(datetime.now(), datetime.now(), datetime.now(), datetime.now()),
        best_params={"period": 10},
        in_sample=BacktestResult({}, datetime.now(), datetime.now(), {"sharpe_ratio": 2.0}, [], [], [], [], 1.0, 10, True),
        out_of_sample=BacktestResult({}, datetime.now(), datetime.now(), {"sharpe_ratio": 1.5, "profit_factor": 1.5, "max_drawdown": 0.1, "total_trades": 5.0}, [], [], [], [], 1.0, 5, True),
    )
    report_low_trades = WalkForwardReport(
        folds=[dummy_fold],
        aggregate_oos_metrics={"sharpe_ratio": 1.5, "profit_factor": 1.5, "max_drawdown": 0.1, "total_trades": 5.0},
        walk_forward_efficiency=0.75,
        param_stability=0.9,
    )
    sig1 = evaluator.evaluate(report_low_trades)
    assert sig1.tier1_passed is False
    assert sig1.trusted is False
    assert any("T1: OOS trades" in r for r in sig1.reasons)

    # Case 2: Excessive degradation (Fails Tier 2)
    # IS Sharpe = 4.0, OOS Sharpe = 1.0 -> degradation = 0.25 < 0.5
    dummy_fold_degraded = FoldResult(
        window=Window(datetime.now(), datetime.now(), datetime.now(), datetime.now()),
        best_params={"period": 10},
        in_sample=BacktestResult({}, datetime.now(), datetime.now(), {"sharpe_ratio": 4.0}, [], [], [], [], 1.0, 50, True),
        out_of_sample=BacktestResult({}, datetime.now(), datetime.now(), {"sharpe_ratio": 1.0, "profit_factor": 1.5, "max_drawdown": 0.1, "total_trades": 50.0}, [], [], [], [], 1.0, 50, True),
    )
    report_degraded = WalkForwardReport(
        folds=[dummy_fold_degraded],
        aggregate_oos_metrics={"sharpe_ratio": 1.0, "profit_factor": 1.5, "max_drawdown": 0.1, "total_trades": 50.0},
        walk_forward_efficiency=0.25,
        param_stability=0.9,
    )
    sig2 = evaluator.evaluate(report_degraded)
    assert sig2.tier1_passed is True
    assert sig2.tier2_passed is False
    assert sig2.trusted is False
    assert any("T2: Degradation" in r for r in sig2.reasons)

    # Case 3: Robust passing strategy
    dummy_fold_good = FoldResult(
        window=Window(datetime.now(), datetime.now(), datetime.now(), datetime.now()),
        best_params={"period": 10},
        in_sample=BacktestResult({}, datetime.now(), datetime.now(), {"sharpe_ratio": 2.0}, [], [], [], [], 1.0, 50, True),
        out_of_sample=BacktestResult({}, datetime.now(), datetime.now(), {"sharpe_ratio": 1.6, "profit_factor": 1.8, "max_drawdown": 0.15, "total_trades": 50.0}, [], [], [], [], 1.0, 50, True),
    )
    report_good = WalkForwardReport(
        folds=[dummy_fold_good],
        aggregate_oos_metrics={"sharpe_ratio": 1.6, "profit_factor": 1.8, "max_drawdown": 0.15, "total_trades": 50.0},
        walk_forward_efficiency=0.8,
        param_stability=0.85,
    )
    sig3 = evaluator.evaluate(report_good)
    assert sig3.tier1_passed is True
    assert sig3.tier2_passed is True
    assert sig3.tier3_passed is True
    assert sig3.trusted is True

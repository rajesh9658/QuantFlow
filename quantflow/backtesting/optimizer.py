"""Parameter sweep, walk-forward validation, and significance evaluation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import itertools
import math
from typing import Any

from quantflow.backtesting.engine import BacktestEngine, BacktestResult
from quantflow.config.manager import ConfigManager
from quantflow.core.interfaces import Strategy
from quantflow.core.logging import get_logger
from quantflow.replay.event_store import EventStoreReader

logger = get_logger("backtest_optimizer")


@dataclass
class Window:
    """Train and test time windows for a single fold."""

    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


@dataclass
class FoldResult:
    """Result of in-sample training and out-of-sample evaluation for one fold."""

    window: Window
    best_params: dict[str, Any]
    in_sample: BacktestResult
    out_of_sample: BacktestResult


@dataclass
class SignificanceReport:
    """Tiered validation report: Sanity (T1) -> Robustness (T2) -> Statistical (T3)."""

    tier1_passed: bool
    tier2_passed: bool
    tier3_passed: bool
    trusted: bool

    # Diagnostics
    oos_trades: int
    oos_sharpe: float
    is_sharpe: float
    degradation_ratio: float
    wfe: float
    stability: float
    deflated_sharpe: float | None

    reasons: list[str]


@dataclass
class WalkForwardReport:
    """Complete report across all walk-forward folds."""

    folds: list[FoldResult]
    aggregate_oos_metrics: dict[str, float]
    walk_forward_efficiency: float
    param_stability: float
    significance: SignificanceReport | None = None

    def rank_by_oos(
        self,
        metric: str = "sharpe_ratio",
        maximize: bool = True,
    ) -> list[FoldResult]:
        """Rank fold results by out-of-sample performance metric."""
        return sorted(
            self.folds,
            key=lambda f: f.out_of_sample.metrics.get(
                metric, float("-inf") if maximize else float("inf")
            ),
            reverse=maximize,
        )


@dataclass
class SweepResult:
    """Aggregated results from a parameter sweep."""

    results: list[BacktestResult]
    param_grid: dict[str, list[Any]]

    def top_n(
        self,
        metric: str,
        n: int = 10,
        maximize: bool = True,
    ) -> list[BacktestResult]:
        """Return top-N results sorted by specified metric."""
        sorted_results = sorted(
            self.results,
            key=lambda r: r.metrics.get(
                metric, float("-inf") if maximize else float("inf")
            ),
            reverse=maximize,
        )
        return sorted_results[:n]


def expand_grid(param_grid: dict[str, list[Any]]) -> Iterator[dict[str, Any]]:
    """Cartesian product of parameter grid -> iterator of parameter dicts."""
    keys = list(param_grid.keys())
    for combo in itertools.product(*[param_grid[k] for k in keys]):
        yield dict(zip(keys, combo))


def _run_backtest_sync(
    config_dict: dict[str, Any],
    data_reader_factory: Callable[[], EventStoreReader],
    strategy_cls: type[Strategy],
    params: dict[str, Any],
    start: datetime,
    end: datetime,
) -> BacktestResult:
    """Sync wrapper executed in a subprocess. Creates a fresh event loop."""
    config = ConfigManager(defaults=config_dict)
    reader = data_reader_factory()
    engine = BacktestEngine(config)
    return asyncio.run(engine.run(reader, strategy_cls, params, start, end))


class ParameterSweepRunner:
    """Runs a parameter sweep over a single train window.

    Supports ProcessPoolExecutor for CPU-bound backtests with robust fallback.
    """

    def __init__(
        self,
        base_config: ConfigManager | None = None,
        max_workers: int | None = None,
    ) -> None:
        self.config = base_config if base_config is not None else ConfigManager()
        self.max_workers = max_workers

    async def run(
        self,
        data_reader_factory: Callable[[], EventStoreReader],
        strategy_cls: type[Strategy],
        param_grid: dict[str, list[Any]],
        start: datetime,
        end: datetime,
        max_combinations: int | None = None,
    ) -> SweepResult:
        param_sets = list(expand_grid(param_grid))
        if max_combinations and len(param_sets) > max_combinations:
            param_sets = param_sets[:max_combinations]

        workers = self.max_workers
        if workers is None:
            workers = int(self.config.get("backtest.sweep.max_workers", 0))

        results: list[BacktestResult] = []

        if workers > 1:
            try:
                loop = asyncio.get_running_loop()
                with ProcessPoolExecutor(max_workers=workers) as pool:
                    tasks = [
                        loop.run_in_executor(
                            pool,
                            _run_backtest_sync,
                            getattr(self.config, "_config", {}),
                            data_reader_factory,
                            strategy_cls,
                            params,
                            start,
                            end,
                        )
                        for params in param_sets
                    ]
                    results = await asyncio.gather(*tasks)
            except Exception as ex:
                logger.warning(
                    "ProcessPoolExecutor failed, falling back to async execution: %s",
                    ex,
                )
                results = []

        if not results:
            engine = BacktestEngine(self.config)
            for params in param_sets:
                reader = data_reader_factory()
                res = await engine.run(reader, strategy_cls, params, start, end)
                results.append(res)

        return SweepResult(results=results, param_grid=param_grid)


def generate_windows(
    data_start: datetime,
    data_end: datetime,
    train_span_days: int,
    test_span_days: int,
    step_days: int,
    anchored: bool = False,
) -> list[Window]:
    """Produce non-overlapping test windows with rolling or anchored training.

    - Non-overlapping: test windows across consecutive folds do not overlap.
    - Rolling: training window moves forward by step_days.
    - Anchored: training window always begins at data_start and expands.
    """
    start_tz = data_start.replace(tzinfo=UTC) if data_start.tzinfo is None else data_start
    end_tz = data_end.replace(tzinfo=UTC) if data_end.tzinfo is None else data_end

    windows: list[Window] = []
    cursor = start_tz

    while True:
        if anchored:
            train_start = start_tz
            train_end = cursor + timedelta(days=train_span_days)
        else:
            train_start = cursor
            train_end = cursor + timedelta(days=train_span_days)

        test_start = train_end
        test_end = test_start + timedelta(days=test_span_days)

        if test_end > end_tz:
            break

        windows.append(Window(train_start, train_end, test_start, test_end))

        cursor += timedelta(days=step_days)
        if not anchored and cursor + timedelta(days=train_span_days + test_span_days) > end_tz:
            break
        if anchored and train_end + timedelta(days=step_days + test_span_days) > end_tz:
            break

    return windows


class WalkForwardValidator:
    """Enforces walk-forward validation with rolling train/test windows.

    Anti-overfitting: prevents single-pass optimization across the full dataset.
    """

    def __init__(
        self,
        base_config: ConfigManager | None = None,
        train_span_days: int = 90,
        test_span_days: int = 30,
        step_days: int = 30,
        anchored: bool = False,
        selection_metric: str = "sharpe_ratio",
        max_workers: int | None = None,
    ) -> None:
        self.config = base_config if base_config is not None else ConfigManager()
        self.train_span = train_span_days
        self.test_span = test_span_days
        self.step_days = step_days
        self.anchored = anchored
        self.selection_metric = selection_metric
        self.max_workers = max_workers

    async def run(
        self,
        data_reader_factory: Callable[[], EventStoreReader],
        strategy_cls: type[Strategy],
        param_grid: dict[str, list[Any]],
        data_start: datetime,
        data_end: datetime,
    ) -> WalkForwardReport:
        """Run rolling/anchored walk-forward optimization and out-of-sample evaluation."""
        start_tz = data_start.replace(tzinfo=UTC) if data_start.tzinfo is None else data_start
        end_tz = data_end.replace(tzinfo=UTC) if data_end.tzinfo is None else data_end

        windows = generate_windows(
            data_start=start_tz,
            data_end=end_tz,
            train_span_days=self.train_span,
            test_span_days=self.test_span,
            step_days=self.step_days,
            anchored=self.anchored,
        )
        if not windows:
            raise ValueError("No valid walk-forward windows — data range too small")

        sweep_runner = ParameterSweepRunner(self.config, self.max_workers)
        engine = BacktestEngine(self.config)

        folds: list[FoldResult] = []
        for w in windows:
            # 1. Sweep on train window
            sweep = await sweep_runner.run(
                data_reader_factory,
                strategy_cls,
                param_grid,
                w.train_start,
                w.train_end,
            )
            top_results = sweep.top_n(self.selection_metric, n=1)
            if not top_results:
                raise RuntimeError("No backtest results returned during train sweep")
            best = top_results[0]

            # 2. Evaluate best params on the held-out test window (single run)
            reader = data_reader_factory()
            oos = await engine.run(
                reader,
                strategy_cls,
                best.params,
                w.test_start,
                w.test_end,
            )

            folds.append(
                FoldResult(
                    window=w,
                    best_params=best.params,
                    in_sample=best,
                    out_of_sample=oos,
                )
            )

        # 3. Aggregate OOS metrics across folds
        agg = self._aggregate_oos(folds)

        # 4. Walk-forward efficiency (WFE)
        wfe = self._walk_forward_efficiency(folds, self.selection_metric)

        # 5. Parameter stability
        stability = self._param_stability(folds)

        report = WalkForwardReport(
            folds=folds,
            aggregate_oos_metrics=agg,
            walk_forward_efficiency=wfe,
            param_stability=stability,
            significance=None,
        )

        evaluator = SignificanceEvaluator(self.config)
        report.significance = evaluator.evaluate(report)
        return report

    @staticmethod
    def _aggregate_oos(folds: list[FoldResult]) -> dict[str, float]:
        """Equal-weighted mean of OOS metrics across folds."""
        if not folds:
            return {}
        metric_keys = folds[0].out_of_sample.metrics.keys()
        return {
            k: sum(f.out_of_sample.metrics.get(k, 0.0) for f in folds) / len(folds)
            for k in metric_keys
        }

    @staticmethod
    def _walk_forward_efficiency(
        folds: list[FoldResult],
        metric: str = "sharpe_ratio",
    ) -> float:
        """WFE = mean(OOS metric) / mean(IS metric)."""
        is_vals = [f.in_sample.metrics.get(metric, 0.0) for f in folds]
        oos_vals = [f.out_of_sample.metrics.get(metric, 0.0) for f in folds]
        mean_is = sum(is_vals) / len(is_vals) if is_vals else 0.0
        mean_oos = sum(oos_vals) / len(oos_vals) if oos_vals else 0.0
        if mean_is <= 0:
            return 0.0
        return mean_oos / mean_is

    @staticmethod
    def _param_stability(folds: list[FoldResult]) -> float:
        """Stability = mean normalized distance between consecutive best-param sets."""
        if len(folds) < 2:
            return 1.0
        scores: list[float] = []
        for a, b in zip(folds[:-1], folds[1:]):
            keys = set(a.best_params) | set(b.best_params)
            per_key: list[float] = []
            for k in keys:
                va, vb = a.best_params.get(k), b.best_params.get(k)
                if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                    denom = max(abs(float(va)), abs(float(vb)), 1e-9)
                    per_key.append(1.0 - min(abs(float(va) - float(vb)) / denom, 1.0))
                elif va == vb:
                    per_key.append(1.0)
                else:
                    per_key.append(0.0)
            scores.append(sum(per_key) / len(per_key) if per_key else 1.0)
        return sum(scores) / len(scores)


# ── Significance Criteria & Statistical Tests ────────────────────────


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _poly_eval(coeffs: list[float], x: float) -> float:
    """Horner's method for polynomial evaluation."""
    res = 0.0
    for c in coeffs:
        res = res * x + c
    return res


def _norm_ppf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's approximation, sufficient for p in (0,1))."""
    if p <= 0 or p >= 1:
        raise ValueError("p must be in (0, 1)")
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return _poly_eval(c, q) / _poly_eval(d + [1.0], q)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -_poly_eval(c, q) / _poly_eval(d + [1.0], q)

    q = p - 0.5
    r = q * q
    return _poly_eval(a, r) * q / _poly_eval(b + [1.0], r)


def deflated_sharpe_ratio(
    sharpe_obs_per_period: float,
    T: int,
    skew: float,
    kurt: float,
    sharpe_variance_across_trials: float,
    n_trials: int,
) -> float:
    """Bailey & López de Prado (2014) multiple testing correction.

    All Sharpe inputs must be in per-period units (not annualized).
    Returns DSR in [0, 1].
    """
    euler = 0.5772156649015329
    e = math.e
    if n_trials <= 1:
        sr0 = 0.0
    else:
        sr0 = math.sqrt(max(0.0, sharpe_variance_across_trials)) * (
            (1 - euler) * _norm_ppf(1 - 1.0 / n_trials)
            + euler * _norm_ppf(1 - 1.0 / (n_trials * e))
        )
    denom = math.sqrt(
        max(
            1e-12,
            1 - skew * sharpe_obs_per_period + ((kurt - 1) / 4) * sharpe_obs_per_period**2,
        )
    )
    z = (sharpe_obs_per_period - sr0) * math.sqrt(max(1, T - 1)) / denom
    return _norm_cdf(z)


class SignificanceEvaluator:
    """Applies tiered validation criteria: Sanity (T1) -> Robustness (T2) -> Statistical (T3)."""

    def __init__(self, config: ConfigManager) -> None:
        self.config = config

    def evaluate(self, report: WalkForwardReport) -> SignificanceReport:
        cfg = self.config
        reasons: list[str] = []

        # ---- Tier 1: Basic Sanity ----
        min_trades = int(cfg.get_int("backtest.significance.min_trades", 30))
        min_oos_sharpe = float(cfg.get_float("backtest.significance.min_oos_sharpe", 0.0))
        min_profit_factor = float(
            cfg.get_float("backtest.significance.min_profit_factor", 1.0)
        )
        max_dd = float(
            cfg.get_float("backtest.significance.max_drawdown_limit", 0.25)
        )

        oos = report.aggregate_oos_metrics
        oos_trades = int(oos.get("total_trades", 0))
        oos_sharpe = float(oos.get("sharpe_ratio", 0.0))
        oos_pf = float(oos.get("profit_factor", 0.0))
        oos_dd = float(oos.get("max_drawdown", 1.0))

        tier1 = True
        if oos_trades < min_trades:
            tier1 = False
            reasons.append(f"T1: OOS trades {oos_trades} < {min_trades}")
        if oos_sharpe <= min_oos_sharpe:
            tier1 = False
            reasons.append(f"T1: OOS Sharpe {oos_sharpe:.2f} <= {min_oos_sharpe}")
        if oos_pf <= min_profit_factor:
            tier1 = False
            reasons.append(f"T1: OOS PF {oos_pf:.2f} <= {min_profit_factor}")
        if oos_dd > max_dd:
            tier1 = False
            reasons.append(f"T1: OOS max DD {oos_dd:.2%} > {max_dd:.2%}")

        # ---- Tier 2: Robustness ----
        min_degradation = float(
            cfg.get_float("backtest.significance.min_degradation_ratio", 0.5)
        )
        min_wfe = float(cfg.get_float("backtest.significance.min_wfe", 0.5))
        min_stability = float(
            cfg.get_float("backtest.significance.min_param_stability", 0.6)
        )

        is_sharpes = [
            float(f.in_sample.metrics.get("sharpe_ratio", 0.0))
            for f in report.folds
        ]
        is_sharpe = sum(is_sharpes) / max(len(report.folds), 1)
        degradation = (oos_sharpe / is_sharpe) if is_sharpe > 0 else 0.0

        tier2 = True
        if degradation < min_degradation:
            tier2 = False
            reasons.append(f"T2: Degradation {degradation:.2f} < {min_degradation}")
        if report.walk_forward_efficiency < min_wfe:
            tier2 = False
            reasons.append(
                f"T2: WFE {report.walk_forward_efficiency:.2f} < {min_wfe}"
            )
        if report.param_stability < min_stability:
            tier2 = False
            reasons.append(
                f"T2: Stability {report.param_stability:.2f} < {min_stability}"
            )

        # ---- Tier 3: Statistical Significance (Deflated Sharpe Ratio) ----
        enable_dsr = bool(
            cfg.get("backtest.significance.enable_deflated_sharpe", False)
        )
        min_dsr = float(cfg.get_float("backtest.significance.min_dsr", 0.95))
        dsr_value: float | None = None
        tier3 = True

        if enable_dsr:
            all_oos_sharpes = [
                float(f.out_of_sample.metrics.get("sharpe_ratio", 0.0))
                for f in report.folds
            ]
            if len(all_oos_sharpes) >= 2:
                mean_sr = sum(all_oos_sharpes) / len(all_oos_sharpes)
                var_sr = sum((s - mean_sr) ** 2 for s in all_oos_sharpes) / (
                    len(all_oos_sharpes) - 1
                )
                sr_obs_pp = oos_sharpe / math.sqrt(252.0)
                T = max(2, int(oos_trades * 2))
                dsr_value = deflated_sharpe_ratio(
                    sharpe_obs_per_period=sr_obs_pp,
                    T=T,
                    skew=float(
                        cfg.get_float("backtest.significance.assumed_skew", -0.5)
                    ),
                    kurt=float(
                        cfg.get_float("backtest.significance.assumed_kurtosis", 4.0)
                    ),
                    sharpe_variance_across_trials=var_sr,
                    n_trials=int(
                        cfg.get_int("backtest.significance.num_trials", 100)
                    ),
                )
                if dsr_value < min_dsr:
                    tier3 = False
                    reasons.append(f"T3: DSR {dsr_value:.3f} < {min_dsr}")

        trusted = tier1 and tier2 and tier3

        return SignificanceReport(
            tier1_passed=tier1,
            tier2_passed=tier2,
            tier3_passed=tier3,
            trusted=trusted,
            oos_trades=oos_trades,
            oos_sharpe=oos_sharpe,
            is_sharpe=is_sharpe,
            degradation_ratio=degradation,
            wfe=report.walk_forward_efficiency,
            stability=report.param_stability,
            deflated_sharpe=dsr_value,
            reasons=reasons,
        )

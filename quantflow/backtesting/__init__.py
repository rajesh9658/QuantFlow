"""QuantFlow backtesting subpackage: deterministic pipeline, sweeps, and walk-forward validation."""

from quantflow.backtesting.engine import (
    BacktestEngine,
    BacktestPipeline,
    BacktestResult,
    NullExchangeAdapter,
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
    deflated_sharpe_ratio,
    expand_grid,
    generate_windows,
)

__all__ = [
    "BacktestEngine",
    "BacktestPipeline",
    "BacktestResult",
    "FoldResult",
    "NullExchangeAdapter",
    "ParameterSweepRunner",
    "SignificanceEvaluator",
    "SignificanceReport",
    "SweepResult",
    "WalkForwardReport",
    "WalkForwardValidator",
    "Window",
    "build_backtest_pipeline",
    "deflated_sharpe_ratio",
    "expand_grid",
    "generate_windows",
]

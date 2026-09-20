"""QuantFlow Analytics package."""

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
    calculate_total_return,
    calculate_variance,
    calculate_win_rate,
    daily_return,
    daily_returns_from_equity_curve,
)

__all__ = [
    "AnalyticsEngine",
    "BatchAnalyticsCalculator",
    "DrawdownTracker",
    "IncrementalAnalyticsCalculator",
    "TradeStatsAggregator",
    "WelfordOnline",
    "calculate_avg_latency",
    "calculate_avg_slippage",
    "calculate_avg_trade",
    "calculate_downside_deviation",
    "calculate_drawdowns",
    "calculate_mean",
    "calculate_profit_factor",
    "calculate_sharpe_ratio",
    "calculate_sortino_ratio",
    "calculate_stddev",
    "calculate_total_return",
    "calculate_variance",
    "calculate_win_rate",
    "daily_return",
    "daily_returns_from_equity_curve",
]

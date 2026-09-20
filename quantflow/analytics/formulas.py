"""Pure, stateless mathematical functions for QuantFlow analytics metrics."""

from __future__ import annotations

import math
from collections.abc import Sequence


def daily_return(current_equity: float, previous_equity: float) -> float:
    """Compute single-period return: (E_t - E_{t-1}) / E_{t-1}."""
    if previous_equity <= 0:
        return 0.0
    return (current_equity - previous_equity) / previous_equity


def daily_returns_from_equity_curve(equities: Sequence[float]) -> list[float]:
    """Compute series of returns from an ordered sequence of equity values."""
    if len(equities) < 2:
        return []
    returns: list[float] = []
    for i in range(1, len(equities)):
        prev = equities[i - 1]
        curr = equities[i]
        returns.append(daily_return(curr, prev))
    return returns


def calculate_mean(values: Sequence[float]) -> float:
    """Compute arithmetic mean of a sequence of numbers."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def calculate_variance(values: Sequence[float], ddof: int = 1) -> float:
    """Compute sample variance of a sequence with specified degrees of freedom."""
    n = len(values)
    if n <= ddof:
        return 0.0
    mean_val = calculate_mean(values)
    sum_sq_diff = sum((x - mean_val) ** 2 for x in values)
    return sum_sq_diff / (n - ddof)


def calculate_stddev(values: Sequence[float], ddof: int = 1) -> float:
    """Compute sample standard deviation of a sequence."""
    var = calculate_variance(values, ddof=ddof)
    return math.sqrt(var) if var > 0.0 else 0.0


def calculate_downside_deviation(
    returns: Sequence[float],
    target: float | None = None,
    ddof: int = 1,
) -> float:
    """Compute sample downside deviation for Sortino ratio.

    Uses deviations below the target (defaults to sample mean if target is None):
    d_t = min(R_t - target, 0.0)
    sigma_d = sqrt( sum(d_t^2) / (N - ddof) )
    """
    n = len(returns)
    if n <= ddof:
        return 0.0
    mean_val = target if target is not None else calculate_mean(returns)
    sum_sq_downside = sum(min(r - mean_val, 0.0) ** 2 for r in returns)
    return math.sqrt(sum_sq_downside / (n - ddof))


def calculate_sharpe_ratio(
    mean_return: float,
    std_dev: float,
    risk_free_rate: float = 0.0,
    annualization_factor: float = 252.0,
) -> float:
    """Compute annualized Sharpe ratio."""
    if std_dev <= 0.0:
        return 0.0
    excess_return = mean_return - risk_free_rate
    return (excess_return / std_dev) * math.sqrt(annualization_factor)


def calculate_sortino_ratio(
    mean_return: float,
    downside_std_dev: float,
    risk_free_rate: float = 0.0,
    annualization_factor: float = 252.0,
) -> float:
    """Compute annualized Sortino ratio."""
    if downside_std_dev <= 0.0:
        return 0.0
    excess_return = mean_return - risk_free_rate
    return (excess_return / downside_std_dev) * math.sqrt(annualization_factor)


def calculate_drawdowns(equities: Sequence[float]) -> tuple[float, float]:
    """Compute (max_drawdown, current_drawdown) for an equity series."""
    if not equities:
        return 0.0, 0.0

    peak = equities[0]
    max_dd = 0.0
    current_dd = 0.0

    for eq in equities:
        if eq > peak:
            peak = eq
        current_dd = (peak - eq) / peak if peak > 0 else 0.0
        if current_dd > max_dd:
            max_dd = current_dd

    return max_dd, current_dd


def calculate_win_rate(winning_trades: int, total_trades: int) -> float:
    """Compute win rate percentage: winning_trades / total_trades."""
    if total_trades <= 0:
        return 0.0
    return winning_trades / total_trades


def calculate_profit_factor(sum_win_pnl: float, sum_loss_pnl: float) -> float:
    """Compute profit factor: sum(winning_pnl) / sum(abs(losing_pnl)).

    Returns float('inf') if there are wins and zero losses.
    Returns 0.0 if there are zero wins and zero losses.
    """
    abs_loss = abs(sum_loss_pnl)
    if abs_loss == 0.0:
        return float("inf") if sum_win_pnl > 0 else 0.0
    return sum_win_pnl / abs_loss


def calculate_avg_trade(sum_pnl: float, total_trades: int) -> float:
    """Compute average trade PnL: sum(pnl) / total_trades."""
    if total_trades <= 0:
        return 0.0
    return sum_pnl / total_trades


def calculate_avg_slippage(sum_slippage: float, total_trades: int) -> float:
    """Compute average slippage per trade: sum(slippage) / total_trades."""
    if total_trades <= 0:
        return 0.0
    return sum_slippage / total_trades


def calculate_avg_latency(sum_latency: float, latency_count: int) -> float:
    """Compute average execution latency: sum(latency) / latency_count."""
    if latency_count <= 0:
        return 0.0
    return sum_latency / latency_count


def calculate_total_return(initial_equity: float, final_equity: float) -> float:
    """Compute cumulative return: (final_equity - initial_equity) / initial_equity."""
    if initial_equity <= 0:
        return 0.0
    return (final_equity - initial_equity) / initial_equity


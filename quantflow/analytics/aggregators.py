"""Incremental and stateful aggregators for online streaming analytics."""

from __future__ import annotations

import math

from quantflow.analytics.formulas import (
    calculate_avg_latency,
    calculate_avg_slippage,
    calculate_avg_trade,
    calculate_profit_factor,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_total_return,
    calculate_win_rate,
)


class WelfordOnline:
    """Online mean and sample variance accumulator using Welford's algorithm."""

    def __init__(self) -> None:
        self.n: int = 0
        self.mean: float = 0.0
        self.m2: float = 0.0  # Sum of squared differences from the running mean

    def update(self, x: float) -> None:
        """Update running mean and M2 with a new sample value."""
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        delta2 = x - self.mean
        self.m2 += delta * delta2

    def variance(self) -> float:
        """Sample variance (ddof=1). Returns 0.0 if n <= 1."""
        return self.m2 / (self.n - 1) if self.n > 1 else 0.0

    def stddev(self) -> float:
        """Sample standard deviation. Returns 0.0 if n <= 1."""
        var = self.variance()
        return math.sqrt(var) if var > 0.0 else 0.0


class DrawdownTracker:
    """Tracks running peak, current drawdown, and maximum drawdown."""

    def __init__(self, initial_equity: float) -> None:
        self.peak: float = initial_equity
        self.current_drawdown: float = 0.0
        self.max_drawdown: float = 0.0

    def update(self, equity: float) -> None:
        """Update peak and drawdowns with a new equity value."""
        if equity > self.peak:
            self.peak = equity
        self.current_drawdown = (
            (self.peak - equity) / self.peak if self.peak > 0.0 else 0.0
        )
        if self.current_drawdown > self.max_drawdown:
            self.max_drawdown = self.current_drawdown


class TradeStatsAggregator:
    """Aggregates per-trade PnL, win/loss counts, slippage, and latency."""

    def __init__(self) -> None:
        self.total_trades: int = 0
        self.winning_trades: int = 0
        self.sum_pnl: float = 0.0
        self.sum_win_pnl: float = 0.0
        self.sum_loss_pnl: float = 0.0  # Absolute value of losses
        self.sum_slippage: float = 0.0
        self.sum_latency: float = 0.0
        self.latency_count: int = 0

    def add_trade(
        self,
        pnl: float,
        slippage: float | None = None,
        latency: float | None = None,
    ) -> None:
        """Record an executed trade with PnL and optional execution statistics."""
        self.total_trades += 1
        self.sum_pnl += pnl
        if pnl > 0:
            self.winning_trades += 1
            self.sum_win_pnl += pnl
        elif pnl < 0:
            self.sum_loss_pnl += abs(pnl)

        if slippage is not None:
            self.sum_slippage += slippage
        if latency is not None:
            self.sum_latency += latency
            self.latency_count += 1

    @property
    def win_rate(self) -> float:
        """Fraction of winning trades."""
        return calculate_win_rate(self.winning_trades, self.total_trades)

    @property
    def avg_trade(self) -> float:
        """Average PnL per trade."""
        return calculate_avg_trade(self.sum_pnl, self.total_trades)

    @property
    def profit_factor(self) -> float:
        """Ratio of gross profits to gross losses."""
        return calculate_profit_factor(self.sum_win_pnl, self.sum_loss_pnl)

    @property
    def avg_slippage(self) -> float:
        """Average slippage across all trades."""
        return calculate_avg_slippage(self.sum_slippage, self.total_trades)

    @property
    def avg_latency(self) -> float:
        """Average execution latency across fills with latency data."""
        return calculate_avg_latency(self.sum_latency, self.latency_count)


class IncrementalAnalyticsCalculator:
    """Stateful rolling/incremental calculator for real-time analytics."""

    def __init__(
        self,
        risk_free_rate: float = 0.0,
        annualization_factor: float = 252.0,
    ) -> None:
        self.risk_free_rate = risk_free_rate
        self.annualization_factor = annualization_factor

        self.initial_equity: float | None = None
        self.last_equity: float | None = None
        self.return_aggregator = WelfordOnline()
        self.downside_aggregator = WelfordOnline()
        self.drawdown_tracker: DrawdownTracker | None = None
        self.trade_stats = TradeStatsAggregator()

    def reset(self) -> None:
        """Reset all internal accumulators."""
        self.initial_equity = None
        self.last_equity = None
        self.return_aggregator = WelfordOnline()
        self.downside_aggregator = WelfordOnline()
        self.drawdown_tracker = None
        self.trade_stats = TradeStatsAggregator()

    def update_equity(self, equity: float) -> None:
        """Update equity for running drawdown tracking."""
        if self.initial_equity is None:
            self.initial_equity = equity
            self.drawdown_tracker = DrawdownTracker(equity)
            self.last_equity = equity
            return

        if self.drawdown_tracker is not None:
            self.drawdown_tracker.update(equity)
        self.last_equity = equity

    def add_daily_return(self, ret: float) -> None:
        """Update rolling return variance and downside variance."""
        self.return_aggregator.update(ret)
        # Downside deviation uses deviation below current mean (per spec)
        downside = min(ret - self.return_aggregator.mean, 0.0)
        self.downside_aggregator.update(downside)

    def add_trade(
        self,
        pnl: float,
        slippage: float | None = None,
        latency: float | None = None,
    ) -> None:
        """Record trade fill performance."""
        self.trade_stats.add_trade(pnl, slippage, latency)

    def get_metrics(self) -> dict[str, float]:
        """Compute all performance metrics from current accumulated state."""
        mean_ret = self.return_aggregator.mean
        std_ret = self.return_aggregator.stddev()
        downside_std = self.downside_aggregator.stddev()

        sharpe = calculate_sharpe_ratio(
            mean_return=mean_ret,
            std_dev=std_ret,
            risk_free_rate=self.risk_free_rate,
            annualization_factor=self.annualization_factor,
        )

        sortino = calculate_sortino_ratio(
            mean_return=mean_ret,
            downside_std_dev=downside_std,
            risk_free_rate=self.risk_free_rate,
            annualization_factor=self.annualization_factor,
        )

        max_dd = (
            self.drawdown_tracker.max_drawdown
            if self.drawdown_tracker is not None
            else 0.0
        )
        current_dd = (
            self.drawdown_tracker.current_drawdown
            if self.drawdown_tracker is not None
            else 0.0
        )

        metrics: dict[str, float] = {
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "max_drawdown": max_dd,
            "current_drawdown": current_dd,
            "win_rate": self.trade_stats.win_rate,
            "profit_factor": self.trade_stats.profit_factor,
            "avg_trade": self.trade_stats.avg_trade,
            "avg_slippage": self.trade_stats.avg_slippage,
            "avg_latency": self.trade_stats.avg_latency,
            "total_trades": float(self.trade_stats.total_trades),
        }

        if (
            self.initial_equity is not None
            and self.last_equity is not None
            and self.initial_equity > 0.0
        ):
            metrics["total_return"] = calculate_total_return(
                self.initial_equity, self.last_equity
            )

        return metrics

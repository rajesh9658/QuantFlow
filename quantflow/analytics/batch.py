"""Batch analytics calculator for backtesting and historical simulation reports."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from quantflow.analytics.aggregators import IncrementalAnalyticsCalculator
from quantflow.analytics.formulas import (
    daily_return,
)


class BatchAnalyticsCalculator:
    """Computes full performance analytics over static historical datasets.

    Shares pure formula implementations with the streaming engine to guarantee
    mathematical parity between backtests and live trading.
    """

    def __init__(
        self,
        risk_free_rate: float = 0.0,
        annualization_factor: float = 252.0,
    ) -> None:
        self.risk_free_rate = risk_free_rate
        self.annualization_factor = annualization_factor

    def compute_metrics_from_history(
        self,
        equity_curve: Sequence[tuple[datetime, float]],
        trades: Sequence[tuple[float, float | None, float | None]] | None = None,
    ) -> dict[str, float]:
        """Compute metrics by processing a timestamped equity curve and trade list.

        This method replicates day-boundary daily return accumulation to ensure
        100% numerical match with live streaming event processing.
        """
        calc = IncrementalAnalyticsCalculator(
            risk_free_rate=self.risk_free_rate,
            annualization_factor=self.annualization_factor,
        )

        last_update_day: str | None = None
        last_day_equity: float | None = None

        for ts, eq in equity_curve:
            day_key = ts.date().isoformat()

            if calc.initial_equity is None:
                calc.update_equity(eq)
                last_day_equity = eq
                last_update_day = day_key
                continue

            if day_key != last_update_day:
                if last_day_equity is not None and last_day_equity > 0:
                    ret = daily_return(eq, last_day_equity)
                    calc.add_daily_return(ret)
                last_update_day = day_key
                last_day_equity = eq

            calc.update_equity(eq)
            last_day_equity = eq

        if trades:
            for pnl, slippage, latency in trades:
                calc.add_trade(pnl, slippage, latency)

        return calc.get_metrics()

    def compute_metrics_from_series(
        self,
        equities: Sequence[float],
        trades: Sequence[tuple[float, float | None, float | None]] | None = None,
    ) -> dict[str, float]:
        """Compute metrics from a flat sequence of daily equity values and trades."""
        calc = IncrementalAnalyticsCalculator(
            risk_free_rate=self.risk_free_rate,
            annualization_factor=self.annualization_factor,
        )

        if equities:
            calc.update_equity(equities[0])
            for i in range(1, len(equities)):
                prev = equities[i - 1]
                curr = equities[i]
                ret = daily_return(curr, prev)
                calc.add_daily_return(ret)
                calc.update_equity(curr)

        if trades:
            for pnl, slippage, latency in trades:
                calc.add_trade(pnl, slippage, latency)

        return calc.get_metrics()

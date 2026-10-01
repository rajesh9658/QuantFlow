"""Significance evaluator re-export for spec parity."""

from quantflow.backtesting.optimizer import (
    SignificanceEvaluator,
    SignificanceReport,
    deflated_sharpe_ratio,
)

__all__ = [
    "SignificanceEvaluator",
    "SignificanceReport",
    "deflated_sharpe_ratio",
]

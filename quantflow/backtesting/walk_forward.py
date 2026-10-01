"""Walk-forward validator re-export for spec parity."""

from quantflow.backtesting.optimizer import (
    FoldResult,
    WalkForwardReport,
    WalkForwardValidator,
    Window,
    generate_windows,
)

__all__ = [
    "FoldResult",
    "WalkForwardReport",
    "WalkForwardValidator",
    "Window",
    "generate_windows",
]

"""Real-time and batch Analytics Engine for QuantFlow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from quantflow.analytics.aggregators import (
    DrawdownTracker,
    TradeStatsAggregator,
    WelfordOnline,
)
from quantflow.analytics.formulas import (
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_total_return,
)
from quantflow.common.events import FillEvent, PortfolioUpdateEvent
from quantflow.config.manager import ConfigManager
from quantflow.core.interfaces import EventBus
from quantflow.core.logging import get_logger


class AnalyticsEngine:
    """Real-time analytics engine subscribing to PortfolioUpdate and Fill events.

    Maintains rolling performance statistics and exposes computed risk/return metrics.
    Guarantees parity between live event streaming and offline backtest calculations.
    """

    def __init__(self, config: ConfigManager, event_bus: EventBus) -> None:
        self.config = config
        self.event_bus = event_bus
        self.logger = get_logger("analytics_engine")

        # Configuration options
        if hasattr(config, "get_float"):
            self.risk_free_rate: float = float(
                config.get_float("analytics.risk_free_rate", 0.0)
            )
            self.annualization_factor: float = float(
                config.get_float("analytics.annualization_factor", 252.0)
            )
        else:
            self.risk_free_rate = float(config.get("analytics.risk_free_rate", 0.0))
            self.annualization_factor = float(
                config.get("analytics.annualization_factor", 252.0)
            )

        # Internal state
        self.initial_equity: float | None = None
        self.last_equity: float | None = None
        self.last_update_day: str | None = None

        # Return & downside variance aggregators
        self.return_aggregator = WelfordOnline()
        self.downside_aggregator = WelfordOnline()

        # Drawdown & trade stats trackers
        self.drawdown_tracker: DrawdownTracker | None = None
        self.trade_stats = TradeStatsAggregator()

        # Historical equity curve snapshots
        self.equity_curve: list[tuple[datetime, float]] = []

        self._running: bool = False

    async def start(self) -> None:
        """Start the engine and subscribe to portfolio and execution events."""
        if self._running:
            return
        self._running = True
        await self.event_bus.subscribe(PortfolioUpdateEvent, self._handle_portfolio)
        await self.event_bus.subscribe(FillEvent, self._handle_fill)
        self.logger.info("Analytics Engine started")

    async def stop(self) -> None:
        """Stop the engine and unsubscribe from event bus."""
        if not self._running:
            return
        self._running = False
        await self.event_bus.unsubscribe(PortfolioUpdateEvent, self._handle_portfolio)
        await self.event_bus.unsubscribe(FillEvent, self._handle_fill)
        self.logger.info("Analytics Engine stopped")

    # ── Event Handlers ───────────────────────────────────────────────

    async def _handle_portfolio(self, event: PortfolioUpdateEvent | Any) -> None:
        """Process portfolio update events to maintain daily returns and drawdowns."""
        if not self._running:
            return

        # Extract total value / equity from event (supports direct attribute or payload)
        payload = getattr(event, "payload", event)
        equity = float(
            getattr(
                payload,
                "total_value",
                getattr(payload, "total_equity", 0.0),
            )
        )

        ts: datetime = (
            getattr(event, "timestamp_received", None)
            or getattr(event, "timestamp", None)
            or datetime.now(UTC)
        )
        day_key = ts.date().isoformat()

        # Initial equity setup
        if self.initial_equity is None:
            self.initial_equity = equity
            self.drawdown_tracker = DrawdownTracker(equity)
            self.last_equity = equity
            self.last_update_day = day_key
            self.equity_curve.append((ts, equity))
            return

        # Day transition: compute daily return for previous day
        if day_key != self.last_update_day:
            if self.last_equity is not None and self.last_equity > 0:
                daily_ret = (equity - self.last_equity) / self.last_equity
                self._add_daily_return(daily_ret)

            self.last_update_day = day_key
            self.last_equity = equity
            self.equity_curve.append((ts, equity))

        # Always update drawdown
        if self.drawdown_tracker:
            self.drawdown_tracker.update(equity)

        self.last_equity = equity

    async def _handle_fill(self, event: FillEvent | Any) -> None:
        """Process fill events to compute trade PnL, slippage, and latency."""
        if not self._running:
            return

        fill = getattr(event, "payload", event)
        metadata = getattr(fill, "metadata", {}) or {}

        # 1. Realized PnL
        realized_pnl = float(
            getattr(fill, "realized_pnl", metadata.get("realized_pnl", 0.0))
        )

        # 2. Slippage
        fill_price = float(getattr(fill, "fill_price", getattr(fill, "price", 0.0)))
        expected_price = metadata.get(
            "expected_price", getattr(fill, "expected_price", None)
        )
        slippage: float | None = None
        if expected_price is not None and float(expected_price) > 0:
            slippage = fill_price - float(expected_price)

        # 3. Latency
        ts_received = getattr(event, "timestamp_received", None)
        ts_exchange = getattr(event, "timestamp_exchange", None)
        latency: float | None = None
        if ts_received and ts_exchange:
            latency = (ts_received - ts_exchange).total_seconds()

        # Record trade if realized PnL was recognized
        if abs(realized_pnl) > 1e-12:
            self.trade_stats.add_trade(realized_pnl, slippage, latency)

    # ── Internal Computation ─────────────────────────────────────────

    def _add_daily_return(self, ret: float) -> None:
        """Update standard return aggregator and downside deviation aggregator."""
        self.return_aggregator.update(ret)
        downside = min(ret - self.return_aggregator.mean, 0.0)
        self.downside_aggregator.update(downside)

    # ── Batch Loading (for Backtests & Simulations) ──────────────────

    def load_historical_equity(
        self, equity_curve: list[tuple[datetime, float]]
    ) -> None:
        """Bulk-load a historical equity curve for batch/backtest calculations."""
        self.reset()
        for ts, eq in equity_curve:
            day_key = ts.date().isoformat()
            if self.initial_equity is None:
                self.initial_equity = eq
                self.drawdown_tracker = DrawdownTracker(eq)
                self.last_equity = eq
                self.last_update_day = day_key
                self.equity_curve.append((ts, eq))
                continue

            if day_key != self.last_update_day:
                if self.last_equity is not None and self.last_equity > 0:
                    daily_ret = (eq - self.last_equity) / self.last_equity
                    self._add_daily_return(daily_ret)
                self.last_update_day = day_key
                self.last_equity = eq
                self.equity_curve.append((ts, eq))

            if self.drawdown_tracker:
                self.drawdown_tracker.update(eq)
            self.last_equity = eq

    def load_historical_trades(
        self,
        trades: list[tuple[float, float | None, float | None]],
    ) -> None:
        """Bulk-load historical trades: list of (pnl, slippage, latency)."""
        for pnl, slippage, latency in trades:
            self.trade_stats.add_trade(pnl, slippage, latency)

    # ── Reset & Getters ──────────────────────────────────────────────

    def reset(self) -> None:
        """Reset all state to compute a fresh set of metrics."""
        self.initial_equity = None
        self.last_equity = None
        self.last_update_day = None
        self.return_aggregator = WelfordOnline()
        self.downside_aggregator = WelfordOnline()
        self.drawdown_tracker = None
        self.trade_stats = TradeStatsAggregator()
        self.equity_curve.clear()

    def get_metrics(self) -> dict[str, float]:
        """Return the full dictionary of computed performance metrics."""
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
            and self.initial_equity > 0
        ):
            metrics["total_return"] = calculate_total_return(
                self.initial_equity, self.last_equity
            )

        return metrics

    def get_equity_curve(self) -> list[tuple[datetime, float]]:
        """Return a copy of the recorded equity curve snapshots."""
        return self.equity_curve.copy()

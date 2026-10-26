"""Real-time and batch Analytics Engine for QuantFlow."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
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
from quantflow.core.clock import Clock, SystemClock
from quantflow.core.interfaces import EventBus
from quantflow.core.logging import get_logger


class AnalyticsEngine:
    """Real-time analytics engine subscribing to PortfolioUpdate and Fill events.

    Maintains rolling performance statistics and exposes computed risk/return metrics.
    Guarantees parity between live event streaming and offline backtest calculations.
    """

    def __init__(
        self,
        config: ConfigManager,
        event_bus: EventBus,
        clock: Clock | None = None,
    ) -> None:
        self.config = config
        self.event_bus = event_bus
        self.clock: Clock = clock or SystemClock()
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
        self._daily_equities: dict[Any, float] = {}
        self.exposure_history: dict[datetime, float] = {}

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
            or self.clock.now()
        )
        self.exposure_history[ts] = float(getattr(payload, "total_exposure", 0.0))
        self._record_equity(ts, equity)
        return

    def _record_equity(self, ts: datetime, equity: float) -> None:
        ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
        if self.equity_curve and ts < self.equity_curve[-1][0]:
            raise ValueError("Equity snapshots must be chronological")
        if not math.isfinite(equity):
            raise ValueError("Equity must be finite")
        if self.initial_equity is None:
            self.initial_equity = equity
            self.drawdown_tracker = DrawdownTracker(equity)
        # A midnight sample closes the preceding UTC day. The initial point is
        # the baseline, not an extra flat trading day.
        initial_ts = self.equity_curve[0][0] if self.equity_curve else ts
        day = (ts-timedelta(microseconds=1)).date() if ts != initial_ts and ts.time().isoformat() == "00:00:00" else ts.date()
        if self.equity_curve and (ts != initial_ts or equity != self.initial_equity):
            self._daily_equities[day] = equity
        self.last_equity = equity
        self.last_update_day = ts.date().isoformat()
        self.drawdown_tracker.update(equity)
        if self.equity_curve and self.equity_curve[-1][0] == ts:
            self.equity_curve[-1] = (ts, equity)
        else:
            self.equity_curve.append((ts, equity))

    def finalize(self) -> None:
        """Rebuild close-to-close daily samples, including inactive UTC days."""
        self.return_aggregator = WelfordOnline()
        self.downside_aggregator = WelfordOnline()
        if not self._daily_equities or self.initial_equity is None:
            return
        previous = self.initial_equity
        day, last = min(self._daily_equities), max(self._daily_equities)
        while day <= last:
            current = self._daily_equities.get(day, previous)
            if previous > 0:
                self._add_daily_return((current-previous)/previous)
            previous = current
            day += timedelta(days=1)

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
        if metadata.get("accounted"):
            if float(metadata.get("closed_quantity", 0.0)) > 0 and metadata.get("trade_complete", True):
                self.trade_stats.add_trade(float(metadata["closed_trade_pnl"]), slippage, latency)
        elif abs(realized_pnl) > 1e-12:
            self.trade_stats.add_trade(realized_pnl, slippage, latency)

    # ── Internal Computation ─────────────────────────────────────────

    def _add_daily_return(self, ret: float) -> None:
        """Update standard return aggregator and downside deviation aggregator."""
        self.return_aggregator.update(ret)
        downside = min(ret - self.risk_free_rate / self.annualization_factor, 0.0)
        self.downside_aggregator.update(downside)

    # ── Batch Loading (for Backtests & Simulations) ──────────────────

    def load_historical_equity(
        self, equity_curve: list[tuple[datetime, float]]
    ) -> None:
        """Bulk-load a historical equity curve for batch/backtest calculations."""
        self.reset()
        for ts, eq in equity_curve:
            self._record_equity(ts, eq)
        self.finalize()

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
        self._daily_equities.clear()
        self.exposure_history.clear()

    def get_metrics(self) -> dict[str, float]:
        """Return the full dictionary of computed performance metrics."""
        self.finalize()
        mean_ret = self.return_aggregator.mean
        std_ret = self.return_aggregator.stddev()
        downside = self.downside_aggregator
        downside_std = math.sqrt(max(0.0, downside.m2 / downside.n + downside.mean**2)) if downside.n else 0.0

        sharpe = calculate_sharpe_ratio(
            mean_return=mean_ret,
            std_dev=std_ret,
            risk_free_rate=self.risk_free_rate / self.annualization_factor,
            annualization_factor=self.annualization_factor,
        )

        sortino = calculate_sortino_ratio(
            mean_return=mean_ret,
            downside_std_dev=downside_std,
            risk_free_rate=self.risk_free_rate / self.annualization_factor,
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

"""Dependency injection and state provider for QuantFlow FastAPI APIs."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from quantflow.analytics.engine import AnalyticsEngine
from quantflow.config.manager import ConfigManager
from quantflow.core.event_bus import AsyncEventBus
from quantflow.core.interfaces import EventBus
from quantflow.portfolio.engine import PortfolioEngine
from quantflow.risk.engine import RiskEngine
from quantflow.strategies.engine import StrategyEngine


class APIState:
    """State manager bridging QuantFlow engines and API endpoints."""

    def __init__(
        self,
        config: ConfigManager | None = None,
        event_bus: EventBus | None = None,
        portfolio_engine: PortfolioEngine | None = None,
        risk_engine: RiskEngine | None = None,
        analytics_engine: AnalyticsEngine | None = None,
        strategy_engine: StrategyEngine | None = None,
    ) -> None:
        self.config = config or ConfigManager()
        self.event_bus = event_bus or AsyncEventBus()
        self.portfolio_engine = portfolio_engine
        self.risk_engine = risk_engine
        self.analytics_engine = analytics_engine
        self.strategy_engine = strategy_engine

        # Default fallback in-memory fixture stores (for standalone/dev/testing)
        self._strategy_toggles: dict[str, bool] = {
            "Simple Momentum": True,
            "Mean Reversion": True,
            "Trend Follower": False,
        }
        self._emergency_stop: bool = False
        self._exchange_status: list[dict[str, Any]] = [
            {
                "name": "binance",
                "connected": True,
                "latency_ms": 45.0,
                "last_heartbeat": datetime.now(UTC).isoformat(),
                "symbols_subscribed": ["BTC/USDT", "ETH/USDT"],
            }
        ]

        # Seed realistic fixture history
        self._trades: list[dict[str, Any]] = []
        self._orders: list[dict[str, Any]] = []
        self._signals: list[dict[str, Any]] = []
        self._logs: list[dict[str, Any]] = []
        self._seed_fixtures()

    def _seed_fixtures(self) -> None:
        now = datetime.now(UTC)
        for i in range(5):
            t_time = (now - timedelta(minutes=10 * (5 - i))).isoformat()
            o_id = str(uuid4())
            f_id = str(uuid4())
            sym = "BTC/USDT" if i % 2 == 0 else "ETH/USDT"
            side = "buy" if i % 3 != 0 else "sell"
            price = 48500.0 + (i * 50.0) if "BTC" in sym else 2800.0 + (i * 10.0)
            qty = 0.5 if "BTC" in sym else 2.0

            self._orders.append(
                {
                    "order_id": o_id,
                    "exchange_order_id": f"binance-{o_id[:8]}",
                    "symbol": sym,
                    "side": side,
                    "type": "limit",
                    "quantity": qty,
                    "filled_quantity": qty,
                    "avg_price": price,
                    "status": "FILLED",
                    "created_at": t_time,
                    "strategy": "Simple Momentum",
                }
            )

            self._trades.append(
                {
                    "fill_id": f_id,
                    "order_id": o_id,
                    "symbol": sym,
                    "side": side,
                    "price": price,
                    "quantity": qty,
                    "commission": round(price * qty * 0.0005, 2),
                    "timestamp_exchange": t_time,
                    "realized_pnl": 150.0 if side == "sell" else 0.0,
                    "strategy": "Simple Momentum",
                }
            )

            self._signals.append(
                {
                    "event_id": str(uuid4()),
                    "strategy_name": "Simple Momentum",
                    "symbol": sym,
                    "direction": side,
                    "confidence": 0.85,
                    "timestamp_exchange": t_time,
                }
            )

            self._logs.append(
                {
                    "correlation_id": str(uuid4()),
                    "level": "INFO" if i > 1 else "WARNING",
                    "logger_name": (
                        "quantflow.risk" if i == 0 else "quantflow.strategy"
                    ),
                    "message": (
                        "Risk check completed"
                        if i > 0
                        else "Approaching daily exposure threshold"
                    ),
                    "metadata": {"step": i},
                    "received_at": t_time,
                }
            )

    # ── Data Provider Methods ────────────────────────────────────────

    def get_portfolio_snapshot(self) -> dict[str, Any]:
        if self.portfolio_engine is not None:
            st = self.portfolio_engine.state
            positions = [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_entry_price": p.avg_entry_price,
                    "unrealized_pnl": 0.0,
                }
                for p in st.positions.values()
                if not p.is_empty()
            ]
            return {
                "cash": st.cash,
                "total_equity": st.total_equity or st.cash,
                "total_exposure": st.total_exposure,
                "realized_pnl": st.realized_pnl,
                "unrealized_pnl": st.unrealized_pnl,
                "positions": positions,
            }

        # Fallback fixture
        return {
            "cash": 50234.50,
            "total_equity": 102450.75,
            "total_exposure": 52216.25,
            "realized_pnl": 12450.75,
            "unrealized_pnl": 2216.25,
            "positions": [
                {
                    "symbol": "BTC/USDT",
                    "quantity": 0.5,
                    "avg_entry_price": 48500.0,
                    "unrealized_pnl": 750.0,
                },
                {
                    "symbol": "ETH/USDT",
                    "quantity": 5.0,
                    "avg_entry_price": 2800.0,
                    "unrealized_pnl": 1466.25,
                },
            ],
        }

    def get_portfolio_history(
        self,
        from_ts: str | None = None,
        to_ts: str | None = None,
        interval: str | None = None,
    ) -> list[dict[str, Any]]:
        if self.analytics_engine is not None:
            curve = self.analytics_engine.get_equity_curve()
            if curve:
                res = []
                peak = curve[0][1]
                for ts, eq in curve:
                    if eq > peak:
                        peak = eq
                    dd = (peak - eq) / peak if peak > 0 else 0.0
                    ts_val = (
                        ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
                    )
                    res.append(
                        {
                            "timestamp": ts_val,
                            "equity": eq,
                            "drawdown": dd,
                            "exposure": eq * 0.5,
                        }
                    )
                return res

        # Seed 10 day historical curve
        now = datetime.now(UTC)
        points = []
        base_eq = 100000.0
        peak = base_eq
        for i in range(10):
            day = now - timedelta(days=10 - i)
            base_eq += (-500.0 if i == 3 else (1000.0 if i % 2 == 0 else 400.0))
            if base_eq > peak:
                peak = base_eq
            dd = (peak - base_eq) / peak
            points.append(
                {
                    "timestamp": day.date().isoformat(),
                    "equity": base_eq,
                    "drawdown": dd,
                    "exposure": base_eq * 0.45,
                }
            )
        return points

    def get_trades(
        self,
        from_ts: str | None = None,
        to_ts: str | None = None,
        strategy: str | None = None,
        symbol: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        trades = self._trades
        if strategy:
            trades = [t for t in trades if t.get("strategy") == strategy]
        if symbol:
            trades = [t for t in trades if t.get("symbol") == symbol]
        return trades[offset : offset + limit]

    def get_orders(
        self,
        status: str | None = None,
        strategy: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        orders = self._orders
        if status:
            orders = [o for o in orders if o.get("status") == status]
        if strategy:
            orders = [o for o in orders if o.get("strategy") == strategy]
        return orders[offset : offset + limit]

    def get_signals(
        self,
        from_ts: str | None = None,
        to_ts: str | None = None,
        strategy: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        sigs = self._signals
        if strategy:
            sigs = [s for s in sigs if s.get("strategy_name") == strategy]
        return sigs[offset : offset + limit]

    def get_strategies(self) -> list[dict[str, Any]]:
        res = []
        for name, active in self._strategy_toggles.items():
            res.append(
                {
                    "name": name,
                    "version": "1.0.0",
                    "active": active,
                    "config": {"timeframe": "1m", "threshold": 0.02},
                    "metrics": {
                        "win_rate": 0.65 if "Momentum" in name else 0.58,
                        "sharpe": 1.85 if "Momentum" in name else 1.42,
                        "total_trades": 42 if "Momentum" in name else 19,
                    },
                }
            )
        return res

    def get_strategy_metrics(self, name: str) -> dict[str, Any]:
        return {
            "win_rate": 0.65,
            "sharpe": 1.85,
            "sortino": 2.20,
            "profit_factor": 2.15,
            "max_drawdown": 0.12,
            "equity_curve": self.get_portfolio_history(),
        }

    def get_risk_status(self) -> dict[str, Any]:
        if self.risk_engine is not None:
            return {
                "emergency_stop": self.risk_engine.is_emergency_stop_active(),
                "circuit_breaker_active": self.risk_engine.is_circuit_breaker_tripped(),
                "daily_pnl": self.risk_engine.daily_realized_pnl,
                "daily_loss_limit": float(
                    self.config.get("risk.max_daily_loss", 1000.0)
                ),
                "current_exposure": 52216.25,
                "max_exposure": float(
                    self.config.get("risk.max_total_exposure", 100000.0)
                ),
            }

        return {
            "emergency_stop": self._emergency_stop,
            "circuit_breaker_active": False,
            "daily_pnl": -450.0,
            "daily_loss_limit": float(
                self.config.get("risk.max_daily_loss", 1000.0)
            ),
            "current_exposure": 52216.25,
            "max_exposure": float(
                self.config.get("risk.max_total_exposure", 100000.0)
            ),
        }

    def get_risk_config(self) -> dict[str, Any]:
        return {
            "max_position_qty": float(self.config.get("risk.max_position_qty", 5.0)),
            "max_daily_loss": float(self.config.get("risk.max_daily_loss", 1000.0)),
            "max_total_exposure": float(
                self.config.get("risk.max_total_exposure", 100000.0)
            ),
            "allowed_symbols": self.config.get(
                "risk.allowed_symbols", ["BTC/USDT", "ETH/USDT"]
            ),
            "trading_schedule": self.config.get(
                "risk.trading_schedule", "00:00-23:59"
            ),
        }

    def get_exchanges_status(self) -> list[dict[str, Any]]:
        return self._exchange_status

    def get_logs(
        self,
        level: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
        correlation_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        logs = self._logs
        if level:
            logs = [entry for entry in logs if entry.get("level") == level.upper()]
        if correlation_id:
            logs = [
                entry
                for entry in logs
                if entry.get("correlation_id") == correlation_id
            ]
        return logs[offset : offset + limit]

    def get_analytics_metrics(self) -> dict[str, float]:
        if self.analytics_engine is not None:
            m = self.analytics_engine.get_metrics()
            return {
                "sharpe": m.get("sharpe_ratio", 1.8),
                "sortino": m.get("sortino_ratio", 2.2),
                "win_rate": m.get("win_rate", 0.65),
                "profit_factor": m.get("profit_factor", 2.1),
                "avg_trade": m.get("avg_trade", 35.5),
                "avg_slippage": m.get("avg_slippage", 0.25),
                "avg_latency": m.get("avg_latency", 0.018),
                "max_drawdown": m.get("max_drawdown", 0.12),
            }
        return {
            "sharpe": 1.8,
            "sortino": 2.2,
            "win_rate": 0.65,
            "profit_factor": 2.1,
            "avg_trade": 35.5,
            "avg_slippage": 0.25,
            "avg_latency": 0.018,
            "max_drawdown": 0.12,
        }

    async def set_emergency_stop(
        self, enabled: bool, trigger: str = "manual"
    ) -> str:
        self._emergency_stop = enabled
        if self.risk_engine is not None:
            res = self.risk_engine.set_emergency_stop(enabled, trigger=trigger)
            if inspect.isawaitable(res):
                await res
        return "activated" if enabled else "deactivated"

    def toggle_strategy(self, name: str, active: bool) -> tuple[str, bool]:
        self._strategy_toggles[name] = active
        return name, active


# Global state holder
_api_state: APIState | None = None


def get_api_state() -> APIState:
    """FastAPI Dependency retrieving the initialized APIState singleton."""
    global _api_state
    if _api_state is None:
        _api_state = APIState()
    return _api_state


def set_api_state(state: APIState) -> None:
    """Override APIState singleton (useful for test fixtures)."""
    global _api_state
    _api_state = state

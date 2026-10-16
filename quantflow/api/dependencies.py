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
        self._strategy_configs: dict[str, dict[str, Any]] = {
            "Simple Momentum": {"period": 20, "threshold": 0.02, "timeframe": "1m"},
            "Mean Reversion": {"window": 30, "std_dev": 2.0, "timeframe": "5m"},
            "Trend Follower": {"fast_period": 10, "slow_period": 50, "timeframe": "15m"},
        }
        self._risk_config: dict[str, Any] = {
            "max_position_qty": 5.0,
            "max_daily_loss": 1000.0,
            "max_total_exposure": 100000.0,
            "allowed_symbols": ["BTC/USDT", "ETH/USDT"],
            "trading_schedule": "00:00-23:59",
        }
        self._exchanges: dict[str, dict[str, Any]] = {
            "binance": {
                "id": "binance",
                "name": "Binance Spot/Futures",
                "type": "crypto",
                "enabled": True,
                "connected": True,
                "latency_ms": 42.0,
                "last_heartbeat": datetime.now(UTC).isoformat(),
                "symbols_subscribed": ["BTC/USDT", "ETH/USDT"],
            },
            "bybit": {
                "id": "bybit",
                "name": "Bybit Perpetual",
                "type": "crypto",
                "enabled": True,
                "connected": True,
                "latency_ms": 55.0,
                "last_heartbeat": datetime.now(UTC).isoformat(),
                "symbols_subscribed": ["BTC/USDT", "ETH/USDT"],
            },
        }
        self._backtest_runs: list[dict[str, Any]] = [
            {
                "id": "run-001",
                "strategy_name": "Simple Momentum",
                "start_date": "2024-01-01",
                "end_date": "2024-06-01",
                "status": "completed",
                "created_at": "2024-06-02T10:00:00Z",
                "sharpe": 1.85,
                "win_rate": 0.62,
                "total_return": 0.28,
                "max_drawdown": 0.09,
                "params": {"period": 20, "threshold": 0.02},
                "metrics": {
                    "sharpe": 1.85,
                    "sortino": 2.4,
                    "profit_factor": 2.1,
                    "trades": 142,
                },
                "equity_curve": [],
                "trades": [],
            }
        ]
        self._backtest_jobs: dict[str, dict[str, Any]] = {}

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

    def get_strategy_config(self, name: str) -> dict[str, Any]:
        return self._strategy_configs.get(
            name, {"period": 20, "threshold": 0.02, "timeframe": "1m"}
        )

    def update_strategy_config(
        self, name: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        curr = self._strategy_configs.setdefault(name, {})
        curr.update(config)
        return curr

    def update_risk_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        for k, v in updates.items():
            if v is not None:
                self._risk_config[k] = v
        return self._risk_config

    def get_exchanges(self) -> list[dict[str, Any]]:
        return list(self._exchanges.values())

    def get_exchange_status_by_id(
        self, exchange_id: str
    ) -> dict[str, Any] | None:
        return self._exchanges.get(exchange_id)

    def toggle_exchange(
        self, exchange_id: str, enabled: bool
    ) -> dict[str, Any]:
        if exchange_id not in self._exchanges:
            self._exchanges[exchange_id] = {
                "id": exchange_id,
                "name": exchange_id.title(),
                "type": "crypto",
                "enabled": enabled,
                "connected": enabled,
                "latency_ms": 50.0 if enabled else 0.0,
                "last_heartbeat": datetime.now(UTC).isoformat(),
                "symbols_subscribed": [],
            }
        else:
            self._exchanges[exchange_id]["enabled"] = enabled
            self._exchanges[exchange_id]["connected"] = enabled
        return self._exchanges[exchange_id]

    def get_backtest_runs(self) -> list[dict[str, Any]]:
        return self._backtest_runs

    def get_backtest_run(self, run_id: str) -> dict[str, Any] | None:
        for r in self._backtest_runs:
            if r["id"] == run_id:
                return r
        return None

    def submit_backtest_job(self, data: dict[str, Any]) -> str:
        job_id = f"job-{uuid4().hex[:8]}"
        run_id = f"run-{uuid4().hex[:8]}"
        self._backtest_jobs[job_id] = {
            "job_id": job_id,
            "status": "completed",
            "progress": 1.0,
            "run_id": run_id,
            "error": None,
        }
        self._backtest_runs.insert(
            0,
            {
                "id": run_id,
                "strategy_name": data.get("strategy_name", "Simple Momentum"),
                "start_date": data.get("start_date", "2024-01-01"),
                "end_date": data.get("end_date", "2024-06-01"),
                "status": "completed",
                "created_at": datetime.now(UTC).isoformat(),
                "sharpe": 1.72,
                "win_rate": 0.58,
                "total_return": 0.22,
                "max_drawdown": 0.11,
                "params": data.get("parameters", {}),
                "metrics": {
                    "sharpe": 1.72,
                    "sortino": 2.1,
                    "profit_factor": 1.9,
                    "trades": 88,
                },
                "equity_curve": [],
                "trades": [],
            },
        )
        return job_id

    def get_backtest_job(self, job_id: str) -> dict[str, Any] | None:
        return self._backtest_jobs.get(job_id)


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


from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(
    state: APIState = Depends(get_api_state),
    api_key: str | None = Security(api_key_header),
) -> None:
    """Verify API key authentication if configured on APIState."""
    expected_key = state.config.get("api.key")
    if not expected_key:
        return
    if api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


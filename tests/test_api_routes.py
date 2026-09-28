"""Tests for QuantFlow FastAPI REST API routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from quantflow.api.app import app
from quantflow.api.dependencies import APIState, set_api_state


@pytest.fixture(autouse=True)
def reset_api_state() -> None:
    """Ensure clean APIState before each test."""
    set_api_state(APIState())


@pytest.fixture
def client() -> TestClient:
    """Test client for FastAPI app."""
    return TestClient(app)


def test_health_check(client: TestClient) -> None:
    """Verify health check endpoint returns status ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_get_portfolio_shape(client: TestClient) -> None:
    """Verify GET /api/portfolio returns required financial snapshot contract."""
    resp = client.get("/api/portfolio")
    assert resp.status_code == 200
    data = resp.json()

    assert "cash" in data
    assert "total_equity" in data
    assert "total_exposure" in data
    assert "realized_pnl" in data
    assert "unrealized_pnl" in data
    assert "positions" in data
    assert isinstance(data["positions"], list)
    assert len(data["positions"]) > 0

    pos = data["positions"][0]
    assert "symbol" in pos
    assert "quantity" in pos
    assert "avg_entry_price" in pos
    assert "unrealized_pnl" in pos


def test_get_portfolio_history(client: TestClient) -> None:
    """Verify GET /api/portfolio/history returns equity curve points."""
    resp = client.get(
        "/api/portfolio/history?from=2026-08-01&to=2026-08-20&interval=1d"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0

    pt = data[0]
    assert "timestamp" in pt
    assert "equity" in pt
    assert "drawdown" in pt
    assert "exposure" in pt


def test_get_trades_shape_and_pagination(client: TestClient) -> None:
    """Verify GET /api/trades returns execution history and supports filters."""
    resp = client.get("/api/trades?limit=2&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) <= 2

    trade = data[0]
    assert "fill_id" in trade
    assert "order_id" in trade
    assert "symbol" in trade
    assert "side" in trade
    assert "price" in trade
    assert "quantity" in trade
    assert "commission" in trade
    assert "timestamp_exchange" in trade
    assert "realized_pnl" in trade


def test_get_orders_shape(client: TestClient) -> None:
    """Verify GET /api/orders returns orders contract."""
    resp = client.get("/api/orders?status=FILLED&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0

    order = data[0]
    assert "order_id" in order
    assert "exchange_order_id" in order
    assert "symbol" in order
    assert "side" in order
    assert "type" in order
    assert "quantity" in order
    assert "filled_quantity" in order
    assert "avg_price" in order
    assert "status" in order
    assert "created_at" in order


def test_get_signals_shape(client: TestClient) -> None:
    """Verify GET /api/signals returns generated strategy signals."""
    resp = client.get("/api/signals?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0

    sig = data[0]
    assert "event_id" in sig
    assert "strategy_name" in sig
    assert "symbol" in sig
    assert "direction" in sig
    assert "confidence" in sig
    assert "timestamp_exchange" in sig


def test_get_strategies_and_metrics(client: TestClient) -> None:
    """Verify GET /api/strategies and detailed metrics endpoint."""
    resp = client.get("/api/strategies")
    assert resp.status_code == 200
    strats = resp.json()
    assert isinstance(strats, list)
    assert len(strats) > 0

    s0 = strats[0]
    assert "name" in s0
    assert "version" in s0
    assert "active" in s0
    assert "config" in s0
    assert "metrics" in s0
    assert "win_rate" in s0["metrics"]
    assert "sharpe" in s0["metrics"]
    assert "total_trades" in s0["metrics"]

    # Detailed metrics
    resp_metrics = client.get(f"/api/strategies/{s0['name']}/metrics")
    assert resp_metrics.status_code == 200
    det = resp_metrics.json()
    assert "win_rate" in det
    assert "sharpe" in det
    assert "sortino" in det
    assert "profit_factor" in det
    assert "max_drawdown" in det
    assert "equity_curve" in det


def test_toggle_strategy(client: TestClient) -> None:
    """Verify POST /api/strategies/{name}/toggle enables and disables strategies."""
    resp = client.post(
        "/api/strategies/Simple%20Momentum/toggle",
        json={"active": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Simple Momentum"
    assert data["active"] is False

    # Check that GET /api/strategies reflects update
    resp2 = client.get("/api/strategies")
    strat = next(s for s in resp2.json() if s["name"] == "Simple Momentum")
    assert strat["active"] is False


def test_get_risk_status_and_config(client: TestClient) -> None:
    """Verify GET /api/risk/status and GET /api/risk/config contracts."""
    resp_status = client.get("/api/risk/status")
    assert resp_status.status_code == 200
    st = resp_status.json()
    assert "emergency_stop" in st
    assert "circuit_breaker_active" in st
    assert "daily_pnl" in st
    assert "daily_loss_limit" in st
    assert "current_exposure" in st
    assert "max_exposure" in st

    resp_cfg = client.get("/api/risk/config")
    assert resp_cfg.status_code == 200
    cfg = resp_cfg.json()
    assert "max_position_qty" in cfg
    assert "max_daily_loss" in cfg
    assert "max_total_exposure" in cfg
    assert "allowed_symbols" in cfg
    assert "trading_schedule" in cfg


def test_post_emergency_stop(client: TestClient) -> None:
    """Verify POST /api/risk/emergency-stop engages and releases emergency stop."""
    # Activate
    r1 = client.post(
        "/api/risk/emergency-stop", json={"enabled": True, "trigger": "manual"}
    )
    assert r1.status_code == 200
    assert r1.json() == {"status": "activated"}

    r_check = client.get("/api/risk/status")
    assert r_check.json()["emergency_stop"] is True

    # Deactivate
    r2 = client.post(
        "/api/risk/emergency-stop", json={"enabled": False, "trigger": "manual"}
    )
    assert r2.status_code == 200
    assert r2.json() == {"status": "deactivated"}

    r_check2 = client.get("/api/risk/status")
    assert r_check2.json()["emergency_stop"] is False


def test_get_exchanges_status(client: TestClient) -> None:
    """Verify GET /api/exchanges/status returns adapter health."""
    resp = client.get("/api/exchanges/status")
    assert resp.status_code == 200
    exchanges = resp.json()
    assert isinstance(exchanges, list)
    assert len(exchanges) > 0

    ex = exchanges[0]
    assert "name" in ex
    assert "connected" in ex
    assert "latency_ms" in ex
    assert "last_heartbeat" in ex
    assert "symbols_subscribed" in ex


def test_get_logs(client: TestClient) -> None:
    """Verify GET /api/logs returns structured system logs."""
    resp = client.get("/api/logs?limit=5")
    assert resp.status_code == 200
    logs = resp.json()
    assert isinstance(logs, list)
    assert len(logs) > 0

    log = logs[0]
    assert "correlation_id" in log
    assert "level" in log
    assert "logger_name" in log
    assert "message" in log
    assert "metadata" in log
    assert "received_at" in log


def test_get_metrics(client: TestClient) -> None:
    """Verify GET /api/metrics returns system-wide performance snapshot."""
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    metrics = resp.json()
    assert "sharpe" in metrics
    assert "sortino" in metrics
    assert "win_rate" in metrics
    assert "profit_factor" in metrics
    assert "avg_trade" in metrics
    assert "avg_slippage" in metrics
    assert "avg_latency" in metrics
    assert "max_drawdown" in metrics

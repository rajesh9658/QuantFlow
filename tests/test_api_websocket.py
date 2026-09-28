"""Tests for QuantFlow WebSocket dashboard streaming endpoint."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from quantflow.api.app import app
from quantflow.api.dependencies import APIState, set_api_state
from quantflow.api.websocket import ws_manager
from quantflow.common.events import (
    FillEvent,
    PortfolioUpdateEvent,
    SignalEvent,
    SystemEvent,
    TickEvent,
)


@pytest.fixture(autouse=True)
def clean_state() -> APIState:
    """Provide fresh APIState with clean WS manager."""
    state = APIState()
    set_api_state(state)
    return state


def test_websocket_handshake_and_ping_pong() -> None:
    """Verify immediate 'connected' event and ping/pong roundtrip."""
    client = TestClient(app)
    with client.websocket_connect("/ws/dashboard?token=test-jwt") as ws:
        # 1. First message must be 'connected' acknowledgment
        first_raw = ws.receive_text()
        first_msg = json.loads(first_raw)
        assert first_msg["event"] == "connected"
        assert "session_id" in first_msg["data"]
        assert "server_time" in first_msg["data"]

        # 2. Send ping action
        ws.send_text(json.dumps({"action": "ping"}))
        pong_raw = ws.receive_text()
        pong_msg = json.loads(pong_raw)
        assert pong_msg["event"] == "pong"
        assert "server_time" in pong_msg["data"]


def test_websocket_unknown_and_malformed_actions() -> None:
    """Verify error envelope returned for malformed payload or unknown action."""
    client = TestClient(app)
    with client.websocket_connect("/ws/dashboard") as ws:
        ws.receive_text()  # connected handshake

        # Malformed JSON
        ws.send_text("INVALID_NOT_JSON")
        err1 = json.loads(ws.receive_text())
        assert err1["event"] == "error"
        assert err1["data"]["code"] == "INVALID_JSON"

        # Unknown action
        ws.send_text(json.dumps({"action": "unknown_cmd"}))
        err2 = json.loads(ws.receive_text())
        assert err2["event"] == "error"
        assert err2["data"]["code"] == "UNKNOWN_ACTION"


def test_websocket_ordered_event_delivery() -> None:
    """Verify events streamed through ws_manager reach connected client in order."""
    client = TestClient(app)
    with client.websocket_connect("/ws/dashboard") as ws:
        # 0. Initial handshake
        conn_msg = json.loads(ws.receive_text())
        assert conn_msg["event"] == "connected"

        # 1. Subscribe to BTC/USDT ticker
        ws.send_text(json.dumps({"action": "subscribe", "symbols": ["BTC/USDT"]}))

        # 2. PortfolioUpdateEvent
        p_event = PortfolioUpdateEvent(
            cash=75000.0,
            total_value=125000.0,
            total_exposure=50000.0,
            realized_pnl=5000.0,
            unrealized_pnl=1200.0,
            positions={"BTC/USDT": 1.0},
        )
        ws.portal.call(ws_manager.handle_portfolio_event, p_event)

        msg_p = json.loads(ws.receive_text())
        assert msg_p["event"] == "portfolio_update"
        assert msg_p["data"]["cash"] == 75000.0
        assert msg_p["data"]["total_equity"] == 125000.0
        assert len(msg_p["data"]["positions"]) == 1
        assert msg_p["data"]["positions"][0]["symbol"] == "BTC/USDT"

        # 3. FillEvent
        t_now = datetime.now(UTC)
        fill_event = FillEvent(
            order_id="order-xyz",
            symbol="BTC/USDT",
            side="buy",
            quantity=0.5,
            fill_price=51000.0,
            commission=12.50,
            realized_pnl=250.0,
            timestamp_exchange=t_now,
        )
        ws.portal.call(ws_manager.handle_fill_event, fill_event)

        msg_f = json.loads(ws.receive_text())
        assert msg_f["event"] == "fill"
        assert msg_f["data"]["symbol"] == "BTC/USDT"
        assert msg_f["data"]["price"] == 51000.0
        assert msg_f["data"]["quantity"] == 0.5
        assert msg_f["data"]["realized_pnl"] == 250.0

        # 4. SignalEvent
        sig_event = SignalEvent(
            strategy_id="Simple Momentum",
            symbol="BTC/USDT",
            side="buy",
            quantity=0.5,
            signal_strength=0.92,
        )
        ws.portal.call(ws_manager.handle_signal_event, sig_event)

        msg_s = json.loads(ws.receive_text())
        assert msg_s["event"] == "signal"
        assert msg_s["data"]["strategy_name"] == "Simple Momentum"
        assert msg_s["data"]["confidence"] == 0.92

        # 5. SystemEvent (Exchange status)
        sys_event = SystemEvent(
            source="binance",
            component="exchange_adapter",
            state="CONNECTED",
        )
        ws.portal.call(ws_manager.handle_system_event, sys_event)

        msg_sys = json.loads(ws.receive_text())
        assert msg_sys["event"] == "exchange_status"
        assert msg_sys["data"]["name"] == "binance"
        assert msg_sys["data"]["connected"] is True

        # 6. TickEvent (Subscribed)
        tick_event = TickEvent(
            symbol="BTC/USDT",
            exchange="binance",
            bid_price=51000.0,
            ask_price=51002.0,
            bid_size=1.5,
            ask_size=2.0,
            last_price=51001.0,
            last_size=0.1,
        )
        ws.portal.call(ws_manager.handle_tick_event, tick_event)

        msg_t = json.loads(ws.receive_text())
        assert msg_t["event"] == "ticker"
        assert msg_t["data"]["symbol"] == "BTC/USDT"
        assert msg_t["data"]["last"] == 51001.0

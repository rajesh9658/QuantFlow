"""FastAPI WebSocket streaming endpoint and connection manager."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from quantflow.api.dependencies import get_api_state
from quantflow.common.events import (
    FillEvent,
    PortfolioUpdateEvent,
    RiskEvent,
    SignalEvent,
    SystemEvent,
    TickEvent,
)

logger = logging.getLogger("quantflow.api.websocket")
ws_router = APIRouter(tags=["WebSocket"])


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class DashboardConnection:
    """Represents a single active WebSocket client connection."""

    def __init__(
        self, websocket: WebSocket, session_id: str, token: str | None = None
    ) -> None:
        self.websocket = websocket
        self.session_id = session_id
        self.token = token
        self.subscribed_symbols: set[str] = set()
        self.connected_at = datetime.now(UTC)

    async def send_event(self, event_name: str, data: Any) -> None:
        """Send a standardized JSON envelope to the client."""
        payload = {
            "event": event_name,
            "timestamp": _utc_now_iso(),
            "data": data,
        }
        await self.websocket.send_text(json.dumps(payload))


class DashboardWebSocketManager:
    """Manages active dashboard WebSocket clients and bridges EventBus events."""

    def __init__(self) -> None:
        self.active_connections: dict[str, DashboardConnection] = {}
        self._lock = asyncio.Lock()
        self._event_bus_subscribed = False

    async def connect(
        self, websocket: WebSocket, token: str | None = None
    ) -> DashboardConnection:
        """Accept connection, register client, and send immediate acknowledgment."""
        await websocket.accept()
        session_id = str(uuid4())
        connection = DashboardConnection(
            websocket=websocket, session_id=session_id, token=token
        )

        async with self._lock:
            self.active_connections[session_id] = connection

        # Send initial connected handshake per spec
        await connection.send_event(
            "connected",
            {
                "session_id": session_id,
                "server_time": _utc_now_iso(),
            },
        )
        logger.info(f"Dashboard client connected: {session_id}")
        return connection

    async def disconnect(self, session_id: str) -> None:
        """Unregister a disconnected client."""
        async with self._lock:
            self.active_connections.pop(session_id, None)
        logger.info(f"Dashboard client disconnected: {session_id}")

    async def broadcast(
        self,
        event_name: str,
        data: Any,
        symbol_filter: str | None = None,
    ) -> None:
        """Broadcast an event to all or filtered connected clients."""
        async with self._lock:
            connections = list(self.active_connections.values())

        for conn in connections:
            if symbol_filter and symbol_filter not in conn.subscribed_symbols:
                continue
            try:
                await conn.send_event(event_name, data)
            except Exception as e:
                logger.warning(f"Error sending event to {conn.session_id}: {e}")

    # ── EventBus Bridge Handlers ──────────────────────────────────────

    async def handle_portfolio_event(self, event: PortfolioUpdateEvent) -> None:
        """Bridge PortfolioUpdateEvent to WS clients."""
        payload = getattr(event, "payload", event)
        raw_positions = getattr(payload, "positions", {}) or {}
        positions = []
        if isinstance(raw_positions, dict):
            for sym, pos in raw_positions.items():
                qty = getattr(
                    pos,
                    "quantity",
                    pos if isinstance(pos, (int, float)) else 0.0,
                )
                positions.append(
                    {
                        "symbol": sym,
                        "quantity": qty,
                        "avg_entry_price": getattr(pos, "avg_entry_price", 0.0),
                        "unrealized_pnl": getattr(pos, "unrealized_pnl", 0.0),
                    }
                )

        data = {
            "cash": getattr(payload, "cash", 0.0),
            "total_equity": getattr(
                payload,
                "total_equity",
                getattr(payload, "total_value", 0.0),
            ),
            "total_exposure": getattr(payload, "total_exposure", 0.0),
            "realized_pnl": getattr(payload, "realized_pnl", 0.0),
            "unrealized_pnl": getattr(payload, "unrealized_pnl", 0.0),
            "positions": positions,
        }
        await self.broadcast("portfolio_update", data)

    async def handle_fill_event(self, event: FillEvent) -> None:
        """Bridge FillEvent to WS clients."""
        ts_exch = getattr(event, "timestamp_exchange", None)
        if ts_exch is not None and hasattr(ts_exch, "isoformat"):
            ts_str = ts_exch.isoformat()
        elif ts_exch is not None:
            ts_str = str(ts_exch)
        else:
            ts_str = _utc_now_iso()
        data = {
            "fill_id": str(getattr(event, "fill_id", uuid4())),
            "order_id": str(getattr(event, "order_id", "")),
            "symbol": getattr(event, "symbol", ""),
            "side": getattr(event, "side", "").lower(),
            "price": float(getattr(event, "fill_price", getattr(event, "price", 0.0))),
            "quantity": float(getattr(event, "quantity", 0.0)),
            "commission": float(getattr(event, "commission", 0.0)),
            "realized_pnl": float(getattr(event, "realized_pnl", 0.0)),
            "timestamp_exchange": ts_str,
        }
        await self.broadcast("fill", data)

    async def handle_signal_event(self, event: SignalEvent) -> None:
        """Bridge SignalEvent to WS clients."""
        metadata = getattr(event, "metadata", {}) or {}
        data = {
            "event_id": str(getattr(event, "event_id", uuid4())),
            "strategy_name": getattr(event, "strategy_id", "Strategy"),
            "symbol": getattr(event, "symbol", ""),
            "direction": getattr(event, "side", "").lower(),
            "confidence": float(getattr(event, "signal_strength", 1.0)),
            "metadata": metadata,
        }
        await self.broadcast("signal", data)

    async def handle_risk_event(self, event: RiskEvent | Any) -> None:
        """Bridge Risk status updates to WS clients."""
        action = getattr(event, "action", "")
        rule = getattr(event, "rule_name", "")
        is_emerg = "EMERGENCY" in rule.upper() or "EMERGENCY" in action.upper()
        is_cb = "CIRCUIT" in rule.upper() or "CIRCUIT" in action.upper()

        data = {
            "emergency_stop": is_emerg,
            "circuit_breaker_active": is_cb,
            "daily_pnl": float(getattr(event, "daily_pnl", 0.0)),
            "daily_loss_limit": float(getattr(event, "daily_loss_limit", 1000.0)),
            "current_exposure": float(getattr(event, "current_exposure", 0.0)),
            "max_exposure": float(getattr(event, "max_exposure", 100000.0)),
        }
        await self.broadcast("risk_status", data)

    async def handle_system_event(self, event: SystemEvent) -> None:
        """Bridge SystemEvent exchange state to WS clients."""
        comp = getattr(event, "component", "").lower()
        if comp in ("exchange_adapter", "binance", "exchange"):
            state = getattr(event, "state", "").upper()
            data = {
                "name": getattr(event, "source", "binance"),
                "connected": state == "CONNECTED",
                "latency_ms": 45.0 if state == "CONNECTED" else 0.0,
                "last_heartbeat": _utc_now_iso(),
                "symbols_subscribed": ["BTC/USDT", "ETH/USDT"],
            }
            await self.broadcast("exchange_status", data)

    async def handle_tick_event(self, event: TickEvent) -> None:
        """Bridge TickEvent to clients subscribed to that symbol."""
        symbol = getattr(event, "symbol", "")
        data = {
            "symbol": symbol,
            "bid": float(getattr(event, "bid_price", 0.0)),
            "ask": float(getattr(event, "ask_price", 0.0)),
            "last": float(getattr(event, "last_price", 0.0)),
        }
        await self.broadcast("ticker", data, symbol_filter=symbol)

    async def subscribe_to_event_bus(self, event_bus: Any) -> None:
        """Attach WS manager handlers to EventBus."""
        if self._event_bus_subscribed:
            return
        self._event_bus_subscribed = True
        try:
            await event_bus.subscribe(PortfolioUpdateEvent, self.handle_portfolio_event)
            await event_bus.subscribe(FillEvent, self.handle_fill_event)
            await event_bus.subscribe(SignalEvent, self.handle_signal_event)
            await event_bus.subscribe(RiskEvent, self.handle_risk_event)
            await event_bus.subscribe(SystemEvent, self.handle_system_event)
            await event_bus.subscribe(TickEvent, self.handle_tick_event)
            logger.info("DashboardWebSocketManager subscribed to EventBus")
        except Exception as e:
            logger.error(f"Failed subscribing to event bus: {e}")


# Global manager singleton
ws_manager = DashboardWebSocketManager()


@ws_router.websocket("/ws/dashboard")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(None),
) -> None:
    """WebSocket streaming endpoint for real-time dashboard updates."""
    state = get_api_state()
    # Automatically attach manager to event bus
    if state.event_bus:
        await ws_manager.subscribe_to_event_bus(state.event_bus)

    conn = await ws_manager.connect(websocket, token=token)
    try:
        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                await conn.send_event(
                    "error",
                    {
                        "code": "INVALID_JSON",
                        "message": "Malformed JSON payload",
                    },
                )
                continue

            action = msg.get("action", "").lower()

            if action == "ping":
                await conn.send_event("pong", {"server_time": _utc_now_iso()})

            elif action == "subscribe":
                symbols = msg.get("symbols", [])
                conn.subscribed_symbols.update(symbols)
                logger.debug(f"Client {conn.session_id} subscribed to {symbols}")

            elif action == "unsubscribe":
                symbols = msg.get("symbols", [])
                conn.subscribed_symbols.difference_update(symbols)
                logger.debug(
                    f"Client {conn.session_id} unsubscribed from {symbols}"
                )

            else:
                await conn.send_event(
                    "error",
                    {
                        "code": "UNKNOWN_ACTION",
                        "message": f"Action '{action}' is not recognized",
                    },
                )

    except WebSocketDisconnect:
        await ws_manager.disconnect(conn.session_id)
    except Exception as e:
        logger.error(f"WebSocket connection error for {conn.session_id}: {e}")
        await ws_manager.disconnect(conn.session_id)

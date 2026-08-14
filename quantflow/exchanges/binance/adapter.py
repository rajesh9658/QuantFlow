"""Binance exchange adapter using ccxt for REST and streaming."""

from __future__ import annotations

import asyncio
import enum
import logging
from datetime import UTC, datetime
from typing import Any

import ccxt.async_support as ccxt

from quantflow.common.events import (
    OrderBookEvent,
    OrderEvent,
    SystemEvent,
    TickEvent,
    TradeEvent,
)
from quantflow.core.event_bus import AsyncEventBus
from quantflow.core.interfaces import ExchangeAdapter

logger = logging.getLogger(__name__)


class ConnectionState(enum.StrEnum):
    """Observable reconnection states."""

    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    DISCONNECTED = "DISCONNECTED"


class BinanceAdapter(ExchangeAdapter):
    """Binance adapter with 3-state reconnect machine and paper-mode guard.

    Every state transition emits a ``SystemEvent`` via the event bus so
    external observers (health checks, dashboards) can react.
    """

    def __init__(
        self,
        event_bus: AsyncEventBus,
        *,
        mode: str = "paper",
        api_key: str = "",
        api_secret: str = "",
        max_retries: int = 10,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> None:
        if mode not in ("paper", "live"):
            raise ValueError(f"mode must be 'paper' or 'live', got {mode!r}")
        self._event_bus = event_bus
        self._mode = mode

        self._api_key = api_key
        self._api_secret = api_secret
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay

        self._state = ConnectionState.DISCONNECTED
        self._exchange: ccxt.binance | None = None
        self._running = False
        self._tasks: list[asyncio.Task[None]] = []
        self._subscribed_symbols: set[str] = set()
        self._retry_count = 0

    # ── state machine ────────────────────────────────────────────

    @property
    def state(self) -> ConnectionState:
        return self._state

    async def _set_state(self, new: ConnectionState, reason: str = "") -> None:
        old = self._state
        if old == new:
            return
        self._state = new
        logger.info("state %s → %s (%s)", old, new, reason or "ok")
        await self._event_bus.publish(
            SystemEvent(
                source="binance",
                component="exchange_adapter",
                state=new.value,
                reason=reason,
            )
        )

    # ── exchange lifecycle ───────────────────────────────────────

    def _make_exchange(self) -> ccxt.binance:
        opts: dict[str, Any] = {
            "apiKey": self._api_key,
            "secret": self._api_secret,
            "enableRateLimit": True,
        }
        if self._mode == "paper":
            opts["sandbox"] = True
        return ccxt.binance(opts)

    async def connect(self) -> None:
        if self._state == ConnectionState.CONNECTED:
            return
        self._exchange = self._make_exchange()
        await self._exchange.load_markets()
        self._running = True
        self._retry_count = 0
        await self._set_state(ConnectionState.CONNECTED, "initial connect")

    async def disconnect(self) -> None:
        self._running = False
        for t in self._tasks:
            if not t.done():
                t.cancel()
        self._tasks.clear()
        if self._exchange:
            await self._exchange.close()
            self._exchange = None
        await self._set_state(ConnectionState.DISCONNECTED, "manual disconnect")

    # ── market data ──────────────────────────────────────────────

    async def subscribe_market_data(self, symbols: list[str]) -> None:
        self._subscribed_symbols.update(symbols)
        for sym in symbols:
            self._tasks.append(asyncio.create_task(self._watch_ticker(sym)))
            self._tasks.append(asyncio.create_task(self._watch_order_book(sym)))
            self._tasks.append(asyncio.create_task(self._watch_trades(sym)))

    # ── watch loops ──────────────────────────────────────────────

    async def _watch_ticker(self, symbol: str) -> None:
        assert self._exchange is not None
        while self._running:
            try:
                t = await self._exchange.watch_ticker(symbol)
                await self._event_bus.publish(_ticker_to_event(symbol, t))
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("ticker watch %s failed", symbol)
                if not await self._handle_reconnect():
                    return

    async def _watch_order_book(self, symbol: str) -> None:
        assert self._exchange is not None
        while self._running:
            try:
                ob = await self._exchange.watch_order_book(symbol)
                await self._event_bus.publish(_orderbook_to_event(symbol, ob))
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("orderbook watch %s failed", symbol)
                if not await self._handle_reconnect():
                    return

    async def _watch_trades(self, symbol: str) -> None:
        assert self._exchange is not None
        while self._running:
            try:
                trades = await self._exchange.watch_trades(symbol)
                for tr in trades:
                    await self._event_bus.publish(_trade_to_event(symbol, tr))
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("trades watch %s failed", symbol)
                if not await self._handle_reconnect():
                    return

    # ── reconnect ────────────────────────────────────────────────

    async def _handle_reconnect(self) -> bool:
        """Try to reconnect with exponential backoff.

        Returns True if reconnected, False if gave up.
        """
        self._retry_count += 1
        if self._retry_count > self._max_retries:
            await self._set_state(
                ConnectionState.DISCONNECTED,
                f"max retries ({self._max_retries}) exceeded",
            )
            self._running = False
            return False

        await self._set_state(
            ConnectionState.RECONNECTING,
            f"attempt {self._retry_count}/{self._max_retries}",
        )

        delay = min(self._base_delay * (2 ** (self._retry_count - 1)), self._max_delay)
        await asyncio.sleep(delay)

        if not self._running:
            return False

        try:
            if self._exchange:
                await self._exchange.close()
            self._exchange = self._make_exchange()
            await self._exchange.load_markets()
            self._retry_count = 0
            await self._set_state(ConnectionState.CONNECTED, "reconnected")
            # Fresh orderbook snapshot is requested automatically by
            # the next watch_order_book iteration (ccxt fetches snapshot
            # on first call after new client).
            return True
        except Exception:
            logger.exception("reconnect attempt %d failed", self._retry_count)
            return await self._handle_reconnect()

    # ── orders (paper-guarded) ───────────────────────────────────

    def _guard_live(self) -> None:
        if self._mode != "paper":
            raise NotImplementedError(
                "Live trading not available before Sprint 15"
            )

    async def place_order(self, order: OrderEvent) -> str:
        self._guard_live()
        assert self._exchange is not None
        resp = await self._exchange.create_order(
            symbol=order.symbol,
            type=order.order_type.lower(),
            side=order.side.lower(),
            amount=order.quantity,
            price=order.price,
        )
        return str(resp.get("id", ""))

    async def cancel_order(self, order_id: str) -> bool:
        self._guard_live()
        assert self._exchange is not None
        await self._exchange.cancel_order(order_id)
        return True

    # ── balances ─────────────────────────────────────────────────

    async def get_balances(self) -> dict[str, float]:
        assert self._exchange is not None
        bal = await self._exchange.fetch_balance()
        return {k: float(v) for k, v in (bal.get("free") or {}).items() if float(v) > 0}


# ── message → event mapping (pure functions) ────────────────────


def _ticker_to_event(symbol: str, t: dict[str, Any]) -> TickEvent:
    return TickEvent(
        symbol=symbol,
        exchange="binance",
        bid_price=float(t.get("bid", 0)),
        ask_price=float(t.get("ask", 0)),
        bid_size=float(t.get("bidVolume", 0)),
        ask_size=float(t.get("askVolume", 0)),
        last_price=float(t.get("last", 0)),
        last_size=float(t.get("baseVolume", 0)),
    )


def _orderbook_to_event(symbol: str, ob: dict[str, Any]) -> OrderBookEvent:
    return OrderBookEvent(
        symbol=symbol,
        exchange="binance",
        bids=[[float(p), float(s)] for p, s in (ob.get("bids") or [])[:20]],
        asks=[[float(p), float(s)] for p, s in (ob.get("asks") or [])[:20]],
    )


def _trade_to_event(symbol: str, tr: dict[str, Any]) -> TradeEvent:
    return TradeEvent(
        symbol=symbol,
        exchange="binance",
        price=float(tr.get("price", 0)),
        size=float(tr.get("amount", 0)),
        trade_id=str(tr.get("id", "")),
    )

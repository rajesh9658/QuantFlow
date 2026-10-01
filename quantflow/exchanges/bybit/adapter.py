"""Bybit exchange adapter using ccxt for REST and streaming."""

from __future__ import annotations

import asyncio
import enum
import logging
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
from quantflow.market_data.raw import RawMarketData

logger = logging.getLogger(__name__)


class ConnectionState(enum.StrEnum):
    """Observable reconnection states."""

    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    DISCONNECTED = "DISCONNECTED"


class BybitAdapter(ExchangeAdapter):
    """Bybit adapter with 3-state reconnect machine and paper-mode guard.

    Every state transition emits a ``SystemEvent`` via the event bus so
    external observers (health checks, dashboards) can react.
    """

    def __init__(
        self,
        event_bus: AsyncEventBus | None = None,
        *,
        exchange_id: str = "bybit",
        mode: str = "paper",
        api_key: str = "",
        api_secret: str = "",
        max_retries: int = 10,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        sink: Any | None = None,
        symbol_mapper: Any | None = None,
        clock: Any | None = None,
        config: Any | None = None,
        cfg: dict[str, Any] | None = None,
    ) -> None:
        if mode not in ("paper", "live"):
            raise ValueError(f"mode must be 'paper' or 'live', got {mode!r}")
        self._event_bus = event_bus
        self.exchange_id = exchange_id
        self._mode = mode
        self.sink = sink
        self.symbol_mapper = symbol_mapper
        self.clock = clock
        self.config = config
        self.cfg = cfg or {}

        self._api_key = api_key
        self._api_secret = api_secret
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay

        self._state = ConnectionState.DISCONNECTED
        self._exchange: ccxt.bybit | None = None
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
        if self._event_bus is not None:
            await self._event_bus.publish(
                SystemEvent(
                    source=self.exchange_id,
                    component="exchange_adapter",
                    state=new.value,
                    reason=reason,
                )
            )

    # ── exchange lifecycle ───────────────────────────────────────

    def _make_exchange(self) -> ccxt.bybit:
        opts: dict[str, Any] = {
            "apiKey": self._api_key,
            "secret": self._api_secret,
            "enableRateLimit": True,
        }
        if self._mode == "paper":
            opts["sandbox"] = True
        return ccxt.bybit(opts)

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
                await self._on_ticker_received(symbol, t)
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
                await self._on_orderbook_received(symbol, ob)
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
                    await self._on_trade_received(symbol, tr)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("trades watch %s failed", symbol)
                if not await self._handle_reconnect():
                    return

    async def _on_ticker_received(self, symbol: str, t: dict[str, Any]) -> None:
        if self.sink and hasattr(self.sink, "on_raw_market_data"):
            from datetime import UTC, datetime

            now = self.clock.now() if self.clock else datetime.now(UTC)
            raw = RawMarketData(
                exchange_id=self.exchange_id,
                symbol_native=symbol,
                kind="ticker",
                data={
                    "bid": float(t.get("bid") or t.get("bid1Price") or 0.0),
                    "ask": float(t.get("ask") or t.get("ask1Price") or 0.0),
                    "last": float(t.get("last") or t.get("lastPrice") or 0.0),
                    "volume": float(t.get("baseVolume") or t.get("volume24h") or 0.0),
                    "timestamp_ms": int(t.get("timestamp") or t.get("ts") or 0),
                },
                received_at=now,
            )
            await self.sink.on_raw_market_data(raw)
        elif self._event_bus is not None:
            await self._event_bus.publish(_ticker_to_event(symbol, t, self.exchange_id))

    async def _on_orderbook_received(self, symbol: str, ob: dict[str, Any]) -> None:
        if self.sink and hasattr(self.sink, "on_raw_market_data"):
            from datetime import UTC, datetime

            now = self.clock.now() if self.clock else datetime.now(UTC)
            raw = RawMarketData(
                exchange_id=self.exchange_id,
                symbol_native=symbol,
                kind="orderbook",
                data={
                    "bids": ob.get("bids") or [],
                    "asks": ob.get("asks") or [],
                    "timestamp_ms": int(ob.get("timestamp") or ob.get("ts") or 0),
                },
                received_at=now,
            )
            await self.sink.on_raw_market_data(raw)
        elif self._event_bus is not None:
            await self._event_bus.publish(
                _orderbook_to_event(symbol, ob, self.exchange_id)
            )

    async def _on_trade_received(self, symbol: str, tr: dict[str, Any]) -> None:
        if self.sink and hasattr(self.sink, "on_raw_market_data"):
            from datetime import UTC, datetime

            now = self.clock.now() if self.clock else datetime.now(UTC)
            raw = RawMarketData(
                exchange_id=self.exchange_id,
                symbol_native=symbol,
                kind="trade",
                data={
                    "price": float(tr.get("price") or 0.0),
                    "size": float(tr.get("amount") or tr.get("size") or 0.0),
                    "trade_id": str(tr.get("id") or tr.get("trade_id") or ""),
                    "timestamp_ms": int(tr.get("timestamp") or tr.get("ts") or 0),
                },
                received_at=now,
            )
            await self.sink.on_raw_market_data(raw)
        elif self._event_bus is not None:
            await self._event_bus.publish(_trade_to_event(symbol, tr, self.exchange_id))

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
            return True
        except Exception:
            logger.exception("reconnect attempt %d failed", self._retry_count)
            return await self._handle_reconnect()

    # ── orders (paper-guarded) ───────────────────────────────────

    def _guard_live(self) -> None:
        if self._mode != "paper":
            raise NotImplementedError("Live trading not available before Sprint 15")

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


def _ticker_to_event(
    symbol: str, t: dict[str, Any], exchange_id: str = "bybit"
) -> TickEvent:
    return TickEvent(
        symbol=symbol,
        exchange=exchange_id,
        exchange_id=exchange_id,
        source=exchange_id,
        bid_price=float(t.get("bid", 0)),
        ask_price=float(t.get("ask", 0)),
        bid_size=float(t.get("bidVolume", 0)),
        ask_size=float(t.get("askVolume", 0)),
        last_price=float(t.get("last", 0)),
        last_size=float(t.get("baseVolume", 0)),
    )


def _orderbook_to_event(
    symbol: str, ob: dict[str, Any], exchange_id: str = "bybit"
) -> OrderBookEvent:
    return OrderBookEvent(
        symbol=symbol,
        exchange=exchange_id,
        exchange_id=exchange_id,
        source=exchange_id,
        bids=[[float(p), float(s)] for p, s in (ob.get("bids") or [])[:20]],
        asks=[[float(p), float(s)] for p, s in (ob.get("asks") or [])[:20]],
    )


def _trade_to_event(
    symbol: str, tr: dict[str, Any], exchange_id: str = "bybit"
) -> TradeEvent:
    return TradeEvent(
        symbol=symbol,
        exchange=exchange_id,
        exchange_id=exchange_id,
        source=exchange_id,
        price=float(tr.get("price", 0)),
        size=float(tr.get("amount", 0)),
        trade_id=str(tr.get("id", "")),
    )

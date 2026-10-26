"""Simple Momentum Strategy — emits SignalEvent only.

This module deliberately imports ONLY from ``quantflow.common.events``
and ``quantflow.core.interfaces``.  It has **no** import path to any
execution, order-placement, or exchange code.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from typing import Any

# NOTE: only events + abstract interfaces — no execution imports.
from quantflow.common.events import Event, SignalEvent, TickEvent, FillEvent, RejectedSignalEvent
from quantflow.core.event_bus import AsyncEventBus
from quantflow.core.interfaces import Strategy

logger = logging.getLogger(__name__)


class SimpleMomentumStrategy(Strategy):
    """N-period return momentum: BUY when return > threshold, SELL when < -threshold.

    Emits at most one signal per direction change to avoid spam.
    """

    def __init__(
        self,
        event_bus: AsyncEventBus,
        config: dict[str, Any] | None = None,
        clock: Any | None = None,
    ) -> None:
        cfg = config or {}
        self._bus = event_bus
        self._clock = clock
        self._symbol: str = cfg.get("symbol", "BTC/USDT")
        self._exchange_id: str | None = cfg.get("exchange_id")
        self._period: int = cfg.get("period", 20)
        self._threshold: float = cfg.get("threshold", 0.02)
        self._quantity: float | None = cfg.get("quantity")
        self._order_notional = float(cfg.get("order_notional", 20.0))
        self._held = 0.0
        self._pending = False
        if (self._period < 1 or not math.isfinite(self._threshold) or self._threshold <= 0
                or not math.isfinite(self._order_notional) or self._order_notional <= 0
                or (self._quantity is not None and (not math.isfinite(self._quantity) or self._quantity <= 0))):
            raise ValueError("Momentum period, threshold and size must be positive")

        self._prices: deque[float] = deque(maxlen=self._period + 1)
        self._last_side: str | None = None
        self._subscribed = False
        self._last_event_id: str | None = None

    def get_name(self) -> str:
        venue = f"@{self._exchange_id}" if self._exchange_id else ""
        return f"SimpleMomentum({self._symbol}{venue})"

    def update_config(self, config: dict[str, Any]) -> None:
        if self._pending or abs(self._held) > 1e-12:
            raise ValueError("Change strategy parameters only while flat with no pending signal")
        period = int(config.get("period", self._period))
        threshold = float(config.get("threshold", self._threshold))
        notional = float(config.get("order_notional", self._order_notional))
        if period < 1 or not math.isfinite(threshold) or threshold <= 0 or not math.isfinite(notional) or notional <= 0:
            raise ValueError("Strategy period, threshold and order_notional must be positive")
        self._period, self._threshold, self._order_notional = period, threshold, notional
        self._prices = deque(maxlen=period+1)
        self._last_side = None

    async def initialize(
        self,
        config: dict[str, Any] | None = None,
        clock: Any | None = None,
    ) -> None:
        """Initialize configuration and clock, and subscribe to market ticks."""
        if clock is not None:
            self._clock = clock
        cfg = config or {}
        if "symbol" in cfg:
            self._symbol = cfg["symbol"]
        if "exchange_id" in cfg:
            self._exchange_id = cfg["exchange_id"]
        if "period" in cfg:
            self._period = cfg["period"]
            self._prices = deque(maxlen=self._period + 1)
        if "threshold" in cfg:
            self._threshold = cfg["threshold"]

        if not self._subscribed and self._bus is not None:
            await self._bus.subscribe(TickEvent, self.on_event)
            await self._bus.subscribe(FillEvent, self._on_fill)
            await self._bus.subscribe(RejectedSignalEvent, self._on_rejected)
            self._subscribed = True

    async def stop(self) -> None:
        if self._subscribed:
            await self._bus.unsubscribe(TickEvent, self.on_event)
            await self._bus.unsubscribe(FillEvent, self._on_fill)
            await self._bus.unsubscribe(RejectedSignalEvent, self._on_rejected)
            self._subscribed = False

    async def _on_fill(self, event: FillEvent) -> None:
        venue = event.metadata.get("order_exchange_id")
        if self._exchange_id and venue and self._exchange_id != venue:
            return
        if event.symbol == self._symbol:
            self._held += event.quantity if event.side == "BUY" else -event.quantity
            self._pending = False
            if event.side == "SELL":
                self._last_side = None

    async def _on_rejected(self, event: RejectedSignalEvent) -> None:
        if event.strategy_id == self.get_name():
            self._pending = False
            self._last_side = None

    async def on_event(self, event: Event) -> None:
        if not getattr(self, "enabled", True):
            return
        if not isinstance(event, TickEvent):
            return
        if getattr(event, "event_id", None) and event.event_id == self._last_event_id:
            return
        self._last_event_id = getattr(event, "event_id", None)

        if event.symbol != self._symbol:
            return

        ev_exchange = getattr(event, "exchange_id", None) or getattr(
            event, "exchange", None
        )
        if self._exchange_id and ev_exchange and ev_exchange != self._exchange_id:
            return

        price = event.last_price
        if price <= 0:
            return

        self._prices.append(price)
        if len(self._prices) < self._period + 1:
            return

        old = self._prices[0]
        if old <= 0:
            return

        ret = (price - old) / old

        if ret > self._threshold:
            side = "BUY"
        elif ret < -self._threshold:
            side = "SELL"
        else:
            return  # inside dead-zone, no signal

        if self._pending or (side == "BUY" and self._held > 1e-12) or (side == "SELL" and self._held <= 1e-12):
            return

        if side == self._last_side:
            return  # already in this direction
        self._last_side = side
        self._pending = True

        sig_exchange = self._exchange_id or ev_exchange or "binance"
        sig_kwargs: dict[str, Any] = {
            "strategy_id": self.get_name(),
            "symbol": self._symbol,
            "exchange_id": sig_exchange,
            "side": side,
            "quantity": (self._quantity or self._order_notional / max(price, event.ask_price)) if side == "BUY" else self._held,
            "price": max(price, event.ask_price) if side == "BUY" else event.bid_price,
            "signal_strength": min(abs(ret) / self._threshold, 1.0),
        }
        if self._clock is not None:
            sig_kwargs["timestamp"] = self._clock.now()

        signal = SignalEvent(**sig_kwargs)
        await self._bus.publish(signal)
        logger.info("%s signal for %s (return=%.4f)", side, self._symbol, ret)

"""Simple Momentum Strategy — emits SignalEvent only.

This module deliberately imports ONLY from ``quantflow.common.events``
and ``quantflow.core.interfaces``.  It has **no** import path to any
execution, order-placement, or exchange code.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

# NOTE: only events + abstract interfaces — no execution imports.
from quantflow.common.events import Event, SignalEvent, TickEvent
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
        self._period: int = cfg.get("period", 20)
        self._threshold: float = cfg.get("threshold", 0.02)

        self._prices: deque[float] = deque(maxlen=self._period + 1)
        self._last_side: str | None = None
        self._subscribed = False
        self._last_event_id: str | None = None

    def get_name(self) -> str:
        return f"SimpleMomentum({self._symbol})"

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
        if "period" in cfg:
            self._period = cfg["period"]
            self._prices = deque(maxlen=self._period + 1)
        if "threshold" in cfg:
            self._threshold = cfg["threshold"]

        if not self._subscribed and self._bus is not None:
            await self._bus.subscribe(TickEvent, self.on_event)
            self._subscribed = True

    async def on_event(self, event: Event) -> None:
        if not isinstance(event, TickEvent):
            return
        if getattr(event, "event_id", None) and event.event_id == self._last_event_id:
            return
        self._last_event_id = getattr(event, "event_id", None)

        if event.symbol != self._symbol:
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

        if side == self._last_side:
            return  # already in this direction
        self._last_side = side

        sig_kwargs: dict[str, Any] = {
            "strategy_id": self.get_name(),
            "symbol": self._symbol,
            "side": side,
            "quantity": 1.0,
            "signal_strength": min(abs(ret) / self._threshold, 1.0),
        }
        if self._clock is not None:
            sig_kwargs["timestamp"] = self._clock.now()

        signal = SignalEvent(**sig_kwargs)
        await self._bus.publish(signal)
        logger.info("%s signal for %s (return=%.4f)", side, self._symbol, ret)

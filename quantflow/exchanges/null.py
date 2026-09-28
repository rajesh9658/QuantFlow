"""Null exchange adapter for replay and backtesting modes."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from quantflow.common.events import OrderEvent
from quantflow.core.clock import Clock, SystemClock
from quantflow.core.interfaces import ExchangeAdapter


class NullExchangeAdapter(ExchangeAdapter):
    """Null adapter that simulates exchange connectivity in replay or headless modes."""

    def __init__(self, clock: Clock | None = None) -> None:
        self.clock = clock or SystemClock()
        self._connected = False
        self._subscribed_symbols: set[str] = set()

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def subscribe_market_data(self, symbols: list[str]) -> None:
        self._subscribed_symbols.update(symbols)

    async def place_order(self, order: OrderEvent) -> str:
        return f"null-{uuid4().hex[:8]}"

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def get_balances(self) -> dict[str, float]:
        return {}

    def fetch_ticker(self, symbol: str) -> dict[str, Any] | None:
        return None

    def get_open_orders(self) -> list[dict[str, Any]]:
        return []

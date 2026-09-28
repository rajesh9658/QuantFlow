"""Strategy Engine: dispatches market events to strategies, isolates failures."""

from __future__ import annotations

import logging

from quantflow.common.events import Event, MarketDataEvent
from quantflow.core.clock import Clock
from quantflow.core.event_bus import AsyncEventBus
from quantflow.core.interfaces import Strategy

logger = logging.getLogger(__name__)


class StrategyEngine:
    """Subscribes to market events, dispatches to registered strategies.

    Strategies emit signals by publishing ``SignalEvent`` to the event bus
    they were constructed with.  The engine never exposes order-placement
    or execution methods — strategies can only produce signals.

    Each strategy's ``on_event`` runs inside its own ``try/except`` so one
    failure never blocks or crashes other strategies.
    """

    def __init__(
        self,
        event_bus: AsyncEventBus,
        strategies: dict[str, Strategy] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._bus = event_bus
        self._strategies: dict[str, Strategy] = strategies or {}
        self.clock = clock
        self._running = False

    # ── lifecycle ────────────────────────────────────────────────

    def register(self, name: str, strategy: Strategy) -> None:
        self._strategies[name] = strategy

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for strat in self._strategies.values():
            if hasattr(strat, "initialize"):
                await strat.initialize(clock=self.clock)
        await self._bus.subscribe(MarketDataEvent, self._dispatch)
        logger.info(
            "strategy engine started with %d strategies", len(self._strategies)
        )

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        await self._bus.unsubscribe(MarketDataEvent, self._dispatch)
        logger.info("strategy engine stopped")

    # ── dispatch ─────────────────────────────────────────────────

    async def _dispatch(self, event: Event) -> None:
        if not self._running:
            return
        for name, strat in self._strategies.items():
            try:
                await strat.on_event(event)
            except Exception:
                logger.exception(
                    "strategy %s failed on event %s", name, event.event_id
                )

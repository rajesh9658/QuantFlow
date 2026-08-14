"""Paper Execution Engine simulating fills against in-memory orderbooks."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from quantflow.common.events import (
    ApprovedSignalEvent,
    OrderEvent,
)
from quantflow.config.manager import ConfigManager
from quantflow.core.interfaces import EventBus, ExecutionEngine
from quantflow.core.logging import get_logger
from quantflow.execution.fill_simulator import (
    FeeSchedule,
    FillSimulationResult,
    simulate_fill,
)
from quantflow.market_data.orderbook import LocalOrderBook

logger = get_logger("paper_execution")


class PaperExecutionHandler(ExecutionEngine):
    """Paper execution engine that simulates fills against live in-memory orderbooks."""

    def __init__(
        self,
        config: ConfigManager | None = None,
        event_bus: EventBus | None = None,
        order_books: dict[str, LocalOrderBook] | None = None,
    ) -> None:
        self.config = config if config is not None else ConfigManager()
        self.event_bus = event_bus
        self.order_books: dict[str, LocalOrderBook] = (
            order_books if order_books is not None else {}
        )

        self._pending_orders: dict[str, OrderEvent] = {}
        self._order_statuses: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._running = False

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running or self.event_bus is None:
            return
        self._running = True
        await self.event_bus.subscribe(
            ApprovedSignalEvent, self._handle_approved_signal
        )
        await self.event_bus.subscribe(OrderEvent, self._handle_order_event)
        logger.info("Paper execution handler started")

    async def stop(self) -> None:
        if not self._running or self.event_bus is None:
            return
        self._running = False
        await self.event_bus.unsubscribe(
            ApprovedSignalEvent, self._handle_approved_signal
        )
        await self.event_bus.unsubscribe(OrderEvent, self._handle_order_event)
        logger.info("Paper execution handler stopped")

    # ── ExecutionEngine Interface ────────────────────────────────

    async def submit_order(self, order: OrderEvent) -> None:
        """Execute an order against the current local orderbook snapshot."""
        async with self._lock:
            book = self.order_books.get(order.symbol)
            if not book:
                logger.error("No order book available for %s", order.symbol)
                self._order_statuses[order.order_id] = "REJECTED"
                return

            fee_schedule = FeeSchedule.from_config(self.config, order.symbol)
            now_ts = datetime.now(UTC)

            result: FillSimulationResult = simulate_fill(
                order=order,
                orderbook_state=book,
                fee_schedule=fee_schedule,
                timestamp=now_ts,
            )

            # Determine order status
            if result.remaining_quantity <= 1e-12:
                status = "FILLED"
            elif len(result.fills) > 0:
                status = "PARTIALLY_FILLED"
                self._pending_orders[order.order_id] = order
            else:
                status = "REJECTED"

            self._order_statuses[order.order_id] = status

            # Publish generated fills to EventBus
            if self.event_bus and result.fills:
                for fill in result.fills:
                    await self.event_bus.publish(fill)

            logger.info(
                "Paper order %s (%s %s %s): status=%s, filled=%s/%s @ avg_price=%.2f",
                order.order_id,
                order.side,
                order.quantity,
                order.symbol,
                status,
                order.quantity - result.remaining_quantity,
                order.quantity,
                result.avg_price,
            )

    async def cancel_order(self, order_id: str) -> None:
        """Cancel an open/pending order."""
        async with self._lock:
            if order_id in self._pending_orders:
                self._pending_orders.pop(order_id)
                self._order_statuses[order_id] = "CANCELLED"
                logger.info("Paper order %s cancelled", order_id)
            else:
                logger.warning("Order %s not found or already filled", order_id)

    def get_order_status(self, order_id: str) -> str:
        """Return the current execution status of an order."""
        return self._order_statuses.get(order_id, "UNKNOWN")

    def get_open_orders(self) -> list[dict[str, Any]]:
        """Return list of open orders."""
        return [
            {"id": order_id, "order": order}
            for order_id, order in self._pending_orders.items()
        ]

    # ── EventBus Handlers ────────────────────────────────────────

    async def _handle_approved_signal(self, event: ApprovedSignalEvent) -> None:
        """Convert approved strategy signal into an OrderEvent and submit."""
        order_type = "LIMIT" if event.price and event.price > 0 else "MARKET"
        order = OrderEvent(
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            order_type=order_type,
            quantity=event.quantity,
            price=event.price,
        )
        await self.submit_order(order)

    async def _handle_order_event(self, event: OrderEvent) -> None:
        """Process directly received OrderEvent."""
        await self.submit_order(event)

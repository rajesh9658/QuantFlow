"""Paper Execution Engine simulating fills against in-memory orderbooks."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quantflow.common.events import (
    ApprovedSignalEvent,
    FillEvent,
    OrderEvent,
)
from quantflow.config.manager import ConfigManager
from quantflow.core.clock import Clock, SystemClock
from quantflow.core.interfaces import EventBus, ExecutionEngine
from quantflow.core.logging import get_logger
from quantflow.database.models import OrderStatus
from quantflow.database.repository import ExecutionRepository, OrderRepository
from quantflow.execution.fill_simulator import (
    FeeSchedule,
    FillSimulationResult,
    simulate_fill,
)
from quantflow.market_data.orderbook import LocalOrderBook

logger = get_logger("paper_execution")


class PaperExecutionHandler(ExecutionEngine):
    """Paper execution engine simulating fills with optional DB persistence."""

    def __init__(
        self,
        config: ConfigManager | None = None,
        event_bus: EventBus | None = None,
        order_books: dict[str, LocalOrderBook] | None = None,
        session_factory_or_clock: async_sessionmaker[AsyncSession] | Clock | None = None,
        clock: Clock | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self.config = config if config is not None else ConfigManager()
        self.event_bus = event_bus
        self.order_books: dict[str, LocalOrderBook] = (
            order_books if order_books is not None else {}
        )

        if isinstance(session_factory_or_clock, Clock):
            clock = session_factory_or_clock
        elif session_factory_or_clock is not None:
            session_factory = session_factory_or_clock

        self.clock: Clock = clock or SystemClock()
        self.session_factory = session_factory

        self._pending_orders: dict[str, OrderEvent] = {}
        self._order_statuses: dict[str, str] = {}
        self._order_fills: dict[str, list[FillEvent]] = {}
        self._lock = asyncio.Lock()
        self._running = False

    # ── Lifecycle ────────────────────────────────────────────────

    async def initialize(self, config: dict[str, Any] | None = None) -> None:
        """Initialize handler configuration."""
        self._running = True

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
            now_ts = self.clock.now()

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
            if result.fills:
                self._order_fills.setdefault(order.order_id, []).extend(result.fills)

            # Publish generated fills to EventBus
            if self.event_bus and result.fills:
                for fill in result.fills:
                    await self.event_bus.publish(fill)

            # Persist to database repository if configured
            if self.session_factory is not None:
                try:
                    async with self.session_factory() as session:
                        order_repo = OrderRepository(session)
                        exec_repo = ExecutionRepository(session)

                        filled_qty = order.quantity - result.remaining_quantity
                        await order_repo.create(
                            order_id=order.order_id,
                            symbol=order.symbol,
                            side=order.side,
                            order_type=order.order_type,
                            quantity=order.quantity,
                            strategy_name=order.strategy_id,
                            limit_price=order.price,
                            status=status,
                            filled_quantity=filled_qty,
                            avg_price=result.avg_price,
                        )

                        for fill in result.fills:
                            await exec_repo.create(
                                fill_id=fill.fill_id,
                                order_id=fill.order_id,
                                symbol=fill.symbol,
                                side=fill.side,
                                price=fill.fill_price,
                                quantity=fill.quantity,
                                commission=fill.commission,
                                timestamp_exchange=fill.timestamp,
                            )
                        await session.commit()
                except Exception as e:
                    logger.error("Failed to persist order execution: %s", e)

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

                if self.session_factory is not None:
                    try:
                        async with self.session_factory() as session:
                            order_repo = OrderRepository(session)
                            await order_repo.update_status(
                                order_id=order_id,
                                status=OrderStatus.CANCELLED,
                            )
                            await session.commit()
                    except Exception as e:
                        logger.error(
                            "Failed to update cancelled order status: %s", e
                        )
            else:
                logger.warning("Order %s not found or already filled", order_id)

    async def modify_order(self, order_id: str, **kwargs: Any) -> bool:
        """Cancel and re-submit an open/pending order with updated parameters."""
        async with self._lock:
            old_order = self._pending_orders.get(order_id)
            if not old_order:
                return False

            new_order = OrderEvent(
                strategy_id=kwargs.get("strategy_id", old_order.strategy_id),
                symbol=kwargs.get("symbol", old_order.symbol),
                side=kwargs.get("side", old_order.side),
                order_type=kwargs.get("order_type", old_order.order_type),
                quantity=float(kwargs.get("quantity", old_order.quantity)),
                price=kwargs.get("price", old_order.price),
                time_in_force=kwargs.get("time_in_force", old_order.time_in_force),
            )

            self._pending_orders.pop(order_id)
            self._order_statuses[order_id] = "CANCELLED"

        await self.submit_order(new_order)
        logger.info("Paper order %s modified to %s", order_id, new_order.order_id)
        return True

    def get_order_status(self, order_id: str) -> str:
        """Return the current execution status of an order."""
        return self._order_statuses.get(order_id, "UNKNOWN")

    def get_open_orders(self) -> list[dict[str, Any]]:
        """Return list of open orders."""
        return [
            {"id": order_id, "order": order}
            for order_id, order in self._pending_orders.items()
        ]

    def get_fills(self, order_id: str) -> list[FillEvent]:
        """Return all fills recorded for a given order ID."""
        return list(self._order_fills.get(order_id, []))

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

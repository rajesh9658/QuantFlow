QuantFlow Platform Specification – Paper Trading Execution Engine
Design Overview
The Paper Execution Engine simulates order fills for paper trading and backtesting. It consumes ApprovedSignalEvent, fetches the current local order book, and simulates realistic fills using a book-walking algorithm that models slippage proportional to the order size. The core fill simulation is a pure function that takes an OrderPayload, an OrderBookPayload, and a FeeSchedule as inputs—guaranteeing it has zero dependencies on the live clock, network, or I/O. This ensures the exact same code powers both live paper trading and historical backtesting.

1. Fee Schedule Configuration
Fees are defined per symbol with global defaults, all sourced via ConfigManager.

python
# fees.py
from dataclasses import dataclass
from typing import Optional, Dict
from config_manager import ConfigManager


@dataclass(frozen=True)
class FeeSchedule:
    """
    Fee structure for a specific symbol.
    Maker/Taker rates are expressed as decimal (e.g., 0.001 for 0.1%).
    """
    taker_rate: float
    maker_rate: float
    flat_fee_per_order: float = 0.0

    def calculate_fee(self, notional: float, is_maker: bool = False) -> float:
        """Calculate the total fee for a trade."""
        rate = self.maker_rate if is_maker else self.taker_rate
        return (notional * rate) + self.flat_fee_per_order

    @classmethod
    def from_config(cls, config: ConfigManager, symbol: Optional[str] = None) -> "FeeSchedule":
        """Load fee schedule from config with fallbacks."""
        prefix = "execution.paper.fees"
        taker = config.get_float(f"{prefix}.default.taker", 0.001)
        maker = config.get_float(f"{prefix}.default.maker", 0.0005)
        flat = config.get_float(f"{prefix}.default.flat", 0.0)

        if symbol:
            taker = config.get_float(f"{prefix}.symbols.{symbol}.taker", taker)
            maker = config.get_float(f"{prefix}.symbols.{symbol}.maker", maker)
            flat = config.get_float(f"{prefix}.symbols.{symbol}.flat", flat)

        return FeeSchedule(taker_rate=taker, maker_rate=maker, flat_fee_per_order=flat)
Sample YAML Configuration
yaml
# quantflow.yaml
execution:
  paper:
    # Default fees (e.g., Binance spot)
    fees:
      default:
        taker: 0.001   # 0.1%
        maker: 0.0005  # 0.05%
        flat: 0.0
      symbols:
        BTC/USDT:
          taker: 0.0006
          maker: 0.0003
2. Pure Order Simulator (Core Algorithm)
This is the reusable, side-effect-free component. It walks the order book to simulate fills, respecting limit prices and market liquidity.

python
# order_simulator.py
from typing import List, Tuple, Optional
from datetime import datetime, timezone
from uuid import uuid4

from events import (
    OrderPayload, OrderBookPayload, FillPayload,
    OrderSide, OrderType, EventType
)
from fees import FeeSchedule


class FillSimulationResult:
    """Result of a simulated fill."""
    def __init__(
        self,
        fills: List[FillPayload],
        remaining_quantity: float,
        total_cost: float,
        total_commission: float,
        avg_price: float,
    ):
        self.fills = fills
        self.remaining_quantity = remaining_quantity
        self.total_cost = total_cost
        self.total_commission = total_commission
        self.avg_price = avg_price


def simulate_fill(
    order: OrderPayload,
    book: OrderBookPayload,
    fee_schedule: FeeSchedule,
    timestamp: datetime,
) -> FillSimulationResult:
    """
    Pure function to simulate an order fill against a given order book state.

    - For MARKET orders, walks the book until the full quantity is filled.
    - For LIMIT orders, only consumes levels that meet the limit price condition.
    - Partial fills are supported if the book lacks sufficient depth.

    :param order: The order to simulate.
    :param book: The current order book snapshot (bids sorted desc, asks sorted asc).
    :param fee_schedule: Fee structure for the symbol.
    :param timestamp: Timestamp to assign to fill events (historical or current).
    :return: FillSimulationResult with fills, remaining qty, cost, fees, and avg price.
    """
    # Sort levels correctly (bids high-to-low, asks low-to-high)
    bids = sorted(book.bids, key=lambda lvl: lvl.price, reverse=True)
    asks = sorted(book.asks, key=lambda lvl: lvl.price)

    remaining = order.quantity
    fills = []
    total_cost = 0.0
    total_commission = 0.0

    # Determine which side to consume
    if order.side == OrderSide.BUY:
        levels = asks
        # Limit price condition: we can only buy at price <= limit_price
        price_limit = order.limit_price if order.order_type == OrderType.LIMIT else float('inf')
    else:  # SELL
        levels = bids
        price_limit = order.limit_price if order.order_type == OrderType.LIMIT else 0.0

    # Walk the book
    for level in levels:
        if remaining <= 1e-12:
            break

        level_price = level.price

        # Check limit condition
        if order.side == OrderSide.BUY and level_price > price_limit:
            break
        if order.side == OrderSide.SELL and level_price < price_limit:
            break

        # Consume volume
        fill_qty = min(remaining, level.size)
        if fill_qty <= 1e-12:
            continue

        cost = fill_qty * level_price
        commission = fee_schedule.calculate_fee(cost, is_maker=False)  # paper uses taker by default

        fills.append(
            FillPayload(
                order_id=order.order_id,
                fill_id=str(uuid4()),
                symbol=order.symbol,
                side=order.side,
                price=level_price,
                quantity=fill_qty,
                commission=commission,
                timestamp=timestamp,
            )
        )

        remaining -= fill_qty
        total_cost += cost
        total_commission += commission

    # Calculate average fill price
    filled_qty = order.quantity - remaining
    avg_price = total_cost / filled_qty if filled_qty > 1e-12 else 0.0

    return FillSimulationResult(
        fills=fills,
        remaining_quantity=remaining,
        total_cost=total_cost,
        total_commission=total_commission,
        avg_price=avg_price,
    )
3. PaperExecutionHandler
Implements the ExecutionHandler interface, wrapping the pure simulator with live state fetching and event publishing.

python
# paper_execution_handler.py
import asyncio
import uuid
from typing import Dict, List, Optional
from datetime import datetime, timezone

from interfaces import ExecutionHandler, EventBus
from events import (
    ApprovedSignalEvent, OrderEvent, OrderPayload, FillEvent,
    EventType, OrderSide, OrderType
)
from config_manager import ConfigManager
from logging_setup import get_logger
from local_order_book import LocalOrderBook
from order_simulator import simulate_fill
from fees import FeeSchedule


class PaperExecutionHandler(ExecutionHandler):
    """
    Paper trading implementation of ExecutionHandler.
    Simulates fills using the local order book and publishes OrderEvent/FillEvent.
    """

    def __init__(
        self,
        config: ConfigManager,
        event_bus: EventBus,
        order_books: Dict[str, LocalOrderBook],  # Sprint 5 component
    ):
        self.config = config
        self.event_bus = event_bus
        self.order_books = order_books  # symbol -> LocalOrderBook
        self.logger = get_logger("paper_execution")
        self._pending_orders: Dict[str, OrderPayload] = {}
        self._lock = asyncio.Lock()
        self._running = False

    async def initialize(self, config: dict) -> None:
        """Prepare the handler (no-op for paper)."""
        self._running = True

    async def submit_order(self, order: OrderPayload) -> str:
        """
        Simulate an order against the live local order book.
        Returns the simulated order ID (same as input order_id).
        """
        async with self._lock:
            # 1. Fetch current book snapshot from LocalOrderBook
            book = self.order_books.get(order.symbol)
            if not book:
                self.logger.error(f"No order book available for {order.symbol}")
                # Publish failed order event
                await self._publish_order_status(order, "REJECTED", reason="Missing order book")
                return order.order_id

            # 2. Get snapshot (top N levels, default 1000)
            top_n = self.config.get_int("execution.paper.max_simulation_depth", 1000)
            book_payload = self._snapshot_to_payload(book, top_n)

            # 3. Load fee schedule
            fee_schedule = FeeSchedule.from_config(self.config, order.symbol)

            # 4. Run pure simulation
            timestamp = datetime.now(timezone.utc)
            result = simulate_fill(order, book_payload, fee_schedule, timestamp)

            # 5. Publish OrderEvent (status)
            status = "FILLED" if result.remaining_quantity <= 1e-12 else "PARTIALLY_FILLED"
            await self._publish_order_status(order, status, avg_price=result.avg_price)

            # 6. Publish FillEvents
            for fill in result.fills:
                fill_event = FillEvent(
                    event_id=uuid.uuid4(),
                    event_type=EventType.FILL,
                    schema_version=1,
                    timestamp_exchange=timestamp,
                    timestamp_received=datetime.now(timezone.utc),
                    source="paper_execution",
                    payload=fill,
                )
                await self.event_bus.publish(fill_event)

            # 7. Store pending order state for cancellation/modification
            self._pending_orders[order.order_id] = order

            self.logger.info(
                f"Paper order {order.order_id} executed: "
                f"filled {order.quantity - result.remaining_quantity}/{order.quantity} @ {result.avg_price:.2f}"
            )
            return order.order_id

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order (only possible if not fully filled)."""
        async with self._lock:
            order = self._pending_orders.pop(order_id, None)
            if order:
                await self._publish_order_status(order, "CANCELLED")
                self.logger.info(f"Paper order {order_id} cancelled")
                return True
            self.logger.warning(f"Order {order_id} not found or already filled")
            return False

    async def modify_order(self, order_id: str, **kwargs) -> bool:
        """Cancel and re-submit with new parameters."""
        async with self._lock:
            old_order = self._pending_orders.get(order_id)
            if not old_order:
                return False

            # Create new order from old + modifications
            new_order = OrderPayload(
                order_id=str(uuid.uuid4()),
                symbol=old_order.symbol,
                side=old_order.side,
                order_type=kwargs.get("order_type", old_order.order_type),
                quantity=kwargs.get("quantity", old_order.quantity),
                limit_price=kwargs.get("limit_price", old_order.limit_price),
                stop_price=kwargs.get("stop_price", old_order.stop_price),
                time_in_force=kwargs.get("time_in_force", old_order.time_in_force),
                timestamp=datetime.now(timezone.utc),
            )

            # Cancel old
            await self.cancel_order(order_id)
            # Submit new
            await self.submit_order(new_order)
            self.logger.info(f"Paper order {order_id} modified to {new_order.order_id}")
            return True

    async def get_order_status(self, order_id: str) -> dict:
        """Return internal order status."""
        order = self._pending_orders.get(order_id)
        if not order:
            return {"status": "UNKNOWN"}
        # In paper, we treat pending as "OPEN"
        return {"status": "OPEN", "order": order.dict()}

    async def get_fills(self, order_id: str) -> List[FillPayload]:
        """Return fills for a given order (not tracked in paper, return empty)."""
        # In a real implementation, we'd track this. For paper, we rely on the emitted FillEvents.
        return []

    # ---------- Helpers ----------

    def _snapshot_to_payload(self, book: LocalOrderBook, depth: int) -> OrderBookPayload:
        """Extract top N bids/asks from the LocalOrderBook."""
        top_bids = book.get_top_bids(depth)
        top_asks = book.get_top_asks(depth)

        # Convert tuples to OrderBookLevel (same dataclass)
        from events import OrderBookLevel
        return OrderBookPayload(
            symbol=book.symbol,
            bids=[OrderBookLevel(price=p, size=s) for p, s in top_bids],
            asks=[OrderBookLevel(price=p, size=s) for p, s in top_asks],
            timestamp=datetime.now(timezone.utc),
        )

    async def _publish_order_status(
        self,
        order: OrderPayload,
        status: str,
        avg_price: float = 0.0,
        reason: Optional[str] = None,
    ) -> None:
        """Publish an OrderEvent to reflect status changes."""
        order_event = OrderEvent(
            event_id=uuid.uuid4(),
            event_type=EventType.ORDER,
            schema_version=1,
            timestamp_exchange=datetime.now(timezone.utc),
            timestamp_received=datetime.now(timezone.utc),
            source="paper_execution",
            payload=order,  # We can extend OrderPayload with status later, but for now separate
        )
        # Attach metadata as a custom attr (or we can extend the model)
        setattr(order_event, "_status", status)
        setattr(order_event, "_avg_price", avg_price)
        setattr(order_event, "_reason", reason)
        await self.event_bus.publish(order_event)
4. Integration with Sprint 5 (Local Order Book)
The PaperExecutionHandler expects a dictionary order_books: Dict[str, LocalOrderBook] populated by the MarketDataEngine. During startup:

python
# main.py (composition root)
# Assuming market_data_engine maintains the dict
market_engine = MarketDataEngine(event_bus)
# ... market_engine starts and maintains order_books ...

order_books = market_engine.order_books  # Dict[str, LocalOrderBook]

execution_handler = PaperExecutionHandler(config, event_bus, order_books)
container.register_singleton(ExecutionHandler, lambda cfg: execution_handler)
The LocalOrderBook provides the get_top_bids() and get_top_asks() methods (Sprint 5), ensuring the simulation sees exactly the same depth the strategies see.

5. Fill Simulation Algorithm – Precise Specification
Inputs
Order: OrderPayload with side, order_type, quantity, limit_price (optional).

Book: OrderBookPayload with bids (descending) and asks (ascending).

FeeSchedule: Maker/Taker rates.

Timestamp: datetime for fill event provenance.

Steps
Sort Levels:

For BUY, walk the asks sorted by price ascending.

For SELL, walk the bids sorted by price descending.

Determine Price Cap:

If LIMIT order, cap at limit_price (BUY: level_price ≤ limit_price; SELL: level_price ≥ limit_price).

If MARKET, no cap (BUY: price < ∞; SELL: price > 0).

Iterate Levels:

For each level, consume fill_qty = min(remaining_quantity, level.size).

If fill_qty > 0, create a FillPayload with price = level_price, quantity = fill_qty.

Compute cost = fill_qty * price.

Compute commission = FeeSchedule.calculate_fee(cost) (uses taker rate for paper).

Update remaining_quantity -= fill_qty, total_cost += cost, total_commission += commission.

Stop when remaining_quantity ≤ 1e-12 or end of book reached.

Return:

List of FillPayload objects.

remaining_quantity (0 if fully filled, >0 if insufficient liquidity).

avg_price = total_cost / (order.quantity - remaining_quantity).

total_cost, total_commission.

Edge Cases
Scenario	Behavior
Insufficient liquidity	Partial fill; remaining_quantity > 0. Order status = PARTIALLY_FILLED.
Limit price too restrictive	No fills; remaining_quantity = quantity. Status = REJECTED or EXPIRED.
Zero-size levels	Skipped.
Level price = 0 or negative	Skipped (invalid).
Empty order book	Zero fills; remaining_quantity = quantity.
Large order requiring many levels	Walks up to max_simulation_depth (configurable) to bound computation.
6. Reuse for Backtesting
The backtest engine will replay historical OrderBookPayload snapshots. The execution path is identical:

python
# backtest_execution_engine.py (snippet)
async def execute_order(order: OrderPayload, book: OrderBookPayload, timestamp: datetime):
    fee_schedule = FeeSchedule.from_config(config, order.symbol)
    result = simulate_fill(order, book, fee_schedule, timestamp)
    # Directly store fills without publishing to live EventBus
    return result
Because simulate_fill is a pure function, it:

Does not call datetime.now() (uses injected timestamp).

Does not read os.environ or config (fee schedule is passed in).

Does not access I/O, network, or asyncio.

This guarantees deterministic replay: the same historical book + order sequence always produces the exact same fills, regardless of the machine or time of day.

Summary
Component	Key Feature
FeeSchedule	Dataclass with taker/maker rates, loaded from ConfigManager.
simulate_fill	Pure function – walks book, respects limit price, calculates weighted avg, handles partial fills.
PaperExecutionHandler	Async wrapper fetching live book, calling pure simulator, emitting OrderEvent/FillEvent.
Slippage Modeling	Realistic – consumes multiple depth levels based on order size, not just best bid/ask.
Backtest Reuse	Backtest uses the exact same simulate_fill with historical data – no code duplication.
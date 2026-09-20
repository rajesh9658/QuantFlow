"""Pure order fill simulation for paper trading and deterministic backtesting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from quantflow.common.events import FillEvent, OrderEvent
from quantflow.config.manager import ConfigManager


@dataclass(frozen=True)
class FeeSchedule:
    """Fee structure for trading execution.

    Maker and taker rates are expressed as decimals (e.g., 0.001 = 0.1%).
    """

    taker_rate: float = 0.001
    maker_rate: float = 0.0005
    flat_fee_per_order: float = 0.0

    def calculate_fee(self, notional: float, is_maker: bool = False) -> float:
        """Calculate total fee for a given trade notional."""
        rate = self.maker_rate if is_maker else self.taker_rate
        return (notional * rate) + self.flat_fee_per_order

    @classmethod
    def from_config(
        cls, config: ConfigManager | Any, symbol: str | None = None
    ) -> FeeSchedule:
        """Load fee schedule from ConfigManager with symbol and default fallbacks."""
        prefix = "execution.paper.fees"

        def _get_val(key: str, default: float) -> float:
            if hasattr(config, "get_float"):
                return float(config.get_float(key, default))
            if hasattr(config, "get"):
                v = config.get(key, default)
                return float(v) if v is not None else default
            return default

        taker = _get_val(f"{prefix}.default.taker", 0.001)
        maker = _get_val(f"{prefix}.default.maker", 0.0005)
        flat = _get_val(f"{prefix}.default.flat", 0.0)

        if symbol:
            taker = _get_val(f"{prefix}.symbols.{symbol}.taker", taker)
            maker = _get_val(f"{prefix}.symbols.{symbol}.maker", maker)
            flat = _get_val(f"{prefix}.symbols.{symbol}.flat", flat)

        return cls(taker_rate=taker, maker_rate=maker, flat_fee_per_order=flat)


@dataclass
class FillSimulationResult:
    """Result of pure order fill simulation against orderbook liquidity."""

    fills: list[FillEvent]
    remaining_quantity: float
    total_cost: float
    total_commission: float
    avg_price: float


def _extract_levels(raw_levels: Any) -> list[tuple[float, float]]:
    """Normalize raw level structures to list of (price, size) tuples."""
    levels: list[tuple[float, float]] = []
    if not raw_levels:
        return levels
    for item in raw_levels:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                p, s = float(item[0]), float(item[1])
            except (ValueError, TypeError):
                continue
        elif hasattr(item, "price") and hasattr(item, "size"):
            try:
                p, s = float(item.price), float(item.size)
            except (ValueError, TypeError):
                continue
        elif isinstance(item, dict):
            raw_p = item.get("price")
            if raw_p is None:
                raw_p = item.get("p")
            if raw_p is None:
                raw_p = 0.0

            raw_s = item.get("size")
            if raw_s is None:
                raw_s = item.get("q")
            if raw_s is None:
                raw_s = item.get("amount", 0.0)
            if raw_s is None:
                raw_s = 0.0
            try:
                p, s = float(raw_p), float(raw_s)
            except (ValueError, TypeError):
                continue
        else:
            continue
        if p > 0.0 and s > 0.0:
            levels.append((p, s))
    return levels


def _extract_book_sides(
    book_state: Any,
    depth: int = 1000,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Extract (bids, asks) from LocalOrderBook, OrderBookEvent, dict, or tuple."""
    if hasattr(book_state, "depth") and callable(book_state.depth):
        bids_raw, asks_raw = book_state.depth(depth)
    elif hasattr(book_state, "get_top_bids") and hasattr(book_state, "get_top_asks"):
        bids_raw = book_state.get_top_bids(depth)
        asks_raw = book_state.get_top_asks(depth)
    elif hasattr(book_state, "bids") and hasattr(book_state, "asks"):
        bids_raw, asks_raw = book_state.bids, book_state.asks
    elif isinstance(book_state, dict):
        bids_raw, asks_raw = book_state.get("bids", []), book_state.get("asks", [])
    elif isinstance(book_state, (tuple, list)) and len(book_state) >= 2:
        bids_raw, asks_raw = book_state[0], book_state[1]
    else:
        bids_raw, asks_raw = [], []

    return _extract_levels(bids_raw), _extract_levels(asks_raw)


def simulate_fill(
    order: OrderEvent | Any,
    orderbook_state: Any,
    fee_schedule: FeeSchedule,
    timestamp: datetime | None = None,
) -> FillSimulationResult:
    """Simulate order execution by walking the orderbook depth.

    Pure function: Zero I/O, zero network, zero system clock access.
    Deterministic timestamps are explicitly passed in (defaults to fixed UTC epoch).

    Args:
        order: The order to execute (OrderEvent, dict, or compatible object).
        orderbook_state: Order book state (LocalOrderBook, OrderBookEvent, dict, etc.).
        fee_schedule: FeeSchedule specifying taker/maker rates.
        timestamp: Deterministic timestamp for generated FillEvents.

    Returns:
        FillSimulationResult containing fills, remaining quantity, costs, and avg price.
    """
    ts = timestamp if timestamp is not None else datetime(2026, 1, 1, tzinfo=UTC)

    # Extract order fields supporting dicts, OrderEvent, and duck-typed objects
    if isinstance(order, dict):
        order_id = str(order.get("order_id", "sim_order"))
        symbol = str(order.get("symbol", ""))
        side = str(order.get("side", "BUY")).upper()
        order_type = str(order.get("order_type", "MARKET")).upper()
        quantity = float(order.get("quantity", 0.0))
        raw_price = (
            order.get("price")
            if order.get("price") is not None
            else order.get("limit_price")
        )
        limit_price = float(raw_price) if raw_price is not None else None
    else:
        order_id = str(getattr(order, "order_id", "sim_order"))
        symbol = str(getattr(order, "symbol", ""))
        side = str(getattr(order, "side", "BUY")).upper()
        order_type = str(getattr(order, "order_type", "MARKET")).upper()
        quantity = float(getattr(order, "quantity", 0.0))
        raw_price = getattr(order, "price", None)
        if raw_price is None:
            raw_price = getattr(order, "limit_price", None)
        limit_price = float(raw_price) if raw_price is not None else None

    bids_levels, asks_levels = _extract_book_sides(orderbook_state)

    # Sort levels correctly:
    # BUY consumes ASKS (sorted ascending by price)
    # SELL consumes BIDS (sorted descending by price)
    price_limit: float
    if side == "BUY":
        levels = sorted(asks_levels, key=lambda x: x[0])
        is_limit = order_type == "LIMIT" and limit_price is not None
        price_limit = (
            limit_price if is_limit and limit_price is not None else float("inf")
        )
    else:
        levels = sorted(bids_levels, key=lambda x: x[0], reverse=True)
        is_limit = order_type == "LIMIT" and limit_price is not None
        price_limit = (
            limit_price if is_limit and limit_price is not None else 0.0
        )

    remaining = max(0.0, quantity)
    fills: list[FillEvent] = []
    total_cost = 0.0
    total_commission = 0.0

    # Walk the orderbook
    for idx, (level_price, level_size) in enumerate(levels):
        if remaining <= 1e-12:
            break

        # Check limit price boundary
        if side == "BUY" and level_price > price_limit:
            break
        if side == "SELL" and level_price < price_limit:
            break

        fill_qty = min(remaining, level_size)
        if fill_qty <= 1e-12:
            continue

        cost = fill_qty * level_price
        commission = fee_schedule.calculate_fee(cost, is_maker=False)

        fill_event = FillEvent(
            fill_id=f"{order_id}_fill_{idx}",
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=fill_qty,
            fill_price=level_price,
            commission=commission,
            exchange="paper",
            timestamp=ts,
        )
        fills.append(fill_event)

        remaining -= fill_qty
        total_cost += cost
        total_commission += commission

    filled_qty = quantity - remaining
    avg_price = total_cost / filled_qty if filled_qty > 1e-12 else 0.0

    return FillSimulationResult(
        fills=fills,
        remaining_quantity=remaining,
        total_cost=total_cost,
        total_commission=total_commission,
        avg_price=avg_price,
    )

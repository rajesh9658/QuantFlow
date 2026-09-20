"""Portfolio Engine maintaining single source of truth for financial state."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quantflow.common.events import FillEvent, PortfolioUpdateEvent
from quantflow.config.manager import ConfigManager
from quantflow.core.interfaces import EventBus, PortfolioManager
from quantflow.core.logging import get_logger
from quantflow.database.repository import (
    PortfolioRepository,
    PositionRepository,
)

logger = get_logger("portfolio_engine")

PriceProvider = (
    Callable[[str], Awaitable[float | None]]
    | Callable[[str], float | None]
)


@dataclass
class PositionState:
    """Internal representation of a single position."""

    symbol: str
    quantity: float  # Net quantity (positive = long, negative = short)
    avg_entry_price: float  # Weighted average cost basis per unit

    def total_cost_basis(self) -> float:
        """Return total cost basis of the position."""
        return self.quantity * self.avg_entry_price

    def is_empty(self) -> bool:
        """Check if position is flat."""
        return abs(self.quantity) < 1e-12


@dataclass
class Position:
    """External snapshot of a single position."""

    symbol: str
    quantity: float
    avg_price: float


@dataclass
class PortfolioState:
    """Full portfolio financial state snapshot."""

    cash: float = 0.0
    positions: dict[str, PositionState] = field(default_factory=dict)
    realized_pnl: float = 0.0
    total_equity: float = 0.0  # Cash + mark-to-market value of positions
    total_exposure: float = 0.0  # sum(abs(qty) * current_price)
    unrealized_pnl: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))


class PortfolioEngine(PortfolioManager):
    """Maintains the trading system's financial state.

    Consumes FillEvent messages, updates cash and positions using Weighted Average Cost
    (WAC) basis, computes realized and mark-to-market unrealized PnL, persists state
    to repositories if configured, and emits PortfolioUpdateEvent on state changes.
    """

    def __init__(
        self,
        config: ConfigManager | None = None,
        event_bus: EventBus | None = None,
        price_provider: PriceProvider | None = None,
        initial_cash: float | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        portfolio_id: str = "quantflow_main",
    ) -> None:
        self.config = config if config is not None else ConfigManager()
        self.event_bus = event_bus
        self.price_provider = price_provider
        self.session_factory = session_factory
        self.portfolio_id = portfolio_id

        if initial_cash is not None:
            start_cash = float(initial_cash)
        else:
            start_cash = float(
                self.config.get("portfolio.initial_cash", 100000.0)
            )

        self.state = PortfolioState(
            cash=start_cash,
            total_equity=start_cash,
            last_updated=datetime.now(UTC),
        )
        self._last_prices: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._running = False

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the engine and subscribe to FillEvent."""
        if self._running:
            return
        self._running = True

        if self.session_factory is not None:
            try:
                async with self.session_factory() as session:
                    port_repo = PortfolioRepository(session)
                    pos_repo = PositionRepository(session)

                    port = await port_repo.get(self.portfolio_id)
                    if port is not None:
                        self.state.cash = float(port.cash)
                        self.state.realized_pnl = float(port.realized_pnl)

                    db_positions = await pos_repo.get_all(self.portfolio_id)
                    for p in db_positions:
                        p_qty = float(p.quantity)
                        p_avg = float(p.avg_entry_price)
                        if abs(p_qty) >= 1e-12:
                            self.state.positions[p.symbol] = PositionState(
                                symbol=p.symbol,
                                quantity=p_qty,
                                avg_entry_price=p_avg,
                            )
                            self._last_prices[p.symbol] = p_avg
                    await self._recalculate_valuation()
            except Exception as e:
                logger.warning(
                    "Failed to load persisted portfolio state: %s", e
                )

        if self.event_bus is not None:
            await self.event_bus.subscribe(FillEvent, self.handle_fill)
        logger.info(
            "Portfolio Engine started with cash %.2f", self.state.cash
        )

    async def stop(self) -> None:
        """Stop the engine and unsubscribe from event bus."""
        if not self._running or self.event_bus is None:
            return
        self._running = False
        await self.event_bus.unsubscribe(FillEvent, self.handle_fill)
        logger.info("Portfolio Engine stopped")

    # ── Core Financial Logic ─────────────────────────────────────

    def _update_cash(self, fill: FillEvent | Any) -> None:
        """Update cash balance for a trade.

        BUY:  cash -= (price * quantity) + commission
        SELL: cash += (price * quantity) - commission
        """
        p_fill = float(
            getattr(fill, "fill_price", getattr(fill, "price", 0.0))
        )
        q_fill_abs = float(getattr(fill, "quantity", 0.0))
        side = str(getattr(fill, "side", "BUY")).upper()
        commission = float(getattr(fill, "commission", 0.0))

        cost = p_fill * q_fill_abs
        if side == "BUY":
            self.state.cash -= cost + commission
        else:
            self.state.cash += cost - commission

    def _update_position(self, fill: FillEvent | Any) -> None:
        """Update position using Weighted Average Cost (WAC) method.

        Handles new positions, additions to existing positions, reductions
        with realized PnL calculation, full closes, and position side-flips.
        """
        symbol = str(getattr(fill, "symbol", ""))
        side = str(getattr(fill, "side", "BUY")).upper()
        p_fill = float(
            getattr(fill, "fill_price", getattr(fill, "price", 0.0))
        )
        qty = float(getattr(fill, "quantity", 0.0))
        q_fill = qty if side == "BUY" else -qty

        self._last_prices[symbol] = p_fill

        pos = self.state.positions.get(symbol)
        q_old = pos.quantity if pos else 0.0
        p_avg = pos.avg_entry_price if pos else 0.0
        q_new = q_old + q_fill

        # Case 1: No existing position
        if abs(q_old) < 1e-12:
            if abs(q_new) >= 1e-12:
                self.state.positions[symbol] = PositionState(
                    symbol=symbol,
                    quantity=q_new,
                    avg_entry_price=p_fill,
                )
            return

        # Case 2: Adding to the same side (q_old and q_fill have the same sign)
        if (q_old * q_fill > 0) or (q_old * q_new > 0 and abs(q_new) > abs(q_old)):
            new_avg = (q_old * p_avg + q_fill * p_fill) / q_new
            self.state.positions[symbol] = PositionState(
                symbol=symbol,
                quantity=q_new,
                avg_entry_price=new_avg,
            )
            return

        # Case 3: Reducing same side without crossing zero (same sign, smaller size)
        if q_old * q_new > 0 and abs(q_new) <= abs(q_old):
            closed_qty = abs(q_fill)
            if q_old > 0:  # Long reduction (selling)
                realized = (p_fill - p_avg) * closed_qty
            else:  # Short reduction (buying to cover)
                realized = (p_avg - p_fill) * closed_qty

            self.state.realized_pnl += realized

            if abs(q_new) < 1e-12:
                self.state.positions.pop(symbol, None)
            else:
                self.state.positions[symbol] = PositionState(
                    symbol=symbol,
                    quantity=q_new,
                    avg_entry_price=p_avg,
                )
            return

        # Case 4: Crossing zero or reducing to exactly zero (q_old * q_new <= 0)
        closed_qty = abs(q_old)
        if q_old > 0:  # Full close of long
            realized = (p_fill - p_avg) * closed_qty
        else:  # Full close of short
            realized = (p_avg - p_fill) * closed_qty

        self.state.realized_pnl += realized
        self.state.positions.pop(symbol, None)

        # If remaining quantity opened on opposite side (flip)
        if abs(q_new) >= 1e-12:
            self.state.positions[symbol] = PositionState(
                symbol=symbol,
                quantity=q_new,
                avg_entry_price=p_fill,
            )

    async def _get_current_price(
        self, symbol: str, fallback_price: float
    ) -> float:
        """Resolve current mark price using price_provider or cached price."""
        if self.price_provider is not None:
            try:
                res = self.price_provider(symbol)
                if inspect.isawaitable(res):
                    val = await res
                else:
                    val = res
                if val is not None and float(val) > 0:
                    self._last_prices[symbol] = float(val)
                    return float(val)
            except Exception as e:
                logger.warning(
                    "Price provider lookup failed for %s: %s", symbol, e
                )

        return self._last_prices.get(symbol, fallback_price)

    async def _recalculate_valuation(self) -> None:
        """Recalculate MTM total equity, unrealized PnL, and gross exposure."""
        total_mtm = 0.0
        total_upl = 0.0
        total_exposure = 0.0

        for symbol, pos in list(self.state.positions.items()):
            if pos.is_empty():
                continue

            current_price = await self._get_current_price(
                symbol, pos.avg_entry_price
            )
            q = pos.quantity
            avg = pos.avg_entry_price

            total_mtm += q * current_price
            total_exposure += abs(q) * current_price

            if q > 0:
                total_upl += (current_price - avg) * q
            else:
                total_upl += (avg - current_price) * abs(q)

        self.state.unrealized_pnl = total_upl
        self.state.total_exposure = total_exposure
        self.state.total_equity = self.state.cash + total_mtm
        self.state.last_updated = datetime.now(UTC)

    def _recalculate_valuation_sync(self) -> None:
        """Synchronous valuation update using cached/average prices."""
        total_mtm = 0.0
        total_upl = 0.0
        total_exposure = 0.0

        for symbol, pos in list(self.state.positions.items()):
            if pos.is_empty():
                continue

            current_price = self._last_prices.get(
                symbol, pos.avg_entry_price
            )
            q = pos.quantity
            avg = pos.avg_entry_price

            total_mtm += q * current_price
            total_exposure += abs(q) * current_price

            if q > 0:
                total_upl += (current_price - avg) * q
            else:
                total_upl += (avg - current_price) * abs(q)

        self.state.unrealized_pnl = total_upl
        self.state.total_exposure = total_exposure
        self.state.total_equity = self.state.cash + total_mtm
        self.state.last_updated = datetime.now(UTC)

    # ── EventBus Publishing ──────────────────────────────────────

    async def _publish_update(self) -> None:
        """Publish a single PortfolioUpdateEvent snapshot to the event bus."""
        if self.event_bus is None:
            return

        pos_dict = {
            sym: pos.quantity
            for sym, pos in self.state.positions.items()
            if not pos.is_empty()
        }
        pos_detail = {
            sym: {
                "quantity": pos.quantity,
                "avg_price": pos.avg_entry_price,
            }
            for sym, pos in self.state.positions.items()
            if not pos.is_empty()
        }

        event = PortfolioUpdateEvent(
            cash=self.state.cash,
            total_value=self.state.total_equity,
            positions=pos_dict,
            realized_pnl=self.state.realized_pnl,
            unrealized_pnl=self.state.unrealized_pnl,
            total_exposure=self.state.total_exposure,
            positions_detail=pos_detail,
            timestamp=self.state.last_updated,
        )
        await self.event_bus.publish(event)
        logger.debug(
            "Portfolio update published: Cash=%.2f, Eq=%.2f, UPL=%.2f",
            self.state.cash,
            self.state.total_equity,
            self.state.unrealized_pnl,
        )

    async def _persist_state(self) -> None:
        """Persist current portfolio and position state to database."""
        if self.session_factory is None:
            return
        try:
            async with self.session_factory() as session:
                port_repo = PortfolioRepository(session)
                pos_repo = PositionRepository(session)

                await port_repo.upsert(
                    portfolio_id=self.portfolio_id,
                    cash=self.state.cash,
                    total_equity=self.state.total_equity,
                    total_exposure=self.state.total_exposure,
                    realized_pnl=self.state.realized_pnl,
                    unrealized_pnl=self.state.unrealized_pnl,
                )

                # Sync positions: delete closed ones, upsert active ones
                db_positions = await pos_repo.get_all(self.portfolio_id)
                db_symbols = {p.symbol for p in db_positions}
                active_symbols = {
                    sym
                    for sym, pos in self.state.positions.items()
                    if not pos.is_empty()
                }

                for sym in db_symbols - active_symbols:
                    await pos_repo.delete(self.portfolio_id, sym)

                for sym, pos in self.state.positions.items():
                    if not pos.is_empty():
                        cur_p = self._last_prices.get(
                            sym, pos.avg_entry_price
                        )
                        upl = (
                            (cur_p - pos.avg_entry_price) * pos.quantity
                            if pos.quantity > 0
                            else (pos.avg_entry_price - cur_p) * abs(pos.quantity)
                        )
                        await pos_repo.upsert(
                            portfolio_id=self.portfolio_id,
                            symbol=sym,
                            quantity=pos.quantity,
                            avg_entry_price=pos.avg_entry_price,
                            unrealized_pnl=upl,
                            realized_pnl=self.state.realized_pnl,
                        )
                await session.commit()
        except Exception as e:
            logger.error("Failed to persist portfolio state: %s", e)

    # ── Public Handlers & PortfolioManager API ───────────────────

    def update_position(self, fill: FillEvent) -> None:
        """Synchronously update positions and cash based on an execution fill."""
        self._update_cash(fill)
        self._update_position(fill)
        self._recalculate_valuation_sync()

    async def handle_fill(self, event: FillEvent) -> None:
        """Handle incoming FillEvent with atomic state update & event publication."""
        async with self._lock:
            self._update_cash(event)
            self._update_position(event)
            await self._recalculate_valuation()
            await self._persist_state()
            await self._publish_update()

    async def update_mark_price(self, symbol: str, price: float) -> None:
        """Update mark price for a symbol and publish updated valuation."""
        if price <= 0:
            return
        async with self._lock:
            self._last_prices[symbol] = price
            await self._recalculate_valuation()
            await self._persist_state()
            await self._publish_update()

    def get_positions(self) -> dict[str, float]:
        """Return net quantities for all active positions."""
        return {
            sym: pos.quantity
            for sym, pos in self.state.positions.items()
            if not pos.is_empty()
        }

    def get_position(self, symbol: str) -> PositionState | None:
        """Return PositionState for a symbol or None if flat."""
        pos = self.state.positions.get(symbol)
        return pos if pos and not pos.is_empty() else None

    def get_state(self) -> PortfolioState:
        """Return current PortfolioState snapshot."""
        return self.state

    def get_cash(self) -> float:
        """Return current cash balance."""
        return self.state.cash

    def get_total_equity(self) -> float:
        """Return current mark-to-market total equity."""
        return self.state.total_equity

    def get_realized_pnl(self) -> float:
        """Return cumulative realized PnL."""
        return self.state.realized_pnl

    def get_unrealized_pnl(self) -> float:
        """Return current mark-to-market unrealized PnL."""
        return self.state.unrealized_pnl

    def get_total_exposure(self) -> float:
        """Return gross portfolio exposure."""
        return self.state.total_exposure

"""Risk Engine and modular pre-trade RiskChecks for QuantFlow."""

from __future__ import annotations

import asyncio
import inspect
import zoneinfo
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from datetime import time as dt_time
from typing import Any

from quantflow.common.events import (
    ApprovedSignalEvent,
    FillEvent,
    OrderEvent,
    PortfolioUpdateEvent,
    RejectedSignalEvent,
    SignalEvent,
)
from quantflow.config.manager import ConfigManager
from quantflow.core.clock import Clock, SystemClock
from quantflow.core.interfaces import EventBus, RiskManager
from quantflow.core.logging import get_logger

logger = get_logger("risk_engine")

# ── Reason Codes ──────────────────────────────────────────────────

REASON_EMERGENCY_STOP = "EMERGENCY_STOP"
REASON_MARKET_CLOSED = "MARKET_CLOSED"
REASON_GLOBAL_HALT = "GLOBAL_HALT"
REASON_MAX_EXPOSURE = "EXCEEDS_MAX_EXPOSURE"
REASON_MAX_POSITION_SIZE = "EXCEEDS_MAX_POSITION_SIZE"
REASON_DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
REASON_CIRCUIT_BREAKER = "CIRCUIT_BREAKER"
REASON_SYMBOL_NOT_ALLOWED = "SYMBOL_NOT_ALLOWED"


# ── Risk Check Interface & Context ───────────────────────────────


class RiskContext(ABC):
    """Context provided to RiskChecks containing market, portfolio, and config state."""

    config: ConfigManager
    clock: Clock
    positions: dict[str, float]
    daily_realized_pnl: float
    current_day: str
    trade_pnl_history: deque[float]

    @abstractmethod
    def is_emergency_stop_active(self) -> bool:
        """Return True if emergency stop is engaged."""

    @abstractmethod
    def is_circuit_breaker_tripped(self) -> bool:
        """Return True if the circuit breaker is currently tripped."""

    @abstractmethod
    def trip_circuit_breaker(self) -> None:
        """Mark circuit breaker as tripped."""

    @abstractmethod
    async def set_emergency_stop(self, enabled: bool, trigger: str = "manual") -> None:
        """Engage or disengage emergency stop."""

    @abstractmethod
    async def get_market_price(self, symbol: str) -> float | None:
        """Retrieve latest market price for symbol."""


class RiskCheck(ABC):
    """Abstract base class for modular, independently testable pre-trade risk checks."""

    @abstractmethod
    async def validate(
        self, signal: SignalEvent, context: RiskContext
    ) -> tuple[bool, str | None]:
        """Validate signal against this rule.

        Returns:
            (True, None) if approved.
            (False, reason_code) if rejected.
        """


# ── Individual Risk Checks ────────────────────────────────────────


class EmergencyStopCheck(RiskCheck):
    """Rejects all signals immediately if emergency stop is active."""

    async def validate(
        self, signal: SignalEvent, context: RiskContext
    ) -> tuple[bool, str | None]:
        if context.is_emergency_stop_active():
            return False, REASON_EMERGENCY_STOP
        return True, None


class AllowedSymbolsCheck(RiskCheck):
    """Validates that the signal symbol is in the allowed_symbols whitelist."""

    async def validate(
        self, signal: SignalEvent, context: RiskContext
    ) -> tuple[bool, str | None]:
        allowed = context.config.get("risk.allowed_symbols", [])
        if allowed and signal.symbol not in allowed:
            return False, REASON_SYMBOL_NOT_ALLOWED
        return True, None


class MarketHoursCheck(RiskCheck):
    """Validates that current time is within configured trading schedule."""

    def __init__(
        self,
        now_fn: Callable[[], datetime] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._now_fn = now_fn
        self._clock = clock

    async def validate(
        self, signal: SignalEvent, context: RiskContext
    ) -> tuple[bool, str | None]:
        schedule = context.config.get("risk.trading_schedule", {})
        if not schedule:
            return True, None

        tz_str = schedule.get("timezone", "UTC")
        try:
            tz = zoneinfo.ZoneInfo(tz_str)
        except Exception:
            tz = UTC

        start_str = schedule.get("start")
        end_str = schedule.get("end")
        if not start_str or not end_str:
            return True, None

        if self._now_fn:
            now_dt = self._now_fn()
        elif self._clock:
            now_dt = self._clock.now()
        elif hasattr(context, "clock") and context.clock is not None:
            now_dt = context.clock.now()
        else:
            now_dt = datetime.now(tz)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=tz)
        else:
            now_dt = now_dt.astimezone(tz)

        current_time = now_dt.time()
        start_time = dt_time.fromisoformat(start_str)
        end_time = dt_time.fromisoformat(end_str)

        if start_time <= end_time:
            in_hours = start_time <= current_time <= end_time
        else:
            # Overnight session (e.g. 22:00 to 06:00)
            in_hours = current_time >= start_time or current_time <= end_time

        if not in_hours:
            return False, REASON_MARKET_CLOSED
        return True, None


class GlobalHaltCheck(RiskCheck):
    """Validates that trading is not globally halted."""

    async def validate(
        self, signal: SignalEvent, context: RiskContext
    ) -> tuple[bool, str | None]:
        if context.config.get("risk.global_halt", False):
            return False, REASON_GLOBAL_HALT
        return True, None


class PositionSizeLimitCheck(RiskCheck):
    """Enforces per-symbol max quantity and max notional limits."""

    async def validate(
        self, signal: SignalEvent, context: RiskContext
    ) -> tuple[bool, str | None]:
        max_qty = float(context.config.get("risk.max_position_qty", float("inf")))
        max_notional = float(
            context.config.get("risk.max_position_notional", float("inf"))
        )

        if max_qty == float("inf") and max_notional == float("inf"):
            return True, None

        qty = signal.quantity if signal.quantity > 0 else float(
            context.config.get(f"risk.position_size_base_{signal.symbol}", 0.01)
        )
        side = signal.side.upper()
        delta = qty if side == "BUY" else (-qty if side == "SELL" else 0.0)

        current_qty = context.positions.get(signal.symbol, 0.0)
        new_qty = current_qty + delta

        if abs(new_qty) > max_qty:
            return False, REASON_MAX_POSITION_SIZE

        if max_notional < float("inf"):
            price = await context.get_market_price(signal.symbol)
            if price is None or price <= 0:
                price = signal.price
            if price is None or price <= 0:
                return False, REASON_MAX_POSITION_SIZE

            new_notional = abs(new_qty) * price
            if new_notional > max_notional:
                return False, REASON_MAX_POSITION_SIZE

        return True, None


class MaxExposureCheck(RiskCheck):
    """Enforces portfolio-wide gross exposure (sum of absolute notional values)."""

    async def validate(
        self, signal: SignalEvent, context: RiskContext
    ) -> tuple[bool, str | None]:
        max_exposure = float(
            context.config.get("risk.max_total_exposure", float("inf"))
        )
        if max_exposure == float("inf"):
            return True, None

        price = await context.get_market_price(signal.symbol)
        if price is None or price <= 0:
            price = signal.price
        if price is None or price <= 0:
            return False, REASON_MAX_EXPOSURE

        qty = signal.quantity if signal.quantity > 0 else float(
            context.config.get(f"risk.position_size_base_{signal.symbol}", 0.01)
        )
        side = signal.side.upper()
        delta = qty if side == "BUY" else (-qty if side == "SELL" else 0.0)
        new_symbol_qty = context.positions.get(signal.symbol, 0.0) + delta

        total_exposure = abs(new_symbol_qty) * price
        for sym, pos_qty in context.positions.items():
            if sym == signal.symbol:
                continue
            sym_price = await context.get_market_price(sym)
            if sym_price is None or sym_price <= 0:
                return False, REASON_MAX_EXPOSURE
            total_exposure += abs(pos_qty) * sym_price

        if total_exposure > max_exposure:
            return False, REASON_MAX_EXPOSURE
        return True, None


class DailyLossLimitCheck(RiskCheck):
    """Enforces cumulative realized loss limit for the current UTC day."""

    async def validate(
        self, signal: SignalEvent, context: RiskContext
    ) -> tuple[bool, str | None]:
        max_loss = float(context.config.get("risk.max_daily_loss", float("inf")))
        if max_loss == float("inf"):
            return True, None

        today = (
            context.clock.now().date().isoformat()
            if hasattr(context, "clock") and context.clock is not None
            else datetime.now(UTC).date().isoformat()
        )
        if today != context.current_day:
            context.daily_realized_pnl = 0.0
            context.current_day = today

        if context.daily_realized_pnl <= -max_loss:
            return False, REASON_DAILY_LOSS_LIMIT
        return True, None


class CircuitBreakerCheck(RiskCheck):
    """Trips when consecutive losses occur and blocks further signals."""

    async def validate(
        self, signal: SignalEvent, context: RiskContext
    ) -> tuple[bool, str | None]:
        if context.is_circuit_breaker_tripped():
            return False, REASON_CIRCUIT_BREAKER

        window = int(context.config.get("risk.circuit_breaker_loss_count", 5))
        if window <= 0:
            return True, None

        if len(context.trade_pnl_history) >= window:
            recent_losses = sum(context.trade_pnl_history)
            if recent_losses < 0:
                context.trip_circuit_breaker()
                severe = float(
                    context.config.get(
                        "risk.circuit_breaker_emergency_threshold", float("inf")
                    )
                )
                if severe < float("inf") and recent_losses < -severe:
                    await context.set_emergency_stop(True, trigger="circuit_breaker")
                return False, REASON_CIRCUIT_BREAKER

        return True, None


# ── Risk Engine ───────────────────────────────────────────────────


class RiskEngine(RiskManager, RiskContext):
    """Central risk management engine orchestrating composable RiskChecks."""

    def __init__(
        self,
        config: ConfigManager | None = None,
        event_bus: EventBus | None = None,
        exchange_adapter: Any | None = None,
        execution_handler: Any | None = None,
        clock_or_checks: Clock | list[RiskCheck] | None = None,
        checks: list[RiskCheck] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.config = config if config is not None else ConfigManager()
        self.event_bus = event_bus
        self.exchange = exchange_adapter
        self.execution = execution_handler

        # Disambiguate 5th positional arg
        if isinstance(clock_or_checks, Clock):
            clock = clock_or_checks
        elif isinstance(clock_or_checks, list):
            checks = clock_or_checks

        self.clock: Clock = clock or SystemClock()

        # State
        self.positions: dict[str, float] = {}
        self.portfolio_value: float = 0.0
        self.cash: float = 0.0
        self.market_prices: dict[str, float] = {}

        self.daily_realized_pnl: float = 0.0
        self.current_day: str = self.clock.now().date().isoformat()
        self.trade_pnl_history: deque[float] = deque(
            maxlen=int(self.config.get("risk.circuit_breaker_loss_count", 5))
        )

        self._emergency_stop = False
        self._circuit_breaker_tripped = False
        self._emergency_stop_lock = asyncio.Lock()
        self._running = False

        # Composable check pipeline
        self.checks: list[RiskCheck] = (
            checks
            if checks is not None
            else [
                EmergencyStopCheck(),
                AllowedSymbolsCheck(),
                MarketHoursCheck(),
                GlobalHaltCheck(),
                PositionSizeLimitCheck(),
                MaxExposureCheck(),
                DailyLossLimitCheck(),
                CircuitBreakerCheck(),
            ]
        )

    # ── RiskContext Protocol Implementation ──────────────────────

    def is_emergency_stop_active(self) -> bool:
        return self._emergency_stop

    def is_circuit_breaker_tripped(self) -> bool:
        return self._circuit_breaker_tripped

    def trip_circuit_breaker(self) -> None:
        self._circuit_breaker_tripped = True
        logger.warning("Circuit breaker tripped!")

    def reset_circuit_breaker(self) -> None:
        """Reset the circuit breaker and clear recent trade history."""
        self._circuit_breaker_tripped = False
        self.trade_pnl_history.clear()
        logger.info("Circuit breaker reset")

    async def get_market_price(self, symbol: str) -> float | None:
        if symbol in self.market_prices:
            return self.market_prices[symbol]
        if self.exchange and hasattr(self.exchange, "fetch_ticker"):
            try:
                res = self.exchange.fetch_ticker(symbol)
                if inspect.isawaitable(res):
                    ticker = await res
                else:
                    ticker = res
                p = ticker.get("last") or (
                    (ticker.get("bid", 0) + ticker.get("ask", 0)) / 2
                )
                if p and p > 0:
                    return float(p)
            except Exception as e:
                logger.debug("Failed to fetch ticker for %s: %s", symbol, e)
        return None

    # ── Emergency Stop Management ────────────────────────────────

    async def set_emergency_stop(self, enabled: bool, trigger: str = "manual") -> None:
        async with self._emergency_stop_lock:
            if enabled == self._emergency_stop:
                return

            self._emergency_stop = enabled
            logger.warning(
                "Emergency stop %s via %s",
                "activated" if enabled else "deactivated",
                trigger,
            )

            if enabled:
                # 1. Cancel open orders
                if self.exchange and hasattr(self.exchange, "get_open_orders"):
                    try:
                        res = self.exchange.get_open_orders()
                        open_orders = await res if inspect.isawaitable(res) else res
                        for order in open_orders:
                            if self.execution and hasattr(
                                self.execution, "cancel_order"
                            ):
                                cancel_res = self.execution.cancel_order(order["id"])
                                if inspect.isawaitable(cancel_res):
                                    await cancel_res
                    except Exception as e:
                        logger.error("Failed to cancel open orders: %s", e)

                # 2. Flatten positions
                if self.execution and hasattr(self.execution, "submit_order"):
                    for symbol, qty in list(self.positions.items()):
                        if abs(qty) < 1e-8:
                            continue
                        side = "SELL" if qty > 0 else "BUY"
                        order = OrderEvent(
                            strategy_id="risk_engine_emergency",
                            symbol=symbol,
                            side=side,
                            order_type="MARKET",
                            quantity=abs(qty),
                        )
                        try:
                            submit_res = self.execution.submit_order(order)
                            if inspect.isawaitable(submit_res):
                                await submit_res
                        except Exception as e:
                            logger.error(
                                "Failed to flatten position for %s: %s", symbol, e
                            )

    # ── Signal & Order Validation ────────────────────────────────

    async def validate_signal(
        self, signal: SignalEvent
    ) -> tuple[bool, str | None]:
        """Run all configured checks in sequence."""
        for check in self.checks:
            try:
                passed, reason = await check.validate(signal, self)
                if not passed:
                    return False, reason
            except Exception as e:
                logger.error(
                    "Error executing risk check %s: %s",
                    check.__class__.__name__,
                    e,
                    exc_info=True,
                )
                return False, "INTERNAL_ERROR"
        return True, None

    def validate_order(self, order: OrderEvent) -> bool:
        """Synchronous risk manager interface for orders."""
        if self._emergency_stop:
            return False
        if self.config.get("risk.global_halt", False):
            return False
        max_qty = float(self.config.get("risk.max_position_qty", float("inf")))
        if max_qty < float("inf"):
            curr = self.positions.get(order.symbol, 0.0)
            delta = order.quantity if order.side.upper() == "BUY" else -order.quantity
            if abs(curr + delta) > max_qty:
                return False
        return True

    # ── EventBus Lifecycle & Event Handlers ──────────────────────

    async def start(self) -> None:
        if self._running or self.event_bus is None:
            return
        self._running = True
        await self.event_bus.subscribe(SignalEvent, self._handle_signal)
        await self.event_bus.subscribe(FillEvent, self._handle_fill)
        await self.event_bus.subscribe(PortfolioUpdateEvent, self._handle_portfolio)
        logger.info("Risk Engine started")

    async def stop(self) -> None:
        if not self._running or self.event_bus is None:
            return
        self._running = False
        await self.event_bus.unsubscribe(SignalEvent, self._handle_signal)
        await self.event_bus.unsubscribe(FillEvent, self._handle_fill)
        await self.event_bus.unsubscribe(PortfolioUpdateEvent, self._handle_portfolio)
        logger.info("Risk Engine stopped")

    async def _handle_signal(self, event: SignalEvent) -> None:
        if not self._running:
            return

        approved, reason = await self.validate_signal(event)
        if approved:
            app_event = ApprovedSignalEvent(
                signal_id=event.event_id,
                strategy_id=event.strategy_id,
                symbol=event.symbol,
                side=event.side,
                quantity=event.quantity,
                signal_strength=event.signal_strength,
                price=event.price,
            )
            if self.event_bus:
                await self.event_bus.publish(app_event)
            logger.info("Approved signal %s for %s", event.event_id, event.symbol)
        else:
            rej_event = RejectedSignalEvent(
                signal_id=event.event_id,
                strategy_id=event.strategy_id,
                symbol=event.symbol,
                reason=reason or "RISK_CHECK_FAILED",
            )
            if self.event_bus:
                await self.event_bus.publish(rej_event)
            logger.warning(
                "Rejected signal %s for %s: %s",
                event.event_id,
                event.symbol,
                reason,
            )

    async def _handle_fill(self, event: FillEvent) -> None:
        side = event.side.upper()
        delta = event.quantity if side == "BUY" else -event.quantity
        self.positions[event.symbol] = self.positions.get(event.symbol, 0.0) + delta
        if abs(self.positions[event.symbol]) < 1e-10:
            self.positions.pop(event.symbol, None)

        if event.realized_pnl != 0.0:
            today = self.clock.now().date().isoformat()
            if today != self.current_day:
                self.daily_realized_pnl = 0.0
                self.current_day = today
            self.daily_realized_pnl += event.realized_pnl
            self.trade_pnl_history.append(event.realized_pnl)

    async def _handle_portfolio(self, event: PortfolioUpdateEvent) -> None:
        self.cash = event.cash
        self.portfolio_value = event.total_value
        self.positions.clear()
        for sym, qty in event.positions.items():
            if abs(qty) >= 1e-10:
                self.positions[sym] = qty

"""Core Abstract Base Classes and Protocols for QuantFlow."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from quantflow.common.events import Event, FillEvent, OrderEvent

T = TypeVar("T", bound=Event)
EventHandler = Callable[[T], Awaitable[None]]


class EventBus(ABC):
    """Abstract EventBus interface for event publication and subscription."""

    @abstractmethod
    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribed listeners."""

    @abstractmethod
    async def subscribe(
        self,
        event_type: type[T],
        handler: EventHandler[T],
    ) -> None:
        """Subscribe a callback handler to events of a specific type."""

    @abstractmethod
    async def unsubscribe(
        self,
        event_type: type[T],
        handler: EventHandler[T],
    ) -> None:
        """Unsubscribe a callback handler from events of a specific type."""


class MarketDataProvider(ABC):
    """Abstract interface for market data ingestion components."""

    @abstractmethod
    async def start(self) -> None:
        """Start the market data provider service."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the market data provider service."""

    @abstractmethod
    async def subscribe_symbols(self, symbols: list[str]) -> None:
        """Subscribe to streaming market data for the given symbols."""


class Strategy(ABC):
    """Abstract interface for trading strategies."""

    @abstractmethod
    def get_name(self) -> str:
        """Return the unique name/identifier of the strategy."""

    @abstractmethod
    async def on_event(self, event: Event) -> None:
        """Handle incoming events dispatched to the strategy."""

    async def initialize(
        self,
        config: dict[str, Any] | None = None,
        clock: Any | None = None,
    ) -> None:
        """Initialize the strategy with optional configuration and injected Clock."""
        pass


class ExecutionEngine(ABC):
    """Abstract interface for order execution engines."""

    @abstractmethod
    async def submit_order(self, order: OrderEvent) -> None:
        """Submit an order for execution."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> None:
        """Cancel an existing open order by ID."""


class PortfolioManager(ABC):
    """Abstract interface for portfolio tracking and management."""

    @abstractmethod
    def update_position(self, fill: FillEvent) -> None:
        """Update portfolio positions based on an execution fill."""

    @abstractmethod
    def get_positions(self) -> dict[str, float]:
        """Get a copy of current asset quantities held in portfolio."""


class RiskManager(ABC):
    """Abstract interface for pre-trade risk management."""

    @abstractmethod
    def validate_order(self, order: OrderEvent) -> bool:
        """Validate whether an order satisfies active risk controls."""


class ExchangeAdapter(ABC):
    """Abstract interface for exchange connectivity and order management."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the exchange."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully disconnect from the exchange."""

    @abstractmethod
    async def subscribe_market_data(self, symbols: list[str]) -> None:
        """Subscribe to streaming market data for the given symbols."""

    @abstractmethod
    async def place_order(self, order: OrderEvent) -> str:
        """Place an order; returns exchange order ID."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by exchange ID; returns success."""

    @abstractmethod
    async def get_balances(self) -> dict[str, float]:
        """Return available balances keyed by asset."""

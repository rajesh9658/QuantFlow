"""Event data models for QuantFlow event-driven framework using Pydantic V2."""

from datetime import UTC, datetime
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, Field


def _default_uuid() -> str:
    return str(uuid4())


def _default_utc_now() -> datetime:
    return datetime.now(UTC)


class Event(BaseModel):
    """Base event model."""

    event_id: str = Field(default_factory=_default_uuid)
    timestamp: datetime = Field(default_factory=_default_utc_now)
    timestamp_received: datetime | None = None
    event_type: str = "EVENT"

    model_config = {"frozen": True}

    @property
    def payload(self) -> Self:
        """Convenience property for accessing event content directly or wrapped."""
        return self


class MarketDataEvent(Event):
    """Base market data event model."""

    symbol: str
    exchange: str = ""
    event_type: str = "MARKET_DATA"


class TickEvent(MarketDataEvent):
    """Tick-level market data event model."""

    bid_price: float
    ask_price: float
    bid_size: float
    ask_size: float
    last_price: float
    last_size: float
    event_type: str = "TICK"


class BarEvent(MarketDataEvent):
    """OHLCV Bar market data event model."""

    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    interval: str = "1m"
    event_type: str = "BAR"


class SignalEvent(Event):
    """Strategy signal event model."""

    strategy_id: str
    symbol: str
    side: str  # BUY or SELL
    quantity: float
    signal_strength: float = 1.0
    price: float | None = None
    event_type: str = "SIGNAL"


class OrderEvent(Event):
    """Order placement/submission event model."""

    order_id: str = Field(default_factory=_default_uuid)
    strategy_id: str
    symbol: str
    side: str  # BUY or SELL
    order_type: str  # MARKET or LIMIT
    quantity: float
    price: float | None = None
    time_in_force: str = "GTC"
    event_type: str = "ORDER"


class FillEvent(Event):
    """Order execution fill event model."""

    fill_id: str = Field(default_factory=_default_uuid)
    order_id: str
    symbol: str
    side: str
    quantity: float
    fill_price: float
    commission: float = 0.0
    exchange: str = ""
    realized_pnl: float = 0.0
    expected_price: float | None = None
    timestamp_exchange: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    event_type: str = "FILL"

    @property
    def price(self) -> float:
        """Alias for fill_price to support generic execution interfaces."""
        return self.fill_price


class RiskEvent(Event):
    """Risk check or violation event model."""

    level: str  # INFO, WARNING, CRITICAL
    rule_name: str
    message: str
    action: str = "LOG"
    event_type: str = "RISK"


class SystemEvent(Event):
    """System-level event for component state transitions."""

    source: str  # e.g. "binance"
    component: str  # e.g. "exchange_adapter"
    state: str  # CONNECTED, RECONNECTING, DISCONNECTED
    reason: str = ""
    event_type: str = "SYSTEM"


class OrderBookEvent(MarketDataEvent):
    """Order book snapshot/update event."""

    bids: list[list[float]]  # [[price, size], ...]
    asks: list[list[float]]
    event_type: str = "ORDER_BOOK"


class TradeEvent(MarketDataEvent):
    """Individual trade event."""

    price: float
    size: float
    trade_id: str = ""
    event_type: str = "TRADE"


class ApprovedSignalEvent(Event):
    """Approved strategy signal event model."""

    signal_id: str
    strategy_id: str
    symbol: str
    side: str  # BUY or SELL
    quantity: float
    signal_strength: float = 1.0
    price: float | None = None
    event_type: str = "APPROVED_SIGNAL"


class RejectedSignalEvent(Event):
    """Rejected strategy signal event model."""

    signal_id: str
    strategy_id: str
    symbol: str
    reason: str
    event_type: str = "REJECTED_SIGNAL"


class PortfolioUpdateEvent(Event):
    """Portfolio state update event model."""

    cash: float = 0.0
    total_value: float = 0.0
    positions: dict[str, float] = Field(default_factory=dict)
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_exposure: float = 0.0
    positions_detail: dict[str, Any] = Field(default_factory=dict)
    event_type: str = "PORTFOLIO_UPDATE"

    @property
    def total_equity(self) -> float:
        """Alias for total_value."""
        return self.total_value


class EventType:
    """Type constants mapping to event classes for subscription."""

    EVENT = Event
    MARKET_DATA = MarketDataEvent
    TICK = TickEvent
    BAR = BarEvent
    SIGNAL = SignalEvent
    ORDER = OrderEvent
    FILL = FillEvent
    RISK = RiskEvent
    SYSTEM = SystemEvent
    ORDER_BOOK = OrderBookEvent
    TRADE = TradeEvent
    APPROVED_SIGNAL = ApprovedSignalEvent
    REJECTED_SIGNAL = RejectedSignalEvent
    PORTFOLIO_UPDATE = PortfolioUpdateEvent



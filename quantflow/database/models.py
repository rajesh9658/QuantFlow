"""SQLAlchemy 2.0 async database models for QuantFlow."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    DECIMAL,
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Dialect-agnostic autoincrementing integer primary key
BigIntId = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    """Base declarative class for all QuantFlow database models."""


# ── Python Enums matching Postgres Schema ────────────────────────


class OrderSide(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(enum.StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"


class OrderStatus(enum.StrEnum):
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class SignalDirection(enum.StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class LogLevel(enum.StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# ── Partitioned Tables (Tickers, Orderbooks, Logs, Errors) ───────


class Ticker(Base):
    """Tick-level market data model."""

    __tablename__ = "tickers"

    id: Mapped[int] = mapped_column(
        BigIntId, primary_key=True, autoincrement=True
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    bid: Mapped[float] = mapped_column(DECIMAL(20, 10), nullable=False)
    ask: Mapped[float] = mapped_column(DECIMAL(20, 10), nullable=False)
    last: Mapped[float] = mapped_column(DECIMAL(20, 10), nullable=False)
    volume: Mapped[float] = mapped_column(DECIMAL(20, 10), nullable=False)
    timestamp_exchange: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )

    __table_args__ = (
        Index(
            "idx_tickers_symbol_timestamp",
            "symbol",
            "timestamp_exchange",
            postgresql_ops={"timestamp_exchange": "DESC"},
        ),
    )


class OrderBook(Base):
    """Orderbook snapshot data model."""

    __tablename__ = "orderbooks"

    id: Mapped[int] = mapped_column(
        BigIntId, primary_key=True, autoincrement=True
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False, index=True)
    bids: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    asks: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    last_update_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    timestamp_exchange: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    source: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )

    __table_args__ = (
        Index(
            "idx_orderbooks_symbol_timestamp",
            "symbol",
            "timestamp_exchange",
            postgresql_ops={"timestamp_exchange": "DESC"},
        ),
    )


class Log(Base):
    """System and operational log entry model."""

    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(
        BigIntId, primary_key=True, autoincrement=True
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, index=True, nullable=True
    )
    level: Mapped[LogLevel] = mapped_column(
        Enum(LogLevel, name="log_level", native_enum=False), nullable=False
    )
    logger_name: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("idx_logs_correlation_id", "correlation_id"),
        Index("idx_logs_level", "level"),
    )


class ErrorLog(Base):
    """System error and exception log model."""

    __tablename__ = "errors"

    id: Mapped[int] = mapped_column(
        BigIntId, primary_key=True, autoincrement=True
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=False)
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    component: Mapped[str] = mapped_column(String, nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (Index("idx_errors_component", "component"),)


# ── Regular Tables ───────────────────────────────────────────────


class Strategy(Base):
    """Trading strategy definition and metadata model."""

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(
        BigIntId, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    signals: Mapped[list[Signal]] = relationship(back_populates="strategy")
    orders: Mapped[list[Order]] = relationship(back_populates="strategy")


class Signal(Base):
    """Trading strategy signal model."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(
        BigIntId, primary_key=True, autoincrement=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, unique=True, nullable=False
    )
    strategy_name: Mapped[str] = mapped_column(
        String, ForeignKey("strategies.name"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[SignalDirection] = mapped_column(
        Enum(SignalDirection, name="signal_direction", native_enum=False),
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(DECIMAL(5, 4), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )
    timestamp_exchange: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    strategy: Mapped[Strategy] = relationship(back_populates="signals")

    __table_args__ = (
        Index(
            "idx_signals_symbol_timestamp",
            "symbol",
            "timestamp_exchange",
            postgresql_ops={"timestamp_exchange": "DESC"},
        ),
        Index("idx_signals_strategy", "strategy_name"),
    )


class Order(Base):
    """Internal and exchange order state model."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(
        BigIntId, primary_key=True, autoincrement=True
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, unique=True, nullable=False
    )
    exchange_order_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[OrderSide] = mapped_column(
        Enum(OrderSide, name="order_side", native_enum=False), nullable=False
    )
    order_type: Mapped[OrderType] = mapped_column(
        Enum(OrderType, name="order_type", native_enum=False), nullable=False
    )
    quantity: Mapped[float] = mapped_column(DECIMAL(20, 10), nullable=False)
    filled_quantity: Mapped[float] = mapped_column(
        DECIMAL(20, 10), default=0.0
    )
    avg_price: Mapped[float | None] = mapped_column(
        DECIMAL(20, 10), nullable=True
    )
    limit_price: Mapped[float | None] = mapped_column(
        DECIMAL(20, 10), nullable=True
    )
    stop_price: Mapped[float | None] = mapped_column(
        DECIMAL(20, 10), nullable=True
    )
    time_in_force: Mapped[str] = mapped_column(String, default="GTC")
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status", native_enum=False),
        nullable=False,
    )
    strategy_name: Mapped[str] = mapped_column(
        String, ForeignKey("strategies.name"), nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    strategy: Mapped[Strategy] = relationship(back_populates="orders")
    executions: Mapped[list[Execution]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_orders_symbol", "symbol"),
        Index("idx_orders_status", "status"),
        Index("idx_orders_strategy", "strategy_name"),
    )


class Execution(Base):
    """Order fill execution model."""

    __tablename__ = "executions"

    id: Mapped[int] = mapped_column(
        BigIntId, primary_key=True, autoincrement=True
    )
    fill_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, unique=True, nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[OrderSide] = mapped_column(
        Enum(OrderSide, name="order_side", native_enum=False), nullable=False
    )
    price: Mapped[float] = mapped_column(DECIMAL(20, 10), nullable=False)
    quantity: Mapped[float] = mapped_column(DECIMAL(20, 10), nullable=False)
    commission: Mapped[float] = mapped_column(DECIMAL(20, 10), default=0.0)
    timestamp_exchange: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )

    order: Mapped[Order] = relationship(back_populates="executions")

    __table_args__ = (
        Index("idx_executions_order_id", "order_id"),
        Index(
            "idx_executions_symbol_timestamp",
            "symbol",
            "timestamp_exchange",
            postgresql_ops={"timestamp_exchange": "DESC"},
        ),
    )


class Position(Base):
    """Position persistent state model."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(
        BigIntId, primary_key=True, autoincrement=True
    )
    portfolio_id: Mapped[str] = mapped_column(
        String, default="quantflow_main"
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[float] = mapped_column(DECIMAL(20, 10), nullable=False)
    avg_entry_price: Mapped[float] = mapped_column(
        DECIMAL(20, 10), nullable=False
    )
    unrealized_pnl: Mapped[float | None] = mapped_column(
        DECIMAL(20, 10), nullable=True
    )
    realized_pnl: Mapped[float | None] = mapped_column(
        DECIMAL(20, 10), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint("portfolio_id", "symbol"),
        Index("idx_positions_portfolio", "portfolio_id"),
    )


class Portfolio(Base):
    """Portfolio financial state model."""

    __tablename__ = "portfolio"

    id: Mapped[int] = mapped_column(
        BigIntId, primary_key=True, autoincrement=True
    )
    portfolio_id: Mapped[str] = mapped_column(
        String, unique=True, default="quantflow_main"
    )
    cash: Mapped[float] = mapped_column(DECIMAL(20, 10), nullable=False)
    total_equity: Mapped[float] = mapped_column(
        DECIMAL(20, 10), nullable=False
    )
    total_exposure: Mapped[float] = mapped_column(
        DECIMAL(20, 10), nullable=False
    )
    realized_pnl: Mapped[float] = mapped_column(DECIMAL(20, 10), default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(DECIMAL(20, 10), default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (Index("idx_portfolio_id", "portfolio_id"),)


class Metric(Base):
    """Time-series metric analytical record model."""

    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(
        BigIntId, primary_key=True, autoincrement=True
    )
    portfolio_id: Mapped[str] = mapped_column(
        String, default="quantflow_main"
    )
    metric_name: Mapped[str] = mapped_column(String, nullable=False)
    metric_value: Mapped[float] = mapped_column(
        DECIMAL(20, 6), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )

    __table_args__ = (
        Index(
            "idx_metrics_name_timestamp",
            "metric_name",
            "timestamp",
            postgresql_ops={"timestamp": "DESC"},
        ),
    )


class PartitionMetadata(Base):
    """Metadata tracking table for partition creation and rotation."""

    __tablename__ = "partition_metadata"

    id: Mapped[int] = mapped_column(
        BigIntId, primary_key=True, autoincrement=True
    )
    table_name: Mapped[str] = mapped_column(String, nullable=False)
    partition_name: Mapped[str] = mapped_column(String, nullable=False)
    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    end_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint("table_name", "partition_name"),
    )

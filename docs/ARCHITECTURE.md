# QuantFlow Architecture Specification

## Overview

QuantFlow is an event-driven quantitative trading, backtesting, and live execution framework built on Python 3.12. It decouples market data ingestion, strategy signal generation, risk management, order execution, and portfolio tracking using an asynchronous publish-subscribe EventBus architecture.

---

## 1. Event Models (`quantflow.common.events`)

All events inherit from the base `Event` class and are serialized/validated using Pydantic V2.

### `Event` (Base Class)
- `event_id: str`: Unique identifier (UUIDv4 by default).
- `timestamp: datetime`: Time when event was created (UTC timezone aware).
- `event_type: str`: String discriminator representing event classification.

### `MarketDataEvent` (Inherits from `Event`)
- `symbol: str`: Asset ticker symbol (e.g. `BTC-USD`, `AAPL`).
- `exchange: str`: Exchange identifier (e.g. `BINANCE`, `NASDAQ`).

### `TickEvent` (Inherits from `MarketDataEvent`)
- `bid_price: float`
- `ask_price: float`
- `bid_size: float`
- `ask_size: float`
- `last_price: float`
- `last_size: float`

### `BarEvent` (Inherits from `MarketDataEvent`)
- `open_price: float`
- `high_price: float`
- `low_price: float`
- `close_price: float`
- `volume: float`
- `interval: str`: Timeframe string (e.g. `1m`, `5m`, `1h`, `1d`).

### `SignalEvent` (Inherits from `Event`)
- `strategy_id: str`: Identifier of the strategy generating the signal.
- `symbol: str`: Target symbol.
- `side: str`: Trade direction (`BUY` or `SELL`).
- `quantity: float`: Proposed order size.
- `signal_strength: float`: Confidence weight (default `1.0`).
- `price: float | None`: Target entry price if limit order signal.

### `OrderEvent` (Inherits from `Event`)
- `order_id: str`: Unique order identifier.
- `strategy_id: str`: Associated strategy identifier.
- `symbol: str`: Asset symbol.
- `side: str`: `BUY` or `SELL`.
- `order_type: str`: `MARKET` or `LIMIT`.
- `quantity: float`: Target order quantity.
- `price: float | None`: Limit price (required for `LIMIT` orders).
- `time_in_force: str`: `GTC`, `IOC`, or `FOK` (default `GTC`).

### `FillEvent` (Inherits from `Event`)
- `fill_id: str`: Execution fill identifier.
- `order_id: str`: Identifier of executed order.
- `symbol: str`: Traded asset symbol.
- `side: str`: Executed trade side (`BUY` or `SELL`).
- `quantity: float`: Filled quantity.
- `fill_price: float`: Realized execution price.
- `commission: float`: Transaction fees incurred (default `0.0`).
- `exchange: str`: Executing exchange venue.

### `RiskEvent` (Inherits from `Event`)
- `level: str`: Severity level (`INFO`, `WARNING`, `CRITICAL`).
- `rule_name: str`: Risk rule triggered (e.g. `MaxDrawdownLimit`).
- `message: str`: Explanatory message.
- `action: str`: Mitigation action (e.g. `LOG`, `CANCEL_ORDERS`, `FLATTEN_POSITIONS`).

---

## 2. Core Interfaces (`quantflow.core.interfaces`)

Defined using Python Abstract Base Classes (`abc.ABC`) and Abstract Methods (`@abstractmethod`):

- `EventBus`: Abstract EventBus interface specifying `publish`, `subscribe`, and `unsubscribe`.
- `MarketDataProvider`: Abstract interface for streaming live or historical tick/bar market data.
- `Strategy`: Abstract interface for trading strategy logic triggered by events.
- `ExecutionEngine`: Abstract interface for order placement, cancellation, and exchange interaction.
- `PortfolioManager`: Abstract interface for position tracking, equity, and PnL management.
- `RiskManager`: Abstract interface for order validation and risk parameter enforcement.

---

## 3. In-Process Asyncio EventBus (`quantflow.core.event_bus`)

The `AsyncEventBus` delivers typed asynchronous event routing:
- **Pub/Sub model**: Subscribers register interest in specific event types (or base `Event`).
- **Backpressure Safety**: Each subscriber receives events via a dedicated `asyncio.Queue(maxsize=...)`.
- **Concurrent Dispatch**: `publish()` puts events onto all subscribed queues without blocking publishers.

---

## 4. Plugin Architecture (`quantflow.plugins.manifest`)

Strategies are declared as plugins via a `strategy.yaml` manifest containing:
- `name: str`: Unique strategy name.
- `version: str`: Semantic version string.
- `min_framework_version: str`: Minimum required framework version.
- `entry_point: str`: Python import path to the strategy class.
- `description: str`: Strategy description (optional).
- `author: str`: Strategy author (optional).

The loader validates `min_framework_version` against the system constant `FRAMEWORK_VERSION = "0.1.0"`.

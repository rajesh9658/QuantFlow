"""Repository layer implementing repository-per-aggregate pattern for QuantFlow."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from quantflow.database.models import (
    ErrorLog,
    Execution,
    Log,
    LogLevel,
    Metric,
    Order,
    OrderBook,
    OrderSide,
    OrderStatus,
    OrderType,
    PartitionMetadata,
    Portfolio,
    Position,
    Signal,
    SignalDirection,
    Strategy,
    Ticker,
)


def _to_uuid(val: uuid.UUID | str) -> uuid.UUID:
    """Coerce string or UUID to uuid.UUID, falling back to deterministic UUID5."""
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, AttributeError):
        return uuid.uuid5(uuid.NAMESPACE_DNS, str(val))


# ── 1. Strategy Repository ───────────────────────────────────────


class StrategyRepository:
    """Repository for Strategy aggregate."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_name(self, name: str) -> Strategy | None:
        """Fetch a strategy definition by its unique name."""
        stmt = select(Strategy).where(Strategy.name == name)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def create_or_update(
        self,
        name: str,
        version: str,
        config: dict[str, Any] | None = None,
        active: bool = True,
    ) -> Strategy:
        """Create or update a strategy record."""
        strat = await self.get_by_name(name)
        if strat is None:
            strat = Strategy(
                name=name,
                version=version,
                config=config if config is not None else {},
                active=active,
            )
            self.session.add(strat)
        else:
            strat.version = version
            if config is not None:
                strat.config = config
            strat.active = active
            strat.updated_at = datetime.now(UTC)
        await self.session.flush()
        return strat

    async def list_active(self) -> list[Strategy]:
        """List all active strategies."""
        stmt = select(Strategy).where(Strategy.active.is_(True))
        res = await self.session.execute(stmt)
        return list(res.scalars().all())


# ── 2. Order Repository ──────────────────────────────────────────


class OrderRepository:
    """Repository for Order aggregate."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        order_id: uuid.UUID | str,
        symbol: str,
        side: OrderSide | str,
        order_type: OrderType | str,
        quantity: float,
        strategy_name: str,
        exchange_order_id: str | None = None,
        filled_quantity: float = 0.0,
        avg_price: float | None = None,
        limit_price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str = "GTC",
        status: OrderStatus | str = OrderStatus.PENDING,
        metadata: dict[str, Any] | None = None,
    ) -> Order:
        """Persist a new order."""
        uid = _to_uuid(order_id)
        order = Order(
            order_id=uid,
            exchange_order_id=exchange_order_id,
            symbol=symbol,
            side=OrderSide(str(side).lower()),
            order_type=OrderType(str(order_type).lower()),
            quantity=quantity,
            filled_quantity=filled_quantity,
            avg_price=avg_price,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            status=OrderStatus(str(status).lower()),
            strategy_name=strategy_name,
            metadata_json=metadata if metadata is not None else {},
        )
        self.session.add(order)
        await self.session.flush()
        return order

    async def get_by_order_id(self, order_id: uuid.UUID | str) -> Order | None:
        """Fetch order by internal UUID."""
        uid = _to_uuid(order_id)
        stmt = select(Order).where(Order.order_id == uid)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def update_status(
        self,
        order_id: uuid.UUID | str,
        status: OrderStatus | str,
        filled_quantity: float | None = None,
        avg_price: float | None = None,
    ) -> Order | None:
        """Update order execution status, filled quantity, and average price."""
        order = await self.get_by_order_id(order_id)
        if order is None:
            return None
        order.status = OrderStatus(str(status).lower())
        if filled_quantity is not None:
            order.filled_quantity = filled_quantity
        if avg_price is not None:
            order.avg_price = avg_price
        order.updated_at = datetime.now(UTC)
        await self.session.flush()
        return order

    async def get_open_orders(
        self,
        strategy_name: str | None = None,
        symbol: str | None = None,
    ) -> list[Order]:
        """Fetch all currently open/pending/partially-filled orders."""
        open_statuses = [
            OrderStatus.PENDING,
            OrderStatus.OPEN,
            OrderStatus.PARTIALLY_FILLED,
        ]
        stmt = select(Order).where(Order.status.in_(open_statuses))
        if strategy_name:
            stmt = stmt.where(Order.strategy_name == strategy_name)
        if symbol:
            stmt = stmt.where(Order.symbol == symbol)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())


# ── 3. Execution (Fill) Repository ───────────────────────────────


class ExecutionRepository:
    """Repository for Execution (Fill) records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        fill_id: uuid.UUID | str,
        order_id: uuid.UUID | str,
        symbol: str,
        side: OrderSide | str,
        price: float,
        quantity: float,
        commission: float = 0.0,
        timestamp_exchange: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        received_at: datetime | None = None,
    ) -> Execution:
        """Persist a fill execution."""
        f_uid = _to_uuid(fill_id)
        o_uid = _to_uuid(order_id)
        ts_ex = (
            timestamp_exchange
            if timestamp_exchange is not None
            else datetime.now(UTC)
        )
        rec_at = received_at if received_at is not None else datetime.now(UTC)

        execution = Execution(
            fill_id=f_uid,
            order_id=o_uid,
            symbol=symbol,
            side=OrderSide(str(side).lower()),
            price=price,
            quantity=quantity,
            commission=commission,
            timestamp_exchange=ts_ex,
            received_at=rec_at,
            metadata_json=metadata if metadata is not None else {},
        )
        self.session.add(execution)
        await self.session.flush()
        return execution

    async def get_by_fill_id(
        self, fill_id: uuid.UUID | str
    ) -> Execution | None:
        """Fetch execution by fill UUID."""
        uid = _to_uuid(fill_id)
        stmt = select(Execution).where(Execution.fill_id == uid)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_fills_for_order(
        self, order_id: uuid.UUID | str
    ) -> list[Execution]:
        """Fetch all fills associated with an order ID."""
        uid = _to_uuid(order_id)
        stmt = (
            select(Execution)
            .where(Execution.order_id == uid)
            .order_by(Execution.timestamp_exchange.asc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())


# ── 4. Position Repository ───────────────────────────────────────


class PositionRepository:
    """Repository for Position aggregate state."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, portfolio_id: str, symbol: str
    ) -> Position | None:
        """Fetch position by portfolio ID and symbol."""
        stmt = select(Position).where(
            Position.portfolio_id == portfolio_id, Position.symbol == symbol
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_all(
        self, portfolio_id: str = "quantflow_main"
    ) -> list[Position]:
        """Fetch all positions for a given portfolio ID."""
        stmt = select(Position).where(Position.portfolio_id == portfolio_id)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def upsert(
        self,
        portfolio_id: str,
        symbol: str,
        quantity: float,
        avg_entry_price: float,
        unrealized_pnl: float | None = None,
        realized_pnl: float | None = None,
    ) -> Position:
        """Insert or update a position snapshot."""
        pos = await self.get(portfolio_id, symbol)
        if pos is None:
            pos = Position(
                portfolio_id=portfolio_id,
                symbol=symbol,
                quantity=quantity,
                avg_entry_price=avg_entry_price,
                unrealized_pnl=unrealized_pnl,
                realized_pnl=realized_pnl,
            )
            self.session.add(pos)
        else:
            pos.quantity = quantity
            pos.avg_entry_price = avg_entry_price
            if unrealized_pnl is not None:
                pos.unrealized_pnl = unrealized_pnl
            if realized_pnl is not None:
                pos.realized_pnl = realized_pnl
            pos.updated_at = datetime.now(UTC)
        await self.session.flush()
        return pos

    async def delete(self, portfolio_id: str, symbol: str) -> bool:
        """Delete position record when position is fully flat."""
        stmt = delete(Position).where(
            Position.portfolio_id == portfolio_id, Position.symbol == symbol
        )
        res = await self.session.execute(stmt)
        await self.session.flush()
        count = int(getattr(res, "rowcount", 0) or 0)
        return count > 0


# ── 5. Portfolio Repository ──────────────────────────────────────


class PortfolioRepository:
    """Repository for Portfolio financial summary state."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, portfolio_id: str = "quantflow_main"
    ) -> Portfolio | None:
        """Fetch portfolio snapshot by portfolio ID."""
        stmt = select(Portfolio).where(
            Portfolio.portfolio_id == portfolio_id
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def upsert(
        self,
        portfolio_id: str,
        cash: float,
        total_equity: float,
        total_exposure: float,
        realized_pnl: float = 0.0,
        unrealized_pnl: float = 0.0,
    ) -> Portfolio:
        """Insert or update portfolio financial snapshot."""
        port = await self.get(portfolio_id)
        if port is None:
            port = Portfolio(
                portfolio_id=portfolio_id,
                cash=cash,
                total_equity=total_equity,
                total_exposure=total_exposure,
                realized_pnl=realized_pnl,
                unrealized_pnl=unrealized_pnl,
            )
            self.session.add(port)
        else:
            port.cash = cash
            port.total_equity = total_equity
            port.total_exposure = total_exposure
            port.realized_pnl = realized_pnl
            port.unrealized_pnl = unrealized_pnl
            port.updated_at = datetime.now(UTC)
        await self.session.flush()
        return port


# ── 6. Ticker Repository ─────────────────────────────────────────


class TickerRepository:
    """Repository for Ticker tick data."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        symbol: str,
        bid: float,
        ask: float,
        last: float,
        volume: float,
        timestamp_exchange: datetime,
        source: str,
        metadata: dict[str, Any] | None = None,
        received_at: datetime | None = None,
    ) -> Ticker:
        """Persist a single ticker price tick."""
        rec_at = received_at if received_at is not None else datetime.now(UTC)
        ticker = Ticker(
            symbol=symbol,
            bid=bid,
            ask=ask,
            last=last,
            volume=volume,
            timestamp_exchange=timestamp_exchange,
            received_at=rec_at,
            source=source,
            metadata_json=metadata if metadata is not None else {},
        )
        self.session.add(ticker)
        await self.session.flush()
        return ticker

    async def create_batch(
        self, tickers_data: list[dict[str, Any]]
    ) -> list[Ticker]:
        """Bulk insert ticker records."""
        instances: list[Ticker] = []
        for item in tickers_data:
            rec_at = item.get("received_at", datetime.now(UTC))
            t = Ticker(
                symbol=item["symbol"],
                bid=item["bid"],
                ask=item["ask"],
                last=item["last"],
                volume=item["volume"],
                timestamp_exchange=item["timestamp_exchange"],
                received_at=rec_at,
                source=item.get("source", "system"),
                metadata_json=item.get("metadata", {}),
            )
            instances.append(t)
            self.session.add(t)
        await self.session.flush()
        return instances

    async def get_latest(self, symbol: str) -> Ticker | None:
        """Fetch the most recent tick for a symbol."""
        stmt = (
            select(Ticker)
            .where(Ticker.symbol == symbol)
            .order_by(desc(Ticker.timestamp_exchange))
            .limit(1)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_range(
        self, symbol: str, start_time: datetime, end_time: datetime
    ) -> list[Ticker]:
        """Query tickers within a time range."""
        stmt = (
            select(Ticker)
            .where(
                Ticker.symbol == symbol,
                Ticker.timestamp_exchange >= start_time,
                Ticker.timestamp_exchange <= end_time,
            )
            .order_by(Ticker.timestamp_exchange.asc())
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())


# ── 7. OrderBook Repository ──────────────────────────────────────


class OrderBookRepository:
    """Repository for OrderBook snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        symbol: str,
        bids: list[Any],
        asks: list[Any],
        timestamp_exchange: datetime,
        source: str,
        last_update_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        received_at: datetime | None = None,
    ) -> OrderBook:
        """Persist an orderbook snapshot."""
        rec_at = received_at if received_at is not None else datetime.now(UTC)
        ob = OrderBook(
            symbol=symbol,
            bids=bids,
            asks=asks,
            last_update_id=last_update_id,
            timestamp_exchange=timestamp_exchange,
            received_at=rec_at,
            source=source,
            metadata_json=metadata if metadata is not None else {},
        )
        self.session.add(ob)
        await self.session.flush()
        return ob

    async def get_latest(self, symbol: str) -> OrderBook | None:
        """Fetch latest orderbook snapshot for a symbol."""
        stmt = (
            select(OrderBook)
            .where(OrderBook.symbol == symbol)
            .order_by(desc(OrderBook.timestamp_exchange))
            .limit(1)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()


# ── 8. Signal Repository ─────────────────────────────────────────


class SignalRepository:
    """Repository for Strategy Signal records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        event_id: uuid.UUID | str,
        strategy_name: str,
        symbol: str,
        direction: SignalDirection | str,
        confidence: float,
        timestamp_exchange: datetime,
        metadata: dict[str, Any] | None = None,
        received_at: datetime | None = None,
    ) -> Signal:
        """Persist a strategy generated signal."""
        uid = _to_uuid(event_id)
        rec_at = received_at if received_at is not None else datetime.now(UTC)
        sig = Signal(
            event_id=uid,
            strategy_name=strategy_name,
            symbol=symbol,
            direction=SignalDirection(str(direction).lower()),
            confidence=confidence,
            timestamp_exchange=timestamp_exchange,
            received_at=rec_at,
            metadata_json=metadata if metadata is not None else {},
        )
        self.session.add(sig)
        await self.session.flush()
        return sig

    async def get_by_event_id(
        self, event_id: uuid.UUID | str
    ) -> Signal | None:
        """Fetch signal by event UUID."""
        uid = _to_uuid(event_id)
        stmt = select(Signal).where(Signal.event_id == uid)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()


# ── 9. Metric Repository ─────────────────────────────────────────


class MetricRepository:
    """Repository for Metric time-series records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        metric_name: str,
        metric_value: float,
        portfolio_id: str = "quantflow_main",
        timestamp: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Metric:
        """Record an analytical metric measurement."""
        ts = timestamp if timestamp is not None else datetime.now(UTC)
        metric = Metric(
            portfolio_id=portfolio_id,
            metric_name=metric_name,
            metric_value=metric_value,
            timestamp=ts,
            metadata_json=metadata if metadata is not None else {},
        )
        self.session.add(metric)
        await self.session.flush()
        return metric

    async def get_series(
        self,
        metric_name: str,
        portfolio_id: str = "quantflow_main",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[Metric]:
        """Fetch metric time series within an optional range."""
        stmt = select(Metric).where(
            Metric.portfolio_id == portfolio_id,
            Metric.metric_name == metric_name,
        )
        if start_time:
            stmt = stmt.where(Metric.timestamp >= start_time)
        if end_time:
            stmt = stmt.where(Metric.timestamp <= end_time)
        stmt = stmt.order_by(Metric.timestamp.asc())
        res = await self.session.execute(stmt)
        return list(res.scalars().all())


# ── 10. Log & Error Repository ───────────────────────────────────


class LogRepository:
    """Repository for operational Logs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(
        self,
        level: LogLevel | str,
        logger_name: str,
        message: str,
        correlation_id: uuid.UUID | str | None = None,
        metadata: dict[str, Any] | None = None,
        received_at: datetime | None = None,
    ) -> Log:
        """Persist a log entry."""
        cid = _to_uuid(correlation_id) if correlation_id else None
        rec_at = received_at if received_at is not None else datetime.now(UTC)
        log_entry = Log(
            correlation_id=cid,
            level=LogLevel(str(level)),
            logger_name=logger_name,
            message=message,
            metadata_json=metadata if metadata is not None else {},
            received_at=rec_at,
        )
        self.session.add(log_entry)
        await self.session.flush()
        return log_entry


class ErrorLogRepository:
    """Repository for Error and Exception logs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_error(
        self,
        component: str,
        error_message: str,
        error_code: str | None = None,
        stack_trace: str | None = None,
        correlation_id: uuid.UUID | str | None = None,
        received_at: datetime | None = None,
    ) -> ErrorLog:
        """Persist an error log entry."""
        cid = _to_uuid(correlation_id) if correlation_id else None
        rec_at = received_at if received_at is not None else datetime.now(UTC)
        error = ErrorLog(
            correlation_id=cid,
            error_code=error_code,
            error_message=error_message,
            stack_trace=stack_trace,
            component=component,
            received_at=rec_at,
        )
        self.session.add(error)
        await self.session.flush()
        return error


# ── 11. Partition Repository ─────────────────────────────────────


class PartitionRepository:
    """Repository for partition metadata tracking."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_partition(
        self,
        table_name: str,
        partition_name: str,
        start_date: datetime,
        end_date: datetime,
    ) -> PartitionMetadata:
        """Record created partition in metadata table."""
        part = PartitionMetadata(
            table_name=table_name,
            partition_name=partition_name,
            start_date=start_date,
            end_date=end_date,
        )
        self.session.add(part)
        await self.session.flush()
        return part

    async def list_partitions(
        self, table_name: str | None = None
    ) -> list[PartitionMetadata]:
        """List tracked partitions."""
        stmt = select(PartitionMetadata)
        if table_name:
            stmt = stmt.where(PartitionMetadata.table_name == table_name)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

"""Event store reader abstraction and implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from quantflow.common.events import (
    Event,
    FillEvent,
    OrderBookEvent,
    SignalEvent,
    TickEvent,
)


class EventStoreReader(ABC):
    """Reads historical events from storage in chronological order.

    Events are ordered by virtual arrival time (timestamp_received then
    timestamp or insertion id).
    """

    @abstractmethod
    async def read_range(
        self,
        start: datetime,
        end: datetime,
        event_types: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> AsyncIterator[Event]:
        """Async-iterate over events in [start, end), ordered chronologically."""
        if False:
            yield ...

    @abstractmethod
    async def read_all(
        self,
        event_types: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> AsyncIterator[Event]:
        """Iterate over the entire store."""
        if False:
            yield ...


class InMemoryEventStoreReader(EventStoreReader):
    """In-memory event store reader for fixtures, unit tests, and replay."""

    def __init__(self, events: Sequence[Event] | None = None) -> None:
        self._events: list[Event] = list(events or [])

    def add_event(self, event: Event) -> None:
        """Add a single event to the in-memory store."""
        self._events.append(event)

    def add_events(self, events: Sequence[Event]) -> None:
        """Add multiple events to the in-memory store."""
        self._events.extend(events)

    @staticmethod
    def _event_timestamp(event: Event) -> datetime:
        ts = (
            getattr(event, "timestamp_received", None)
            or getattr(event, "timestamp_exchange", None)
            or getattr(event, "timestamp", None)
        )
        if isinstance(event, dict):
            ts = (
                event.get("timestamp_received")
                or event.get("timestamp_exchange")
                or event.get("timestamp")
                or event.get("received_at")
            )
        if isinstance(ts, datetime):
            pass
        elif isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts / 1000.0 if ts > 1e11 else ts, tz=UTC)
        else:
            return datetime.min.replace(tzinfo=UTC)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ts

    @staticmethod
    def _matches_filter(
        event: Event,
        event_types: list[str] | None,
        symbols: list[str] | None,
    ) -> bool:
        if event_types:
            ev_type = getattr(event, "event_type", "").upper()
            allowed = {t.upper() for t in event_types}
            # Allow matching e.g. "TICK", "ORDER_BOOK", "TICKER"
            type_variants = {ev_type}
            if ev_type == "TICK":
                type_variants.add("TICKER")
            elif ev_type == "TICKER":
                type_variants.add("TICK")
            elif ev_type == "ORDER_BOOK":
                type_variants.add("ORDERBOOK")
            if not type_variants.intersection(allowed):
                return False

        if symbols:
            ev_symbol = getattr(event, "symbol", None)
            if ev_symbol is not None and ev_symbol not in symbols:
                return False
        return True

    async def read_range(
        self,
        start: datetime,
        end: datetime,
        event_types: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> AsyncIterator[Event]:
        start_tz = start.replace(tzinfo=UTC) if start.tzinfo is None else start
        end_tz = end.replace(tzinfo=UTC) if end.tzinfo is None else end
        sorted_events = sorted(
            self._events,
            key=lambda e: (
                self._event_timestamp(e),
                str(getattr(e, "event_id", getattr(e, "id", ""))),
            ),
        )
        for event in sorted_events:
            ts = self._event_timestamp(event)
            if start_tz <= ts < end_tz and self._matches_filter(
                event, event_types, symbols
            ):
                yield event

    async def read_all(
        self,
        event_types: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> AsyncIterator[Event]:
        sorted_events = sorted(
            self._events,
            key=lambda e: (
                self._event_timestamp(e),
                str(getattr(e, "event_id", getattr(e, "id", ""))),
            ),
        )
        for event in sorted_events:
            if self._matches_filter(event, event_types, symbols):
                yield event


class PostgresEventStoreReader(EventStoreReader):
    """Reads historical events from the PostgreSQL database schema."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        batch_size: int = 1000,
    ) -> None:
        self._session_factory = session_factory
        self._batch_size = batch_size

    async def read_range(
        self,
        start: datetime,
        end: datetime,
        event_types: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> AsyncIterator[Event]:
        from quantflow.database.models import Execution, OrderBook, Signal, Ticker

        events: list[Event] = []
        async with self._session_factory() as session:
            # Query tickers
            query_tickers = not event_types or any(
                t.upper() in ("TICK", "TICKER") for t in event_types
            )
            if query_tickers:
                stmt_tickers = select(Ticker).where(
                    Ticker.received_at >= start, Ticker.received_at < end
                )
                if symbols:
                    stmt_tickers = stmt_tickers.where(Ticker.symbol.in_(symbols))
                res_tickers = await session.execute(stmt_tickers)
                for t in res_tickers.scalars():
                    events.append(
                        TickEvent(
                            event_id=str(t.id),
                            symbol=t.symbol,
                            exchange=t.source,
                            bid_price=float(t.bid or 0.0),
                            ask_price=float(t.ask or 0.0),
                            bid_size=float(t.volume or 0.0),
                            ask_size=float(t.volume or 0.0),
                            last_price=float(t.last or 0.0),
                            last_size=float(t.volume or 0.0),
                            timestamp=t.timestamp_exchange,
                            timestamp_received=t.received_at,
                        )
                    )

            # Query orderbooks
            query_obs = not event_types or any(
                t.upper() in ("ORDERBOOK", "ORDER_BOOK") for t in event_types
            )
            if query_obs:
                stmt_obs = select(OrderBook).where(
                    OrderBook.received_at >= start, OrderBook.received_at < end
                )
                if symbols:
                    stmt_obs = stmt_obs.where(OrderBook.symbol.in_(symbols))
                res_obs = await session.execute(stmt_obs)
                for ob in res_obs.scalars():
                    events.append(
                        OrderBookEvent(
                            event_id=str(ob.id),
                            symbol=ob.symbol,
                            exchange=ob.source,
                            bids=ob.bids or [],
                            asks=ob.asks or [],
                            timestamp=ob.timestamp_exchange,
                            timestamp_received=ob.received_at,
                        )
                    )

            # Query executions
            query_fills = not event_types or any(
                t.upper() in ("FILL", "EXECUTION") for t in event_types
            )
            if query_fills:
                stmt_execs = select(Execution).where(
                    Execution.received_at >= start, Execution.received_at < end
                )
                if symbols:
                    stmt_execs = stmt_execs.where(Execution.symbol.in_(symbols))
                res_execs = await session.execute(stmt_execs)
                for ex in res_execs.scalars():
                    side_str = (
                        ex.side.value if hasattr(ex.side, "value") else str(ex.side)
                    )
                    events.append(
                        FillEvent(
                            fill_id=str(ex.fill_id),
                            order_id=str(ex.order_id),
                            symbol=ex.symbol,
                            side=side_str.upper(),
                            quantity=float(ex.quantity),
                            fill_price=float(ex.price),
                            commission=float(ex.commission or 0.0),
                            timestamp=ex.timestamp_exchange,
                            timestamp_received=ex.received_at,
                            timestamp_exchange=ex.timestamp_exchange,
                        )
                    )

            # Query signals
            if not event_types or any(t.upper() == "SIGNAL" for t in event_types):
                stmt_sigs = select(Signal).where(
                    Signal.received_at >= start, Signal.received_at < end
                )
                if symbols:
                    stmt_sigs = stmt_sigs.where(Signal.symbol.in_(symbols))
                res_sigs = await session.execute(stmt_sigs)
                for sig in res_sigs.scalars():
                    dir_val = getattr(sig, "direction", "buy")
                    side_val = getattr(dir_val, "value", str(dir_val))
                    events.append(
                        SignalEvent(
                            event_id=str(sig.event_id),
                            strategy_id=sig.strategy_name,
                            symbol=sig.symbol,
                            exchange_id=getattr(sig, "exchange_id", getattr(sig, "exchange", "binance")),
                            side=side_val.upper(),
                            quantity=1.0,
                            price=None,
                            timestamp=sig.timestamp_exchange,
                            timestamp_received=sig.received_at,
                        )
                    )

        reader = InMemoryEventStoreReader(events)
        async for ev in reader.read_range(
            start, end, event_types=event_types, symbols=symbols
        ):
            yield ev

    async def read_all(
        self,
        event_types: list[str] | None = None,
        symbols: list[str] | None = None,
    ) -> AsyncIterator[Event]:
        # Cover wide range
        start = datetime(1970, 1, 1, tzinfo=UTC)
        end = datetime(2099, 1, 1, tzinfo=UTC)
        async for ev in self.read_range(
            start, end, event_types=event_types, symbols=symbols
        ):
            yield ev

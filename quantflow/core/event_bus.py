"""In-process asyncio implementation of EventBus."""

import asyncio
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from quantflow.common.events import Event
from quantflow.core.clock import Clock
from quantflow.core.interfaces import EventBus

T = TypeVar("T", bound=Event)
EventHandler = Callable[[T], Awaitable[None]]


class AsyncEventBus(EventBus):
    """In-process asyncio implementation of EventBus with backpressure safety."""

    def __init__(
        self,
        default_queue_maxsize: int = 1000,
        clock: Clock | None = None,
    ) -> None:
        self._subscribers: dict[type[Event], list[EventHandler[Any]]] = defaultdict(
            list
        )
        self._queues: dict[type[Event], list[asyncio.Queue[Any]]] = defaultdict(list)
        self._default_queue_maxsize = default_queue_maxsize
        self.clock = clock
        self._lock = asyncio.Lock()

    async def subscribe(
        self,
        event_type: type[T],
        handler: EventHandler[T],
    ) -> None:
        """Subscribe an async callback handler to events of event_type."""
        async with self._lock:
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)

    async def unsubscribe(
        self,
        event_type: type[T],
        handler: EventHandler[T],
    ) -> None:
        """Unsubscribe a callback handler from events of event_type."""
        async with self._lock:
            if handler in self._subscribers[event_type]:
                self._subscribers[event_type].remove(handler)

    async def subscribe_queue(
        self,
        event_type: type[T],
        maxsize: int | None = None,
    ) -> asyncio.Queue[T]:
        """Subscribe and get a dedicated backpressure-safe asyncio.Queue."""
        size = maxsize if maxsize is not None else self._default_queue_maxsize
        q: asyncio.Queue[T] = asyncio.Queue(maxsize=size)
        async with self._lock:
            self._queues[event_type].append(q)
        return q

    async def unsubscribe_queue(
        self,
        event_type: type[T],
        q: asyncio.Queue[Any],
    ) -> None:
        """Unsubscribe and remove a dedicated subscriber queue."""
        async with self._lock:
            if q in self._queues[event_type]:
                self._queues[event_type].remove(q)

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscriber queues and callback handlers."""
        event_cls = type(event)

        matching_types: list[type[Event]] = [
            cls for cls in event_cls.__mro__ if issubclass(cls, Event)
        ]

        handlers_to_call: list[EventHandler[Any]] = []
        queues_to_put: list[asyncio.Queue[Any]] = []

        async with self._lock:
            for et in matching_types:
                handlers_to_call.extend(self._subscribers.get(et, []))
                queues_to_put.extend(self._queues.get(et, []))

        # Preserve registration order: books and financial state must be updated
        # before a strategy consumes the same event. Critical failures propagate.
        for handler in handlers_to_call:
            result = handler(event)
            if inspect.isawaitable(result):
                await result

        # Deliver to subscriber queues with backpressure protection
        for q in queues_to_put:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                await q.put(event)


# Alias for spec parity
InMemoryEventBus = AsyncEventBus


class RedisStreamEventBus(AsyncEventBus):
    """EventBus that dispatches in-process and mirrors to Redis Stream when available."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        stream_key: str = "quantflow:events",
        default_queue_maxsize: int = 1000,
        clock: Clock | None = None,
    ) -> None:
        super().__init__(default_queue_maxsize=default_queue_maxsize, clock=clock)
        self.redis_url = redis_url
        self.stream_key = stream_key
        self._redis_client: Any = None

    async def connect(self) -> None:
        """Attempt connection to Redis instance."""
        try:
            import redis.asyncio as aioredis

            self._redis_client = aioredis.from_url(self.redis_url)
            await self._redis_client.ping()
        except Exception:
            self._redis_client = None

    async def close(self) -> None:
        """Close connection to Redis."""
        if self._redis_client is not None:
            try:
                await self._redis_client.close()
            except Exception:
                pass
            self._redis_client = None

    async def publish(self, event: Event) -> None:
        """Publish locally and to Redis stream if connected."""
        await super().publish(event)
        if self._redis_client is not None:
            try:
                data = {
                    "event_type": type(event).__name__,
                    "payload": event.model_dump_json(),
                }
                await self._redis_client.xadd(self.stream_key, data)
            except Exception:
                pass



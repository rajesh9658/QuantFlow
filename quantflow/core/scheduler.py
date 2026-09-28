"""Async scheduler abstraction and asyncio implementation."""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from quantflow.core.clock import Clock, SystemClock
from quantflow.core.logging import get_logger


class Scheduler(ABC):
    """Abstract scheduler interface supporting recurring and one-shot async jobs."""

    @abstractmethod
    async def schedule_recurring(
        self,
        job_id: str,
        interval_seconds: float,
        coro: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Schedule a recurring async job with non-overlapping execution.

        If a job with the same job_id exists, it is cancelled and replaced.
        """

    @abstractmethod
    async def schedule_once(
        self,
        job_id: str,
        delay_seconds: float,
        coro: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Schedule a one-shot delayed async job. Replaces existing job with same job_id."""

    @abstractmethod
    async def cancel(self, job_id: str) -> None:
        """Cancel a scheduled job by job_id."""

    @abstractmethod
    async def start(self) -> None:
        """Start the scheduler."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop all scheduled jobs."""


class AsyncIOScheduler(Scheduler):
    """AsyncIO implementation of Scheduler supporting non-overlapping recurring jobs."""

    def __init__(self, clock: Clock | None = None) -> None:
        self.clock: Clock = clock or SystemClock()
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._running_jobs: set[str] = set()
        self._lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()
        self._logger = get_logger("scheduler")

    async def start(self) -> None:
        """Start scheduler and reset shutdown state."""
        self._shutdown_event.clear()

    async def stop(self) -> None:
        """Gracefully stop all tasks and release resources."""
        self._shutdown_event.set()
        tasks_to_cancel = [t for t in self._tasks.values() if not t.done()]
        for task in tasks_to_cancel:
            task.cancel()
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
        self._tasks.clear()
        self._running_jobs.clear()

    async def schedule_recurring(
        self,
        job_id: str,
        interval_seconds: float,
        coro: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Schedule a recurring async job with non-overlapping execution."""
        await self.cancel(job_id)

        async def _recurring_wrapper() -> None:
            while not self._shutdown_event.is_set():
                try:
                    await self.clock.sleep(interval_seconds)
                except asyncio.CancelledError:
                    break

                if self._shutdown_event.is_set():
                    break

                # Overlapping-run prevention
                async with self._lock:
                    if job_id in self._running_jobs:
                        self._logger.debug(
                            f"Skipping scheduled execution of '{job_id}': previous run still in progress."
                        )
                        continue
                    self._running_jobs.add(job_id)

                try:
                    await coro(*args, **kwargs)
                except asyncio.CancelledError:
                    break
                except Exception as err:
                    self._logger.error(
                        f"Recurring job '{job_id}' failed: {err}",
                        exc_info=True,
                    )
                finally:
                    async with self._lock:
                        self._running_jobs.discard(job_id)

        task = asyncio.create_task(_recurring_wrapper())
        self._tasks[job_id] = task

    async def schedule_once(
        self,
        job_id: str,
        delay_seconds: float,
        coro: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Schedule a one-shot delayed async job."""
        await self.cancel(job_id)

        async def _once_wrapper() -> None:
            try:
                await self.clock.sleep(delay_seconds)
                if self._shutdown_event.is_set():
                    return
                await coro(*args, **kwargs)
            except asyncio.CancelledError:
                pass
            except Exception as err:
                self._logger.error(
                    f"One-shot job '{job_id}' failed: {err}",
                    exc_info=True,
                )
            finally:
                self._tasks.pop(job_id, None)

        task = asyncio.create_task(_once_wrapper())
        self._tasks[job_id] = task

    async def cancel(self, job_id: str) -> None:
        """Cancel a scheduled job if active."""
        task = self._tasks.pop(job_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        async with self._lock:
            self._running_jobs.discard(job_id)

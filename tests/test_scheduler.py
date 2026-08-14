"""Tests for AsyncIOScheduler."""

import asyncio
import pytest

from quantflow.core.scheduler import AsyncIOScheduler


@pytest.mark.asyncio
async def test_scheduler_overlapping_run_prevention() -> None:
    """Verify recurring job skips ticks if previous execution is still running."""
    scheduler = AsyncIOScheduler()
    await scheduler.start()

    run_count = 0
    concurrent_runs = 0
    max_concurrent_runs = 0

    async def slow_job() -> None:
        nonlocal run_count, concurrent_runs, max_concurrent_runs
        run_count += 1
        concurrent_runs += 1
        if concurrent_runs > max_concurrent_runs:
            max_concurrent_runs = concurrent_runs

        await asyncio.sleep(0.12)
        concurrent_runs -= 1

    # Schedule with 0.02s interval, while job takes 0.12s
    await scheduler.schedule_recurring("slow_job", 0.02, slow_job)

    await asyncio.sleep(0.2)
    await scheduler.stop()

    # Max concurrent runs must be exactly 1 due to overlapping-run prevention
    assert max_concurrent_runs == 1
    # Run count should be 1 or 2, not 10
    assert 1 <= run_count <= 3


@pytest.mark.asyncio
async def test_scheduler_one_shot_job() -> None:
    """Verify one-shot delayed job executes after delay."""
    scheduler = AsyncIOScheduler()
    await scheduler.start()

    executed = False

    async def once_job() -> None:
        nonlocal executed
        executed = True

    await scheduler.schedule_once("once_job", 0.03, once_job)
    assert not executed

    await asyncio.sleep(0.06)
    assert executed

    await scheduler.stop()


@pytest.mark.asyncio
async def test_scheduler_cancel_job() -> None:
    """Verify cancelling a scheduled job prevents its execution."""
    scheduler = AsyncIOScheduler()
    await scheduler.start()

    executed = False

    async def dummy_job() -> None:
        nonlocal executed
        executed = True

    await scheduler.schedule_once("cancel_job", 0.05, dummy_job)
    await scheduler.cancel("cancel_job")

    await asyncio.sleep(0.08)
    assert not executed

    await scheduler.stop()

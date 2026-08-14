"""Tests for structured logging and contextvars correlation_id propagation."""

import asyncio
import logging
import pytest

from quantflow.core.logging import (
    get_correlation_id,
    get_logger,
    set_correlation_id,
    setup_logging,
)


@pytest.mark.asyncio
async def test_correlation_id_propagation_nested_async() -> None:
    """Verify correlation_id propagates through nested async calls and tasks."""
    expected_cid = "req-test-uuid-98765"
    set_correlation_id(expected_cid)

    assert get_correlation_id() == expected_cid

    async def nested_child_task(name: str) -> str | None:
        await asyncio.sleep(0.01)
        cid = get_correlation_id()
        return cid

    async def nested_parent_coro() -> list[str | None]:
        # Task 1 spawned asynchronously inherit context
        t1 = asyncio.create_task(nested_child_task("t1"))
        t2 = asyncio.create_task(nested_child_task("t2"))
        results = await asyncio.gather(t1, t2)
        return list(results)

    results = await nested_parent_coro()
    assert results == [expected_cid, expected_cid]


def test_structured_logging_setup() -> None:
    """Verify setup_logging configures logger without errors."""
    logger = setup_logging(level="DEBUG", json_format=True)
    assert logger.level == logging.DEBUG

    custom_logger = get_logger("test_module")
    assert custom_logger.name == "quantflow.test_module"

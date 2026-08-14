"""Tests for HealthAggregator and health check registration."""

import pytest

from quantflow.core.health import HealthAggregator


@pytest.mark.asyncio
async def test_health_aggregator_reports_healthy_when_all_pass() -> None:
    """Verify aggregator returns healthy status when all registered checks succeed."""
    aggregator = HealthAggregator()
    aggregator.register("db", lambda: True)

    async def async_check() -> bool:
        return True

    aggregator.register("event_bus", async_check)

    res = await aggregator.check_health()
    assert res["status"] == "healthy"
    assert res["checks"]["db"]["status"] == "healthy"
    assert res["checks"]["event_bus"]["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_aggregator_reports_degraded_if_any_check_fails() -> None:
    """Verify aggregator reports degraded if any check fails or raises exception."""
    aggregator = HealthAggregator()
    aggregator.register("healthy_comp", lambda: True)
    aggregator.register("failing_comp", lambda: False)

    async def raising_check() -> bool:
        raise RuntimeError("Connection timed out")

    aggregator.register("error_comp", raising_check)

    res = await aggregator.check_health()
    assert res["status"] == "degraded"
    assert res["checks"]["healthy_comp"]["status"] == "healthy"
    assert res["checks"]["failing_comp"]["status"] == "degraded"
    assert res["checks"]["error_comp"]["status"] == "degraded"
    assert "Connection timed out" in res["checks"]["error_comp"]["error"]

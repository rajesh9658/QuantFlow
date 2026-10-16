"""Tests for app/main.py bootstrap and healthz callable."""

import pytest

from quantflow.app.main import bootstrap_app, healthz, load_config
from quantflow.config.manager import ConfigManager
from quantflow.core.di import DIContainer
from quantflow.core.interfaces import EventBus


def test_app_load_config_and_build_container() -> None:
    """Verify application config loading and DI container construction."""
    config = load_config()
    assert isinstance(config, ConfigManager)
    assert config.get("environment") == "development"

    container = bootstrap_app()
    assert isinstance(container, DIContainer)
    assert container.has(ConfigManager)
    assert container.has(EventBus)


@pytest.mark.asyncio
async def test_app_healthz_callable() -> None:
    """Verify healthz callable returns overall system health status."""
    status = await healthz()
    assert isinstance(status, dict)
    assert status["status"] in ("healthy", "degraded")
    assert "system" in status["checks"]


def test_fastapi_main_composition_lifespan() -> None:
    """Verify main composition root lifespan and endpoint exposition."""
    from fastapi.testclient import TestClient

    from quantflow.main import app as main_app

    with TestClient(main_app) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        metrics_resp = client.get("/metrics")
        assert metrics_resp.status_code == 200
        assert "quantflow_portfolio_equity" in metrics_resp.text

        v1_resp = client.get("/api/v1/portfolio")
        assert v1_resp.status_code == 200


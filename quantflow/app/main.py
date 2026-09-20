"""Application main entrypoint and initialization wireup."""

import asyncio
from pathlib import Path
from typing import Any

from quantflow.config.manager import ConfigManager
from quantflow.core.di import DIContainer
from quantflow.core.event_bus import AsyncEventBus
from quantflow.core.health import HealthAggregator
from quantflow.core.interfaces import EventBus
from quantflow.core.logging import get_logger, setup_logging

_container: DIContainer | None = None
_health_aggregator: HealthAggregator | None = None
_config: ConfigManager | None = None

logger = get_logger("app.main")


def load_config(config_path: str | Path | None = None) -> ConfigManager:
    """Load application configuration."""
    defaults = {
        "environment": "development",
        "log_level": "INFO",
        "event_bus": {"max_queue_size": 1000},
        "analytics": {
            "risk_free_rate": 0.0,
            "annualization_factor": 252.0,
        },
    }
    return ConfigManager(config_path=config_path, defaults=defaults)


def build_container(config: ConfigManager) -> DIContainer:
    """Build and populate the DI container."""
    container = DIContainer()
    container.register(ConfigManager, config)

    # Register EventBus interface to AsyncEventBus implementation
    max_queue_size = config.get("event_bus.max_queue_size", 1000)
    event_bus = AsyncEventBus(default_queue_maxsize=max_queue_size)
    container.register(EventBus, event_bus)

    # Register HealthAggregator
    health_agg = HealthAggregator()
    health_agg.register("system", lambda: True)
    container.register(HealthAggregator, health_agg)

    return container


def bootstrap_app(config_path: str | Path | None = None) -> DIContainer:
    """Bootstrap application config, logging, container, and health aggregator."""
    global _container, _health_aggregator, _config

    _config = load_config(config_path)
    log_level = _config.get("log_level", "INFO")
    setup_logging(level=log_level)

    _container = build_container(_config)
    _health_aggregator = _container.resolve(HealthAggregator)

    logger.info("QuantFlow application bootstrapped successfully.")
    return _container


async def healthz() -> dict[str, Any]:
    """Health check callable endpoint.

    Returns overall status and individual health check components.
    """
    global _health_aggregator
    if _health_aggregator is None:
        bootstrap_app()
    assert _health_aggregator is not None
    return await _health_aggregator.check_health()


def main() -> None:
    """Entry point for running the application."""
    bootstrap_app()
    status = asyncio.run(healthz())
    logger.info(f"Health status on startup: {status['status']}")


if __name__ == "__main__":
    main()

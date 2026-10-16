"""QuantFlow composition root and ASGI application entrypoint.

Initializes all subsystem engines (DI, EventBus, Exchanges, MarketData,
Strategies, Risk, Execution, Portfolio, Analytics, Scheduler) via FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from quantflow.analytics.engine import AnalyticsEngine
from quantflow.api.app import create_app as create_api_app
from quantflow.api.dependencies import APIState, set_api_state
from quantflow.api.websocket import ws_manager
from quantflow.config.manager import ConfigManager
from quantflow.core.clock import SystemClock
from quantflow.core.di import DIContainer
from quantflow.core.event_bus import (
    AsyncEventBus,
    InMemoryEventBus,
    RedisStreamEventBus,
)
from quantflow.core.exchange_registry import ExchangeRegistry
from quantflow.core.health import HealthAggregator
from quantflow.core.interfaces import EventBus
from quantflow.core.logging import get_logger, setup_logging
from quantflow.core.plugin_loader import PluginLoader
from quantflow.core.scheduler import AsyncIOScheduler
from quantflow.execution.paper import PaperExecutionHandler
from quantflow.market_data.engine import MarketDataEngine
from quantflow.portfolio.engine import PortfolioEngine
from quantflow.replay.event_store import SyntheticEventStore
from quantflow.risk.engine import RiskEngine
from quantflow.strategies.engine import StrategyEngine

logger = get_logger("quantflow.main")


async def _run_synthetic_feed(
    event_bus: EventBus,
    stop_event: asyncio.Event,
    interval_seconds: float = 1.0,
) -> None:
    """Background task providing deterministic tick and orderbook stream for paper/demo mode."""
    store = SyntheticEventStore(symbols=["BTC/USDT", "ETH/USDT"])
    step = 0
    while not stop_event.is_set():
        try:
            for sym in store.symbols:
                tick = store.generate_tick(sym, step=step)
                await event_bus.publish(tick)
            step += 1
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug("Synthetic feed error: %s", e)
            await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle for all QuantFlow subsystem engines."""
    logger.info("Initializing QuantFlow composition root...")

    # 1. Resolve Config & Logging
    config = ConfigManager()
    log_level = config.get("log_level", os.environ.get("LOG_LEVEL", "INFO"))
    setup_logging(level=log_level)

    # 2. Go-Live Attestation Guard (Sprint 15)
    app_env = os.environ.get("APP_ENV", config.get("environment", "development")).lower()
    if app_env == "live":
        attestation_file = Path("go_live/attestation.json")
        signing_key = os.environ.get("QUANTFLOW_GO_LIVE_SIGNING_KEY")
        if not attestation_file.exists() or not signing_key:
            raise RuntimeError(
                "CRITICAL: QuantFlow refuses to start in LIVE mode without a valid "
                "go_live/attestation.json and QUANTFLOW_GO_LIVE_SIGNING_KEY."
            )

    # 3. Construct EventBus based on QUANTFLOW_EVENT_BUS_TYPE
    bus_type = os.environ.get("QUANTFLOW_EVENT_BUS_TYPE", "in_memory").lower()
    event_bus: EventBus
    if bus_type == "redis":
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        redis_bus = RedisStreamEventBus(redis_url=redis_url)
        await redis_bus.connect()
        event_bus = redis_bus
        logger.info("Configured RedisStreamEventBus at %s", redis_url)
    else:
        event_bus = InMemoryEventBus()
        logger.info("Configured InMemoryEventBus")

    # 4. Construct DI Container & core providers
    clock = SystemClock()
    container = DIContainer()
    container.register(ConfigManager, config)
    container.register(EventBus, event_bus)

    health_agg = HealthAggregator()
    health_agg.register("system", lambda: True)
    container.register(HealthAggregator, health_agg)

    # 5. Build Subsystems
    registry = ExchangeRegistry(config=config, clock=clock)
    market_data = MarketDataEngine(
        event_bus=event_bus, clock=clock, registry=registry
    )
    plugin_loader = PluginLoader(config=config, container=container)
    risk_engine = RiskEngine(config=config, event_bus=event_bus)
    execution_handler = PaperExecutionHandler(
        config=config, event_bus=event_bus, clock=clock, registry=registry
    )
    portfolio_engine = PortfolioEngine(
        config=config, event_bus=event_bus, clock=clock
    )
    analytics_engine = AnalyticsEngine(config=config, event_bus=event_bus)
    strategy_engine = StrategyEngine(event_bus=event_bus)
    scheduler = AsyncIOScheduler()

    # 6. Subscribe engines and WebSocket manager
    await ws_manager.subscribe_to_event_bus(event_bus)
    await portfolio_engine.start()
    await risk_engine.start()

    # 7. Bridge APIState singleton
    api_state = APIState(
        config=config,
        event_bus=event_bus,
        portfolio_engine=portfolio_engine,
        risk_engine=risk_engine,
        analytics_engine=analytics_engine,
        strategy_engine=strategy_engine,
    )
    set_api_state(api_state)

    # 8. Start background synthetic feed for paper / demo mode
    synthetic_stop_event = asyncio.Event()
    synthetic_task = None
    if app_env != "live":
        synthetic_task = asyncio.create_task(
            _run_synthetic_feed(event_bus, synthetic_stop_event)
        )
        logger.info("Started background synthetic market data feed.")

    logger.info("QuantFlow startup complete. Serving on configured ports.")
    yield

    # Shutdown in reverse order
    logger.info("Shutting down QuantFlow...")
    if synthetic_task:
        synthetic_stop_event.set()
        synthetic_task.cancel()
        try:
            await asyncio.wait_for(synthetic_task, timeout=2.0)
        except (asyncio.CancelledError, TimeoutError):
            pass

    await portfolio_engine.stop()
    await risk_engine.stop()
    if isinstance(event_bus, RedisStreamEventBus):
        await event_bus.close()

    logger.info("QuantFlow shutdown complete.")


def create_app() -> FastAPI:
    """Create and return the production-ready QuantFlow ASGI app."""
    application = create_api_app()
    # Attach top-level composition lifespan
    application.router.lifespan_context = lifespan
    return application


# Global ASGI application instance for uvicorn
app = create_app()

__all__ = ["app", "create_app"]

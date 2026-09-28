"""FastAPI application factory for QuantFlow."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from quantflow.api.dependencies import get_api_state
from quantflow.api.routes import router as api_router
from quantflow.api.websocket import ws_manager, ws_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager to subscribe WS manager to EventBus on startup."""
    state = get_api_state()
    if state.event_bus:
        await ws_manager.subscribe_to_event_bus(state.event_bus)
    yield


def create_app() -> FastAPI:
    """Create and configure the QuantFlow FastAPI application."""
    app = FastAPI(
        title="QuantFlow Trading Platform API",
        description=(
            "High-performance real-time quantitative trading API "
            "and WebSocket stream."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Enable CORS for local Vite dashboard development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount REST and WebSocket routes
    app.include_router(api_router)
    app.include_router(ws_router)

    @app.get("/health", tags=["Health"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app


# Default app instance
app = create_app()

"""FastAPI application factory for QuantFlow."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from quantflow.api.dependencies import get_api_state
from quantflow.api.routes import router as api_router
from quantflow.api.websocket import ws_manager, ws_router

logger = logging.getLogger("quantflow.api.app")
_started_at = datetime.now(UTC).isoformat()


def generate_prometheus_metrics() -> str:
    """Generate standard Prometheus exposition format text."""
    state = get_api_state()
    snapshot = state.get_portfolio_snapshot()
    analytics = state.get_analytics_metrics()
    lines = [
        "# HELP quantflow_portfolio_equity Current portfolio equity in USD",
        "# TYPE quantflow_portfolio_equity gauge",
        f"quantflow_portfolio_equity {snapshot.get('total_equity', 100000.0)}",
        "# HELP quantflow_portfolio_cash Current free cash in USD",
        "# TYPE quantflow_portfolio_cash gauge",
        f"quantflow_portfolio_cash {snapshot.get('cash', 100000.0)}",
        "# HELP quantflow_realized_pnl Total realized PnL",
        "# TYPE quantflow_realized_pnl gauge",
        f"quantflow_realized_pnl {snapshot.get('realized_pnl', 0.0)}",
        "# HELP quantflow_unrealized_pnl Current unrealized PnL",
        "# TYPE quantflow_unrealized_pnl gauge",
        f"quantflow_unrealized_pnl {snapshot.get('unrealized_pnl', 0.0)}",
        "# HELP quantflow_sharpe_ratio Annualized Sharpe ratio",
        "# TYPE quantflow_sharpe_ratio gauge",
        f"quantflow_sharpe_ratio {analytics.get('sharpe', 0.0)}",
        "# HELP quantflow_win_rate Overall strategy win rate",
        "# TYPE quantflow_win_rate gauge",
        f"quantflow_win_rate {analytics.get('win_rate', 0.0)}",
        "# HELP quantflow_system_healthy System health status (1 = healthy, 0 = degraded)",
        "# TYPE quantflow_system_healthy gauge",
        "quantflow_system_healthy 1",
    ]
    return "\n".join(lines) + "\n"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager to subscribe WS manager to EventBus on startup."""
    state = get_api_state()
    if state.event_bus:
        await ws_manager.subscribe_to_event_bus(state.event_bus)
    try:
        yield
    finally:
        await state.close()
        await ws_manager.unsubscribe_from_event_bus()


def create_app() -> FastAPI:
    """Create and configure the QuantFlow FastAPI application."""
    app = FastAPI(
        title="QuantFlow Trading Platform API",
        description=(
            "High-performance real-time quantitative trading API and WebSocket stream."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Middleware: Request ID & Structured Error Handling
    @app.middleware("http")
    async def request_id_and_error_middleware(
        request: Request, call_next: Any
    ) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = req_id
        try:
            response: Response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        except Exception as exc:
            logger.exception("Unhandled error processing request: %s", exc)
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_SERVER_ERROR",
                        "message": str(exc) or "Internal server error",
                        "request_id": req_id,
                    }
                },
                headers={"X-Request-ID": req_id},
            )

    # Configure CORS: explicit origins with credentials
    env_origins = os.environ.get("QUANTFLOW_CORS_ORIGINS")
    if env_origins:
        cors_origins = [o.strip() for o in env_origins.split(",") if o.strip()]
    else:
        cors_origins = [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount REST routes under both /api/v1 (spec) and /api (legacy test compatibility)
    app.include_router(api_router, prefix="/api/v1")
    app.include_router(api_router, prefix="/api")
    app.include_router(ws_router)

    @app.get("/health", tags=["Health"])
    async def health_check() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": "0.1.0",
            "started_at": _started_at,
            "execution_mode": "paper",
            "demo_fixtures": get_api_state().demo_mode,
            "data_source": get_api_state().config.get("market_data.source", "none"),
        }

    @app.get("/ready", tags=["Health"])
    async def readiness() -> JSONResponse:
        ready = bool(getattr(app.state, "pipeline_started", False))
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "ready": ready,
                "execution_mode": "paper",
                "data_source": getattr(app.state, "data_source", "none"),
                "market_feed_available": getattr(app.state, "data_source", "none")
                != "none",
                "historical_data_configured": bool(
                    get_api_state().config.get("backtest.data_path")
                ),
                "live_trading_supported": False,
            },
        )

    @app.get("/metrics", tags=["Monitoring"])
    async def prometheus_metrics() -> Response:
        exposition = generate_prometheus_metrics()
        return Response(
            content=exposition,
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return app


# Default app instance
app = create_app()

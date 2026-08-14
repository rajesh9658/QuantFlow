"""Endpoint-agnostic health check registry and status aggregator."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

HealthCheckCallable = Callable[
    [], Awaitable[bool | dict[str, Any]] | bool | dict[str, Any]
]


class HealthAggregator:
    """Registry and aggregator for application health checks."""

    def __init__(self) -> None:
        self._checks: dict[str, HealthCheckCallable] = {}

    def register(self, name: str, check: HealthCheckCallable) -> None:
        """Register a component health check function (sync or async)."""
        self._checks[name] = check

    async def check_health(self) -> dict[str, Any]:
        """Execute all registered health checks and aggregate overall system status.

        Returns overall status 'healthy' if all pass, or 'degraded' if any check fails
        or raises an exception.
        """
        results: dict[str, Any] = {}
        overall_status = "healthy"

        for name, check_fn in self._checks.items():
            try:
                if inspect.iscoroutinefunction(check_fn):
                    res = await check_fn()
                else:
                    res = check_fn()
                    if inspect.isawaitable(res):
                        res = await res

                if isinstance(res, bool):
                    is_ok = res
                    check_detail: dict[str, Any] = {
                        "status": "healthy" if is_ok else "degraded"
                    }
                elif isinstance(res, dict):
                    status_str = str(res.get("status", "healthy")).lower()
                    is_ok = status_str in ("healthy", "ok", "pass")
                    check_detail = {
                        "status": "healthy" if is_ok else "degraded",
                        **res,
                    }
                else:
                    is_ok = bool(res)
                    check_detail = {"status": "healthy" if is_ok else "degraded"}

                if not is_ok:
                    overall_status = "degraded"

                results[name] = check_detail

            except Exception as exc:
                overall_status = "degraded"
                results[name] = {
                    "status": "degraded",
                    "error": str(exc) or exc.__class__.__name__,
                }

        return {
            "status": overall_status,
            "checks": results,
        }

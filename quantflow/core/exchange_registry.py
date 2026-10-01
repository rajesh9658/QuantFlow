"""Exchange Registry: concurrent lifecycle management with failure isolation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from quantflow.config.manager import ConfigManager
from quantflow.core.clock import Clock, SystemClock
from quantflow.core.interfaces import ExchangeAdapter
from quantflow.core.logging import get_logger


@dataclass
class ExchangeStatus:
    """Snapshot of an adapter's current lifecycle state."""

    exchange_id: str
    enabled: bool
    connected: bool
    connected_since: datetime | None = None
    last_heartbeat: datetime | None = None
    last_error: str | None = None
    reconnect_count: int = 0


AdapterBuilder = Callable[[str, dict[str, Any], ConfigManager, Clock], ExchangeAdapter]
"""Signature: (exchange_id, exchange_cfg, config, clock) -> ExchangeAdapter."""


class ExchangeRegistry:
    """Holds N ExchangeAdapter instances keyed by exchange_id.

    Concurrent lifecycle with independent failure isolation:
    one adapter failing to connect does not prevent others from starting.
    """

    def __init__(
        self,
        config: ConfigManager | dict[str, Any],
        clock: Clock | None = None,
        adapter_builders: Mapping[str, AdapterBuilder] | None = None,
    ) -> None:
        self._config: ConfigManager = (
            config
            if isinstance(config, ConfigManager)
            else ConfigManager(defaults=config if isinstance(config, dict) else None)
        )
        self._clock = clock or SystemClock()
        self._builders: dict[str, AdapterBuilder] = (
            dict(adapter_builders) if adapter_builders else {}
        )
        self._adapters: dict[str, ExchangeAdapter] = {}
        self._status: dict[str, ExchangeStatus] = {}
        self._logger = get_logger("exchange_registry")

    async def register(self, exchange_id: str, adapter: ExchangeAdapter) -> None:
        """Register an already-constructed adapter (used by tests / DI)."""
        if exchange_id in self._adapters:
            raise ValueError(f"Exchange '{exchange_id}' already registered")
        self._adapters[exchange_id] = adapter
        self._status[exchange_id] = ExchangeStatus(
            exchange_id=exchange_id,
            enabled=True,
            connected=False,
        )

    async def start_all(self) -> dict[str, Exception]:
        """Concurrently connect all enabled adapters.

        Failure isolation: each adapter's connect() runs in its own task;
        an exception is captured per-exchange and does NOT abort the others.
        Returns a dict of {exchange_id: exception} for any that failed.
        """
        enabled = self._read_exchange_configs(enabled_only=True)
        enabled_ids = {cfg["exchange_id"] for cfg in enabled}

        tasks: list[tuple[str, Any]] = []
        for cfg in enabled:
            tasks.append((cfg["exchange_id"], self._start_one(cfg)))

        # Also start any registered adapters not explicitly in config list
        for eid, adapter in list(self._adapters.items()):
            if eid not in enabled_ids:
                tasks.append((eid, self._start_registered(eid, adapter)))

        if not tasks:
            return {}

        results = await asyncio.gather(
            *(coro for _, coro in tasks), return_exceptions=True
        )

        failures: dict[str, Exception] = {}
        for (eid, _), result in zip(tasks, results, strict=False):
            if isinstance(result, Exception):
                failures[eid] = result
                self._logger.error(
                    f"Exchange {eid} failed to start: {result}",
                    exc_info=result,
                )
        return failures

    async def stop_all(self) -> None:
        """Concurrently disconnect all adapters. Errors are logged, not raised."""
        coros = [self._stop_one(eid) for eid in list(self._adapters.keys())]
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    async def start(self, exchange_id: str) -> None:
        """Start a single adapter (used for hot-enable)."""
        try:
            cfg = self._find_config(exchange_id)
            await self._start_one(cfg)
        except KeyError:
            adapter = self._adapters.get(exchange_id)
            if adapter is None:
                raise KeyError(
                    f"No exchange registered with id '{exchange_id}'"
                ) from None
            await self._start_registered(exchange_id, adapter)

    async def stop(self, exchange_id: str) -> None:
        """Stop a single adapter (used for hot-disable / maintenance)."""
        await self._stop_one(exchange_id)

    def get(self, exchange_id: str) -> ExchangeAdapter:
        """Return the adapter. Raises KeyError if unknown."""
        if exchange_id not in self._adapters:
            raise KeyError(f"No exchange registered with id '{exchange_id}'")
        return self._adapters[exchange_id]

    def get_status(self, exchange_id: str) -> ExchangeStatus:
        """Return a status snapshot for a single exchange."""
        if exchange_id not in self._status:
            raise KeyError(f"No exchange registered with id '{exchange_id}'")
        return self._status[exchange_id]

    def get_all_status(self) -> dict[str, ExchangeStatus]:
        """Return status snapshots for every registered exchange."""
        return dict(self._status)

    # ---------- Internal ----------

    async def _start_one(self, cfg: dict[str, Any]) -> None:
        exchange_id = cfg["exchange_id"]
        adapter_type = cfg.get("type", "")

        adapter = self._adapters.get(exchange_id)
        if adapter is None:
            builder = self._builders.get(adapter_type)
            if builder is None:
                raise ValueError(
                    f"No adapter builder registered for type '{adapter_type}' "
                    f"(exchange_id={exchange_id})"
                )
            adapter = builder(exchange_id, cfg, self._config, self._clock)
            self._adapters[exchange_id] = adapter

        if exchange_id not in self._status:
            self._status[exchange_id] = ExchangeStatus(
                exchange_id=exchange_id,
                enabled=cfg.get("enabled", True),
                connected=False,
            )

        if self._status[exchange_id].connected:
            self._logger.debug(f"Exchange {exchange_id} already connected")
            return

        try:
            await adapter.connect()
            self._status[exchange_id].connected = True
            self._status[exchange_id].connected_since = self._clock.now()
            self._logger.info(f"Exchange {exchange_id} connected")
        except Exception as e:
            self._status[exchange_id].connected = False
            self._status[exchange_id].last_error = str(e) or "connect() failed"
            raise

    async def _start_registered(
        self, exchange_id: str, adapter: ExchangeAdapter
    ) -> None:
        if exchange_id not in self._status:
            self._status[exchange_id] = ExchangeStatus(
                exchange_id=exchange_id,
                enabled=True,
                connected=False,
            )

        if self._status[exchange_id].connected:
            return

        try:
            await adapter.connect()
            self._status[exchange_id].connected = True
            self._status[exchange_id].connected_since = self._clock.now()
            self._logger.info(f"Exchange {exchange_id} connected")
        except Exception as e:
            self._status[exchange_id].connected = False
            self._status[exchange_id].last_error = str(e) or "connect() failed"
            raise

    async def _stop_one(self, exchange_id: str) -> None:
        adapter = self._adapters.get(exchange_id)
        if adapter is None:
            return
        try:
            await adapter.disconnect()
        except Exception as e:
            self._logger.warning(f"Exchange {exchange_id} disconnect error: {e}")
        finally:
            if exchange_id in self._status:
                self._status[exchange_id].connected = False
            self._logger.info(f"Exchange {exchange_id} stopped")

    def _read_exchange_configs(
        self, enabled_only: bool = False
    ) -> list[dict[str, Any]]:
        exchanges = self._config.get("exchanges", [])
        if not isinstance(exchanges, list):
            return []
        if enabled_only:
            return [
                e for e in exchanges if isinstance(e, dict) and e.get("enabled", True)
            ]
        return [e for e in exchanges if isinstance(e, dict)]

    def _find_config(self, exchange_id: str) -> dict[str, Any]:
        for e in self._read_exchange_configs():
            if e.get("exchange_id") == exchange_id:
                return e
        raise KeyError(f"No config found for exchange '{exchange_id}'")

"""Tests for ExchangeRegistry: concurrent start, failure isolation, and lifecycle."""

from __future__ import annotations

from typing import Any

import pytest

from quantflow.config.manager import ConfigManager
from quantflow.core.clock import Clock, SystemClock
from quantflow.core.exchange_registry import ExchangeRegistry
from quantflow.core.interfaces import ExchangeAdapter


class MockAdapter(ExchangeAdapter):
    """Mock adapter for registry tests."""

    def __init__(self, exchange_id: str, should_fail: bool = False) -> None:
        self.exchange_id = exchange_id
        self.should_fail = should_fail
        self.connected = False
        self.disconnected = False

    async def connect(self) -> None:
        if self.should_fail:
            raise ConnectionError(f"Bad credentials for {self.exchange_id}")
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False
        self.disconnected = True

    async def subscribe_market_data(self, symbols: list[str]) -> None:
        pass

    async def place_order(self, order: Any) -> str:
        return "order_123"

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def get_balances(self) -> dict[str, float]:
        return {}


@pytest.mark.asyncio
async def test_registry_failure_isolation() -> None:
    """Registry starts 2 adapters concurrently, one fails, other connects."""
    config_dict = {
        "exchanges": [
            {
                "exchange_id": "binance",
                "type": "binance",
                "enabled": True,
                "credentials_ref": "valid_cred",
            },
            {
                "exchange_id": "bybit",
                "type": "bybit",
                "enabled": True,
                "credentials_ref": "bad_cred",
            },
        ]
    }
    cfg = ConfigManager(defaults=config_dict)
    clock = SystemClock()

    def builder(
        eid: str, exch_cfg: dict[str, Any], config: ConfigManager, clk: Clock
    ) -> ExchangeAdapter:
        should_fail = eid == "bybit"
        return MockAdapter(eid, should_fail=should_fail)

    builders = {
        "binance": builder,
        "bybit": builder,
    }

    registry = ExchangeRegistry(cfg, clock, builders)

    failures = await registry.start_all()

    # Assert no global failure, but per-exchange failure recorded
    assert "bybit" in failures
    assert isinstance(failures["bybit"], ConnectionError)
    assert "binance" not in failures

    # Assert Binance connected and Bybit disconnected
    binance_status = registry.get_status("binance")
    assert binance_status.connected is True
    assert binance_status.last_error is None
    assert binance_status.connected_since is not None

    bybit_status = registry.get_status("bybit")
    assert bybit_status.connected is False
    assert bybit_status.last_error is not None
    assert "Bad credentials" in bybit_status.last_error

    # Can retrieve the successfully connected adapter
    binance_adapter = registry.get("binance")
    assert isinstance(binance_adapter, MockAdapter)
    assert binance_adapter.connected is True

    # Stop all clean up
    await registry.stop_all()
    assert binance_status.connected is False


@pytest.mark.asyncio
async def test_registry_manual_registration_and_lookup() -> None:
    """Test manual adapter registration via register()."""
    registry = ExchangeRegistry(ConfigManager())
    adapter = MockAdapter("test_exchange")

    await registry.register("test_exchange", adapter)
    assert registry.get("test_exchange") is adapter

    status = registry.get_status("test_exchange")
    assert status.exchange_id == "test_exchange"
    assert status.connected is False

    await registry.start("test_exchange")
    assert registry.get_status("test_exchange").connected is True

    await registry.stop("test_exchange")
    assert registry.get_status("test_exchange").connected is False

    with pytest.raises(KeyError):
        registry.get("non_existent")

    with pytest.raises(ValueError):
        await registry.register("test_exchange", adapter)


@pytest.mark.asyncio
async def test_registry_accepts_dict_and_passes_config_manager() -> None:
    """ExchangeRegistry accepts a raw dict and passes a ConfigManager instance to builders."""
    received_config: Any = None

    def builder(
        eid: str, exch_cfg: dict[str, Any], config: ConfigManager, clk: Clock
    ) -> ExchangeAdapter:
        nonlocal received_config
        received_config = config
        return MockAdapter(eid)

    raw_config = {
        "exchanges": [
            {"exchange_id": "binance", "type": "binance", "enabled": True}
        ]
    }
    registry = ExchangeRegistry(raw_config, adapter_builders={"binance": builder})
    await registry.start("binance")

    assert isinstance(received_config, ConfigManager)
    assert registry.get_status("binance").connected is True


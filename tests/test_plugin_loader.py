"""Tests for PluginLoader strategy plugin discovery and failure isolation."""

import logging
from pathlib import Path
import pytest

from quantflow.config.manager import ConfigManager
from quantflow.core.di import DIContainer
from quantflow.core.interfaces import Strategy
from quantflow.core.plugin_loader import PluginLoader


@pytest.mark.asyncio
async def test_plugin_loader_discovers_example_plugin() -> None:
    """Verify PluginLoader discovers and loads the _example strategy plugin end-to-end."""
    config = ConfigManager()
    container = DIContainer()

    strategies_dir = Path(__file__).parent.parent / "quantflow" / "strategies"
    loader = PluginLoader(config, container, strategies_dir=strategies_dir)

    loaded = await loader.discover_and_load()

    assert "ExampleStrategy" in loaded
    strategy = loaded["ExampleStrategy"]
    assert isinstance(strategy, Strategy)
    assert strategy.get_name() == "ExampleStrategy"

    # Verify registration in DI container as named singleton
    resolved = container.resolve_named("strategy_ExampleStrategy")
    assert resolved is strategy


@pytest.mark.asyncio
async def test_broken_plugin_does_not_prevent_valid_plugin(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify a broken plugin raising ImportError does not prevent valid plugins from loading."""
    strategies_dir = tmp_path / "strategies"
    strategies_dir.mkdir()

    # 1. Create valid plugin directory
    valid_dir = strategies_dir / "valid_plugin"
    valid_dir.mkdir()
    (valid_dir / "strategy.yaml").write_text(
        """
name: "ValidPlugin"
version: "0.1.0"
min_framework_version: "0.1.0"
entry_point: "quantflow.strategies._example.ExampleStrategy"
""",
        encoding="utf-8",
    )

    # 2. Create broken plugin directory with non-existent module entrypoint
    broken_dir = strategies_dir / "broken_plugin"
    broken_dir.mkdir()
    (broken_dir / "strategy.yaml").write_text(
        """
name: "BrokenPlugin"
version: "0.1.0"
min_framework_version: "0.1.0"
entry_point: "non_existent_package.invalid_module.BrokenClass"
""",
        encoding="utf-8",
    )

    config = ConfigManager()
    container = DIContainer()
    loader = PluginLoader(config, container, strategies_dir=strategies_dir)

    with caplog.at_level(logging.ERROR):
        loaded = await loader.discover_and_load()

    # Valid plugin loaded
    assert "ValidPlugin" in loaded
    assert "BrokenPlugin" not in loaded

    # Assert error logged for broken plugin
    assert any(
        "Failed to load plugin" in record.message
        or "Could not import" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_plugin_hot_discovery(tmp_path: Path) -> None:
    """Verify adding a new folder with a valid manifest is picked up on next discover() call."""
    strategies_dir = tmp_path / "hot_strategies"
    strategies_dir.mkdir()

    config = ConfigManager()
    container = DIContainer()
    loader = PluginLoader(config, container, strategies_dir=strategies_dir)

    # 1. Initial discovery returns empty
    loaded1 = await loader.discover()
    assert len(loaded1) == 0

    # 2. Dynamically add new valid plugin folder
    new_dir = strategies_dir / "dynamic_plugin"
    new_dir.mkdir()
    (new_dir / "strategy.yaml").write_text(
        """
name: "DynamicPlugin"
version: "0.1.0"
min_framework_version: "0.1.0"
entry_point: "quantflow.strategies._example.ExampleStrategy"
""",
        encoding="utf-8",
    )

    # 3. Next discover() call picks up the newly added plugin without restart
    loaded2 = await loader.discover()
    assert "DynamicPlugin" in loaded2
    assert container.has("strategy_DynamicPlugin")

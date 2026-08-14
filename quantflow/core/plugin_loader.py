"""Strategy plugin discovery and loader."""

import importlib
import inspect
from pathlib import Path
from typing import Any

from quantflow.config.manager import ConfigManager
from quantflow.core.di import DIContainer
from quantflow.core.interfaces import EventBus, Strategy
from quantflow.core.logging import get_logger
from quantflow.plugins.manifest import StrategyManifest, load_manifest


class PluginLoader:
    """Discovers, validates, instantiates, and registers strategy plugins into DIContainer."""

    def __init__(
        self,
        config: ConfigManager,
        container: DIContainer,
        strategies_dir: Path | str | None = None,
    ) -> None:
        self.config = config
        self.container = container
        self.logger = get_logger("plugin_loader")
        if strategies_dir is not None:
            self.strategies_dir = Path(strategies_dir)
        else:
            dir_str = config.get("strategies.directory", "quantflow/strategies")
            self.strategies_dir = Path(dir_str)

        self._loaded_plugins: dict[str, Strategy] = {}

    async def discover(self) -> dict[str, Strategy]:
        """Discover strategy plugins, load them, and register into DI container."""
        if not self.strategies_dir.exists():
            self.logger.warning(
                f"Strategies directory '{self.strategies_dir}' not found."
            )
            return dict(self._loaded_plugins)

        for strategy_dir in self.strategies_dir.iterdir():
            if not strategy_dir.is_dir() or strategy_dir.name.startswith((".", "__")):
                continue

            manifest_path = strategy_dir / "strategy.yaml"
            if not manifest_path.exists():
                manifest_path = strategy_dir / "strategy.yml"

            if not manifest_path.exists():
                self.logger.debug(
                    f"No manifest found in '{strategy_dir}', skipping."
                )
                continue

            try:
                manifest, instance = await self._load_plugin(
                    strategy_dir, manifest_path
                )
                name = manifest.name
                self.container.register_named_singleton(
                    f"strategy_{name}", instance
                )
                self._loaded_plugins[name] = instance
                self.logger.info(
                    f"Loaded strategy: {name} (version {manifest.version})"
                )
            except Exception as err:
                self.logger.error(
                    f"Failed to load plugin from '{strategy_dir}': {err}",
                    exc_info=True,
                )

        return dict(self._loaded_plugins)

    async def discover_and_load(self) -> dict[str, Strategy]:
        """Alias for discover()."""
        return await self.discover()

    async def _load_plugin(
        self, strategy_dir: Path, manifest_path: Path
    ) -> tuple[StrategyManifest, Strategy]:
        """Load a single plugin manifest and entrypoint."""
        manifest = load_manifest(manifest_path)
        entry_point = manifest.entry_point

        try:
            module_path, class_name = entry_point.rsplit(".", 1)
            module = importlib.import_module(module_path)
            strategy_class = getattr(module, class_name)
        except (ImportError, AttributeError, ValueError) as err:
            raise ImportError(
                f"Could not import entrypoint '{entry_point}': {err}"
            ) from err

        event_bus = (
            self.container.resolve(EventBus)
            if self.container.has(EventBus)
            else None
        )
        strategy_config: dict[str, Any] = self.config.get(
            f"strategies.{manifest.name}", {}
        )

        try:
            if event_bus is not None:
                try:
                    instance = strategy_class(
                        event_bus=event_bus, config=strategy_config
                    )
                except TypeError:
                    instance = strategy_class(event_bus=event_bus)
            else:
                try:
                    instance = strategy_class(config=strategy_config)
                except TypeError:
                    instance = strategy_class()
        except Exception as err:
            raise RuntimeError(
                f"Failed to instantiate strategy class '{class_name}': {err}"
            ) from err

        if not isinstance(instance, Strategy):
            # Also allow duck-typed strategies with get_name and on_event
            if not (
                hasattr(instance, "get_name") and hasattr(instance, "on_event")
            ):
                raise TypeError(
                    f"Loaded class '{class_name}' does not implement Strategy interface."
                )

        init_method = getattr(instance, "initialize", None)
        if callable(init_method):
            if inspect.iscoroutinefunction(init_method):
                await init_method(config=strategy_config)
            else:
                init_method(config=strategy_config)

        from typing import cast

        return manifest, cast(Strategy, instance)

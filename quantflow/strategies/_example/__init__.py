"""Example strategy plugin implementation."""

from typing import Any

from quantflow.common.events import Event
from quantflow.core.interfaces import EventBus, Strategy


class ExampleStrategy(Strategy):
    """No-op example strategy satisfying the Strategy interface."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.config = config or {}

    def get_name(self) -> str:
        """Return unique strategy name."""
        return "ExampleStrategy"

    async def on_event(self, event: Event) -> None:
        """Handle incoming events (no-op)."""
        pass

    async def initialize(self, config: dict[str, Any] | None = None) -> None:
        """Initialize strategy."""
        pass

    async def start(self) -> None:
        """Start strategy background operations."""
        pass

    async def stop(self) -> None:
        """Stop strategy operations."""
        pass

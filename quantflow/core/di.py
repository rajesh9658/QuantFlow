"""Lightweight Dependency Injection Container for interface resolution."""

from collections.abc import Callable
from typing import Any, TypeVar, overload

T = TypeVar("T")


class DIRegistrationError(KeyError):
    """Raised when requesting an unregistered interface from the DIContainer."""

    pass


class DIContainer:
    """Dependency Injection container resolving dependencies by interface type."""

    def __init__(self) -> None:
        self._registrations: dict[type[Any], Any] = {}
        self._singletons: dict[type[Any], bool] = {}
        self._instances: dict[type[Any], Any] = {}
        self._named_singletons: dict[str, Any] = {}

    @overload
    def register(
        self,
        interface: type[T],
        instance_or_factory: T | Callable[..., T],
        singleton: bool = True,
    ) -> None:
        ...

    @overload
    def register(
        self,
        interface: Any,
        instance_or_factory: Any,
        singleton: bool = True,
    ) -> None:
        ...

    def register(
        self,
        interface: Any,
        instance_or_factory: Any,
        singleton: bool = True,
    ) -> None:
        """Register an instance or factory callable for a given interface type."""
        self._registrations[interface] = instance_or_factory
        self._singletons[interface] = singleton
        # If passed an explicit instance that is not a callable class/function
        if not callable(instance_or_factory):
            self._instances[interface] = instance_or_factory

    def register_named_singleton(self, name: str, instance: Any) -> None:
        """Register a named singleton instance."""
        self._named_singletons[name] = instance

    def resolve_named(self, name: str) -> Any:
        """Resolve a named singleton instance by string key."""
        if name not in self._named_singletons:
            raise DIRegistrationError(f"Named singleton '{name}' not found.")
        return self._named_singletons[name]

    def get_all_strategies(self) -> dict[str, Any]:
        """Return all registered strategy instances (prefixed with strategy_)."""
        return {
            k: v for k, v in self._named_singletons.items() if k.startswith("strategy_")
        }

    @overload
    def resolve(self, interface: type[T]) -> T:
        ...

    @overload
    def resolve(self, interface: Any) -> Any:
        ...

    def resolve(self, interface: Any) -> Any:
        """Resolve an instance registered for the specified interface type.

        Raises:
            DIRegistrationError: If no registration exists for interface.
        """
        if interface in self._instances:
            return self._instances[interface]

        if interface not in self._registrations:
            name = getattr(interface, "__name__", str(interface))
            raise DIRegistrationError(
                f"No implementation registered for interface '{name}'."
            )

        target = self._registrations[interface]
        is_singleton = self._singletons.get(interface, True)

        if callable(target):
            try:
                # Try passing self if factory expects container
                instance = target(self)
            except TypeError:
                # Fall back to parameterless factory
                instance = target()
        else:
            instance = target

        if is_singleton:
            self._instances[interface] = instance

        return instance

    def has(self, interface: type[Any] | Any) -> bool:
        """Check if an interface is registered."""
        return (
            interface in self._registrations
            or interface in self._instances
            or (isinstance(interface, str) and interface in self._named_singletons)
        )

    def clear(self) -> None:
        """Clear all registered interfaces and instances."""
        self._registrations.clear()
        self._singletons.clear()
        self._instances.clear()
        self._named_singletons.clear()

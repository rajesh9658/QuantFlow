"""Tests for DIContainer registration and resolution."""

from abc import ABC, abstractmethod
import pytest

from quantflow.core.di import DIContainer, DIRegistrationError


class ServiceInterface(ABC):
    @abstractmethod
    def execute(self) -> str:
        pass


class ServiceImpl(ServiceInterface):
    def execute(self) -> str:
        return "success"


class UnregisteredInterface(ABC):
    pass


def test_di_container_resolves_registered_service() -> None:
    """Verify DI container registers and resolves service implementation."""
    container = DIContainer()
    service_instance = ServiceImpl()

    container.register(ServiceInterface, service_instance)

    assert container.has(ServiceInterface)
    resolved: ServiceInterface = container.resolve(ServiceInterface)
    assert resolved is service_instance
    assert resolved.execute() == "success"


def test_di_container_factory_registration() -> None:
    """Verify DI container supports factory registration."""
    container = DIContainer()
    container.register(ServiceInterface, lambda: ServiceImpl())

    resolved: ServiceInterface = container.resolve(ServiceInterface)
    assert isinstance(resolved, ServiceImpl)
    assert resolved.execute() == "success"


def test_di_container_raises_error_on_missing_registration() -> None:
    """Verify resolving an unregistered interface raises DIRegistrationError."""
    container = DIContainer()

    with pytest.raises(DIRegistrationError) as exc_info:
        container.resolve(UnregisteredInterface)

    assert "UnregisteredInterface" in str(exc_info.value)
    assert issubclass(DIRegistrationError, KeyError)

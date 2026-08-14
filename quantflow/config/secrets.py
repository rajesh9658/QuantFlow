"""Secret management abstractions and providers for QuantFlow."""

import os
from abc import ABC, abstractmethod


class SecretNotFoundError(KeyError):
    """Raised when a requested secret is not found."""

    pass


class SecretsProvider(ABC):
    """Abstract interface for secret resolution."""

    @abstractmethod
    def get_secret(self, key: str) -> str:
        """Retrieve a secret by key.

        Raises:
            SecretNotFoundError: If the secret cannot be found.
        """


class EnvSecretsProvider(SecretsProvider):
    """Environment variable-backed secrets provider."""

    def __init__(
        self,
        prefix: str = "",
        env_dict: dict[str, str] | None = None,
    ) -> None:
        self._prefix = prefix
        self._env_dict = env_dict

    def get_secret(self, key: str) -> str:
        """Retrieve a secret from environment variables or custom env dict."""
        lookup_key = f"{self._prefix}{key}"
        env = self._env_dict if self._env_dict is not None else os.environ
        val = env.get(lookup_key)
        if val is None or val == "":
            if self._prefix and key in env and env[key] != "":
                val = env[key]
            else:
                raise SecretNotFoundError(
                    f"Secret '{key}' (lookup: '{lookup_key}') was not found or empty."
                )
        return val

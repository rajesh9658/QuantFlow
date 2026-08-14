"""Layered configuration manager supporting defaults, YAML config files, and env overrides."""

import json
import os
from pathlib import Path
from typing import Any

import yaml

from quantflow.config.secrets import EnvSecretsProvider, SecretsProvider


def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Recursively update target dictionary with source dictionary."""
    for key, value in source.items():
        if isinstance(value, dict) and key in target and isinstance(target[key], dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
    return target


def _parse_env_value(val: str) -> Any:
    """Parse string env values to appropriate python types (int, float, bool, json)."""
    low = val.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    if (val.startswith("{") and val.endswith("}")) or (
        val.startswith("[") and val.endswith("]")
    ):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            pass
    return val


class ConfigManager:
    """Layered configuration manager.

    Precedence order (highest to lowest):
    1. Environment variables (QUANTFLOW_*)
    2. YAML configuration file
    3. Default values dictionary
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        defaults: dict[str, Any] | None = None,
        env_prefix: str = "QUANTFLOW_",
        secrets_provider: SecretsProvider | None = None,
        env_dict: dict[str, str] | None = None,
    ) -> None:
        self._env_prefix = env_prefix
        self._secrets_provider = (
            secrets_provider
            if secrets_provider is not None
            else EnvSecretsProvider(env_dict=env_dict)
        )
        self._config: dict[str, Any] = {}

        # 1. Load defaults
        if defaults:
            _deep_update(self._config, defaults)

        # 2. Load YAML config
        if config_path:
            path = Path(config_path)
            if path.exists() and path.is_file():
                with open(path, encoding="utf-8") as f:
                    yaml_data = yaml.safe_load(f)
                    if isinstance(yaml_data, dict):
                        _deep_update(self._config, yaml_data)

        # 3. Apply Environment Variable overrides
        env_source = env_dict if env_dict is not None else os.environ
        for env_key, env_val in env_source.items():
            if env_key.startswith(self._env_prefix):
                key_path = env_key[len(self._env_prefix) :].lower().split("__")
                parsed_val = _parse_env_value(env_val)
                curr = self._config
                for part in key_path[:-1]:
                    if part not in curr or not isinstance(curr[part], dict):
                        curr[part] = {}
                    curr = curr[part]
                curr[key_path[-1]] = parsed_val

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a configuration option, supporting dot notation for nested keys."""
        parts = key.split(".")
        curr: Any = self._config
        for part in parts:
            if isinstance(curr, dict) and part in curr:
                curr = curr[part]
            else:
                return default
        return curr

    def get_secret(self, key: str) -> str:
        """Delegate secret resolution to the configured SecretsProvider."""
        return self._secrets_provider.get_secret(key)

    def as_dict(self) -> dict[str, Any]:
        """Return a copy of the merged configuration dictionary."""
        res: dict[str, Any] = json.loads(json.dumps(self._config))
        return res

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is None and key not in self._config:
            raise KeyError(key)
        return val

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

"""Tests for ConfigManager and SecretsProvider."""

from pathlib import Path
import pytest

from quantflow.config.manager import ConfigManager
from quantflow.config.secrets import EnvSecretsProvider, SecretNotFoundError


def test_config_layering_precedence(tmp_path: Path) -> None:
    """Verify layering precedence: env overrides yaml overrides defaults."""
    # 1. Defaults
    defaults = {
        "log_level": "INFO",
        "database": {"host": "localhost", "port": 5432},
        "theme": "dark",
    }

    # 2. YAML file overrides defaults
    yaml_content = """
log_level: "WARNING"
database:
  host: "db.staging.internal"
"""
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    # 3. Env overrides YAML and defaults
    env_dict = {
        "QUANTFLOW_LOG_LEVEL": "DEBUG",
        "QUANTFLOW_DATABASE__PORT": "5433",
    }

    config = ConfigManager(
        config_path=config_file,
        defaults=defaults,
        env_dict=env_dict,
    )

    # Env override wins over yaml and defaults
    assert config.get("log_level") == "DEBUG"
    # Env override wins for nested port
    assert config.get("database.port") == 5433
    # YAML override wins over defaults when env is absent
    assert config.get("database.host") == "db.staging.internal"
    # Default persists when un-overridden
    assert config.get("theme") == "dark"
    # Containment check
    assert "log_level" in config
    assert "database.port" in config
    assert "non_existent_key" not in config


def test_missing_secret_raises_clear_error() -> None:
    """Verify missing secret raises SecretNotFoundError (a KeyError subclass)."""
    secrets_provider = EnvSecretsProvider(prefix="QUANTFLOW_SECRET_", env_dict={})

    with pytest.raises(SecretNotFoundError) as exc_info:
        secrets_provider.get_secret("API_KEY")

    assert "API_KEY" in str(exc_info.value)
    assert issubclass(SecretNotFoundError, KeyError)


def test_config_manager_get_secret() -> None:
    """Verify ConfigManager delegates secret resolution correctly."""
    env_dict = {"API_TOKEN": "secret_12345"}
    secrets_provider = EnvSecretsProvider(env_dict=env_dict)
    config = ConfigManager(secrets_provider=secrets_provider)

    assert config.get_secret("API_TOKEN") == "secret_12345"

    with pytest.raises(SecretNotFoundError):
        config.get_secret("NON_EXISTENT_SECRET")

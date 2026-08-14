"""Unit tests for plugin strategy manifest loader in quantflow/plugins/manifest.py."""

import pytest

from quantflow.plugins.manifest import (
    FRAMEWORK_VERSION,
    StrategyManifest,
    load_manifest,
)


def test_load_valid_manifest(tmp_path: pytest.TempPathFactory) -> None:
    """Test loading a valid strategy.yaml manifest file."""
    yaml_content = f"""
name: TrendFollower
version: 1.0.0
min_framework_version: {FRAMEWORK_VERSION}
entry_point: my_strategies.trend:TrendFollowerStrategy
description: A moving average trend following strategy
author: QuantTeam
"""
    manifest = load_manifest(yaml_content)
    assert isinstance(manifest, StrategyManifest)
    assert manifest.name == "TrendFollower"
    assert manifest.version == "1.0.0"
    assert manifest.min_framework_version == FRAMEWORK_VERSION
    assert manifest.entry_point == "my_strategies.trend:TrendFollowerStrategy"
    assert manifest.author == "QuantTeam"


def test_missing_required_field() -> None:
    """Test manifest loading fails when required fields are missing."""
    invalid_yaml = """
name: IncompleteStrategy
version: 1.0.0
# Missing min_framework_version and entry_point
description: Incomplete strategy declaration
"""
    with pytest.raises(ValueError, match="Manifest validation error"):
        load_manifest(invalid_yaml)


def test_version_mismatch_rejection() -> None:
    """Test manifest loading fails when min_framework_version > FRAMEWORK_VERSION."""

    future_version = "99.0.0"
    incompatible_yaml = f"""
name: FutureStrategy
version: 2.0.0
min_framework_version: {future_version}
entry_point: future.strategy:FutureStrategy
"""
    with pytest.raises(ValueError, match="exceeds active framework version"):
        load_manifest(incompatible_yaml)

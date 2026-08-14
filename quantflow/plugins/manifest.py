"""Plugin manifest parser and validator for strategy plugins."""

from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, Field, ValidationError

FRAMEWORK_VERSION: Final[str] = "0.1.0"


class StrategyManifest(BaseModel):
    """Strategy plugin manifest schema."""

    name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    min_framework_version: str = Field(..., min_length=1)
    entry_point: str = Field(..., min_length=1)
    description: str = ""
    author: str = ""


def _parse_semver(version_str: str) -> tuple[int, ...]:
    """Parse a semantic version string like '0.1.0' into a tuple of ints."""
    clean_ver = version_str.strip().lstrip("v")
    parts = clean_ver.split(".")
    res = []
    for part in parts:
        num_str = "".join(c for c in part if c.isdigit())
        if num_str:
            res.append(int(num_str))
        else:
            res.append(0)
    return tuple(res)


def load_manifest(source: str | Path) -> StrategyManifest:
    """Load and validate a strategy plugin manifest from YAML file path or raw string.

    Raises:
        ValueError: If file is missing, YAML is invalid, required fields missing,
                    or min_framework_version exceeds FRAMEWORK_VERSION.
    """
    yaml_content: str
    if isinstance(source, Path) or (
        isinstance(source, str)
        and not (
            "\n" in source or (":" in source and not source.endswith((".yaml", ".yml")))
        )
    ):
        path = Path(source)
        if path.is_file():
            yaml_content = path.read_text(encoding="utf-8")
        elif isinstance(source, str) and ("name:" in source or "version:" in source):
            yaml_content = source
        else:
            raise ValueError(f"Manifest file not found: {source}")
    else:
        yaml_content = str(source)

    try:
        data = yaml.safe_load(yaml_content)
    except Exception as err:
        raise ValueError(f"Failed to parse YAML content: {err}") from err

    if not isinstance(data, dict):
        raise ValueError(
            "Invalid manifest YAML: expected a top-level mapping/dictionary"
        )

    try:
        manifest = StrategyManifest.model_validate(data)
    except ValidationError as err:
        raise ValueError(f"Manifest validation error: {err}") from err

    # Check min_framework_version requirement
    req_ver = _parse_semver(manifest.min_framework_version)
    curr_ver = _parse_semver(FRAMEWORK_VERSION)

    if req_ver > curr_ver:
        req = manifest.min_framework_version
        raise ValueError(
            f"Strategy '{manifest.name}' requires min_framework_version '{req}', "
            f"which exceeds active framework version '{FRAMEWORK_VERSION}'."
        )

    return manifest

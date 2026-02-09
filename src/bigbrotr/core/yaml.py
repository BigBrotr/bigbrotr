"""YAML configuration loading for BigBrotr.

Provides safe YAML file loading using ``yaml.safe_load`` to prevent
arbitrary code execution from untrusted YAML content. Used by all
services to load their configuration files.

Example::

    from bigbrotr.core.yaml import load_yaml

    config = load_yaml("config/services/finder.yaml")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(config_path: str) -> dict[str, Any]:
    """Load and parse a YAML configuration file.

    Args:
        config_path: Path to the YAML file (absolute or relative).

    Returns:
        Parsed configuration as a nested dictionary. Returns an empty dict
        if the file exists but contains no data.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the file contains invalid YAML syntax.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

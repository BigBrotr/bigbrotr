"""YAML configuration loading utilities for BigBrotr.

This module provides safe YAML file loading with proper error handling.
It uses PyYAML's safe_load to prevent arbitrary code execution from
malicious YAML files.

The module is used by services to load their configuration from YAML files
located in the implementations directory (e.g., implementations/bigbrotr/yaml/).

Example:
    >>> from utils.yaml import load_yaml
    >>> config = load_yaml("/path/to/implementations/bigbrotr/yaml/services/finder.yaml")
    >>> print(config.get("discovery", {}).get("limit", 100))
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(config_path: str) -> dict[str, Any]:
    """Load and parse a YAML configuration file.

    Reads a YAML file from disk and returns its contents as a Python
    dictionary. Uses yaml.safe_load() to prevent arbitrary code execution
    from untrusted YAML content.

    Args:
        config_path: Absolute or relative path to the YAML configuration file.
            The path is resolved using pathlib.Path for cross-platform
            compatibility.

    Returns:
        dict[str, Any]: Parsed configuration as a nested dictionary structure.
            Returns an empty dict if the file exists but contains no data
            (empty file or only comments).

    Raises:
        FileNotFoundError: If the specified configuration file does not exist
            at the given path.
        yaml.YAMLError: If the file contains invalid YAML syntax.

    Example:
        >>> config = load_yaml("config/service.yaml")
        >>> database_host = config.get("database", {}).get("host", "localhost")
        >>> print(f"Connecting to {database_host}")
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    # Use safe_load to prevent arbitrary Python object instantiation
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

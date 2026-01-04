"""
Core utility functions for BigBrotr.

Provides shared utilities used across core components.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(config_path: str) -> dict[str, Any]:
    """
    Load a YAML configuration file.

    Args:
        config_path: Path to YAML configuration file

    Returns:
        Parsed configuration dictionary (empty dict if file is empty)

    Raises:
        FileNotFoundError: If config file does not exist
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

"""YAML configuration loading for BigBrotr.

Provides safe YAML file loading using ``yaml.safe_load`` to prevent
arbitrary code execution from untrusted YAML content. Used by
[Pool.from_yaml()][bigbrotr.core.pool.Pool.from_yaml],
[Brotr.from_yaml()][bigbrotr.core.brotr.Brotr.from_yaml], and
[BaseService.from_yaml()][bigbrotr.core.base_service.BaseService.from_yaml]
to load their configuration files.

Examples:
    ```python
    from bigbrotr.core.yaml import load_yaml

    config = load_yaml("config/services/finder.yaml")
    ```

See Also:
    [Pool.from_yaml()][bigbrotr.core.pool.Pool.from_yaml]: Pool factory
        that delegates to this function.
    [Brotr.from_yaml()][bigbrotr.core.brotr.Brotr.from_yaml]: Brotr factory
        that delegates to this function.
    [BaseService.from_yaml()][bigbrotr.core.base_service.BaseService.from_yaml]:
        Service factory that delegates to this function.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Typical Pydantic model constructed from the returned dictionary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(config_path: str) -> dict[str, Any]:
    """Load and parse a YAML configuration file.

    Uses ``yaml.safe_load`` which only supports standard YAML types
    (strings, numbers, lists, dicts) and prevents arbitrary Python
    object instantiation from YAML tags.

    Args:
        config_path: Path to the YAML file (absolute or relative).

    Returns:
        Parsed configuration as a nested dictionary. Returns an empty dict
        if the file exists but contains no data.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the file contains invalid YAML syntax.

    Warning:
        This function does not validate the structure of the returned
        dictionary. Callers are responsible for passing the result to a
        Pydantic model (e.g.
        [PoolConfig][bigbrotr.core.pool.PoolConfig],
        [BrotrConfig][bigbrotr.core.brotr.BrotrConfig],
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig])
        for schema validation.

    See Also:
        [Pool.from_yaml()][bigbrotr.core.pool.Pool.from_yaml]: Primary
            consumer for pool configuration.
        [Brotr.from_yaml()][bigbrotr.core.brotr.Brotr.from_yaml]: Primary
            consumer for database interface configuration.
        [BaseService.from_yaml()][bigbrotr.core.base_service.BaseService.from_yaml]:
            Primary consumer for service configuration.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

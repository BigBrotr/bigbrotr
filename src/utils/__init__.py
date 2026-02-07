"""BigBrotr utility package.

Re-exports commonly used utilities for convenient imports across the codebase:

- **Configuration**: ``load_yaml``, ``NetworkConfig``, ``KeysConfig``
- **Transport**: ``create_client`` (Nostr client factory)
- **DNS**: ``resolve_host``, ``ResolvedHost``
- **Network types**: ``ClearnetConfig``, ``TorConfig``, ``I2pConfig``, ``LokiConfig``

Example::

    from utils import load_yaml, create_client, NetworkConfig

    config = load_yaml("yaml/services/finder.yaml")
"""

from utils.dns import ResolvedHost, resolve_host
from utils.keys import KeysConfig, load_keys_from_env
from utils.network import (
    ClearnetConfig,
    I2pConfig,
    LokiConfig,
    NetworkConfig,
    NetworkType,
    NetworkTypeConfig,
    TorConfig,
)
from utils.transport import create_client
from utils.yaml import load_yaml


__all__ = [
    "ClearnetConfig",
    "I2pConfig",
    "KeysConfig",
    "LokiConfig",
    "NetworkConfig",
    "NetworkType",
    "NetworkTypeConfig",
    "ResolvedHost",
    "TorConfig",
    "create_client",
    "load_keys_from_env",
    "load_yaml",
    "resolve_host",
]

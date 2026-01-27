"""BigBrotr utility functions.

This module provides shared utility functions and configuration classes used
across the BigBrotr codebase. It re-exports commonly used utilities for
convenient imports.

Exported utilities:
    - BatchProgress: Dataclass for tracking batch processing progress
    - KeysConfig: Pydantic model for Nostr key configuration
    - load_keys_from_env: Load Nostr keys from environment variables
    - NetworkConfig: Unified network configuration for all services
    - ClearnetConfig, TorConfig, I2pConfig, LokiConfig: Per-network configs
    - NetworkTypeConfig: Type alias for any network-specific config
    - create_client: Factory for creating Nostr clients
    - load_yaml: Load YAML configuration files
    - parse_typed_dict: Type-safe parsing against TypedDict schemas

Example:
    >>> from utils import load_yaml, create_client, KeysConfig
    >>> config = load_yaml("/path/to/config.yaml")
    >>> client = create_client(keys=None, proxy_url=None)
"""

from utils.keys import KeysConfig, load_keys_from_env
from utils.network import (
    ClearnetConfig,
    I2pConfig,
    LokiConfig,
    NetworkConfig,
    NetworkTypeConfig,
    TorConfig,
)
from utils.parsing import parse_typed_dict
from utils.progress import BatchProgress
from utils.transport import create_client
from utils.yaml import load_yaml


__all__ = [
    "BatchProgress",
    "ClearnetConfig",
    "I2pConfig",
    "KeysConfig",
    "LokiConfig",
    "NetworkConfig",
    "NetworkTypeConfig",
    "TorConfig",
    "create_client",
    "load_keys_from_env",
    "load_yaml",
    "parse_typed_dict",
]

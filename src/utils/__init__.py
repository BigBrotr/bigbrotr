"""BigBrotr utility functions.

This module provides shared utility functions and configuration classes used
across the BigBrotr codebase. It re-exports commonly used utilities for
convenient imports.

Exported utilities:
    - BatchProgress: Dataclass for tracking batch processing progress
    - KeysConfig: Pydantic model for Nostr key configuration
    - load_keys_from_env: Load Nostr keys from environment variables
    - NetworkConfig: Unified network configuration for all services
    - NetworkTypeConfig: Settings for individual network types
    - create_client: Factory for creating Nostr clients
    - load_yaml: Load YAML configuration files
    - parse_typed_dict: Type-safe parsing against TypedDict schemas

Example:
    >>> from utils import load_yaml, create_client, KeysConfig
    >>> config = load_yaml("/path/to/config.yaml")
    >>> client = create_client(keys=None, proxy_url=None)
"""

from utils.keys import KeysConfig, load_keys_from_env
from utils.network import NetworkConfig, NetworkTypeConfig
from utils.parsing import parse_typed_dict
from utils.progress import BatchProgress
from utils.transport import create_client
from utils.yaml import load_yaml


__all__ = [
    "BatchProgress",
    "KeysConfig",
    "NetworkConfig",
    "NetworkTypeConfig",
    "create_client",
    "load_keys_from_env",
    "load_yaml",
    "parse_typed_dict",
]

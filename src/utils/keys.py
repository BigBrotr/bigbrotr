"""Key loading utilities for BigBrotr.

This module provides utilities for loading Nostr cryptographic keys from
environment variables. It supports both nsec1 (bech32) and hex format
private keys.

The module defines:
    - ENV_PRIVATE_KEY: Default environment variable name for private keys
    - load_keys_from_env: Function to load keys from environment
    - KeysConfig: Pydantic model for automatic key loading in service configs

Security Note:
    Private keys should never be stored in configuration files or source code.
    Always use environment variables or secure secret management systems.

Example:
    >>> import os
    >>> os.environ["PRIVATE_KEY"] = "nsec1..."  # pragma: allowlist secret
    >>> keys = load_keys_from_env("PRIVATE_KEY")
    >>> print(keys.public_key().to_bech32())
"""

from __future__ import annotations

import os
from typing import Any

from nostr_sdk import Keys
from pydantic import BaseModel, Field, model_validator


# Environment variable for private key (default name used by KeysConfig)
ENV_PRIVATE_KEY = "PRIVATE_KEY"  # pragma: allowlist secret


def load_keys_from_env(env_var: str) -> Keys:
    """Load Nostr keys from an environment variable.

    Parses a private key from the specified environment variable. The key
    can be in either nsec1 (bech32) or hex format. The function returns
    a Keys object containing both the private and derived public key.

    Args:
        env_var: Name of the environment variable containing the private key.
            Supports both nsec1 bech32 format (e.g., "nsec1abc...") and
            64-character hex format.

    Returns:
        Keys: A nostr_sdk Keys instance with the private key and derived
            public key ready for signing operations.

    Raises:
        ValueError: If the environment variable is not set or is empty.
        nostr_sdk.NostrError: If the key value is malformed or invalid.

    Example:
        >>> import os
        >>> os.environ["MY_KEY"] = "nsec1..."
        >>> keys = load_keys_from_env("MY_KEY")
        >>> print(f"Public key: {keys.public_key().to_hex()}")
    """
    value = os.getenv(env_var)

    if not value:
        raise ValueError(
            f"{env_var} environment variable is required. Generate one with: openssl rand -hex 32"
        )

    return Keys.parse(value)


class KeysConfig(BaseModel):
    """Pydantic configuration model for Nostr key management.

    This model automatically loads Nostr keys from the PRIVATE_KEY environment
    variable during validation. It is designed to be embedded in service
    configuration models that require authentication capabilities.

    Services using this config:
        - Validator: For NIP-42 authentication during relay testing
        - Monitor: For signing NIP-66 relay monitoring events
        - Synchronizer: For NIP-42 authentication when syncing events

    Attributes:
        keys: The nostr_sdk Keys instance loaded from environment.
            Contains both private and public keys for signing operations.

    Raises:
        ValueError: If PRIVATE_KEY environment variable is not set or empty.
        nostr_sdk.NostrError: If the key in PRIVATE_KEY is malformed.

    Example:
        >>> import os
        >>> os.environ["PRIVATE_KEY"] = "nsec1..."  # pragma: allowlist secret
        >>> config = KeysConfig()
        >>> print(config.keys.public_key().to_bech32())
    """

    model_config = {"arbitrary_types_allowed": True}

    keys: Keys = Field(
        description="Keys loaded from PRIVATE_KEY env (required)",
    )

    @model_validator(mode="before")
    @classmethod
    def _load_keys_from_env(cls, data: Any) -> Any:
        """Load keys from environment if not explicitly provided.

        This validator runs before field validation and automatically
        populates the 'keys' field from the PRIVATE_KEY environment
        variable when not provided in the input data.

        Args:
            data: Input data for model construction.

        Returns:
            Modified data dict with 'keys' field populated from environment.
        """
        if isinstance(data, dict) and "keys" not in data:
            data["keys"] = load_keys_from_env(ENV_PRIVATE_KEY)
        return data

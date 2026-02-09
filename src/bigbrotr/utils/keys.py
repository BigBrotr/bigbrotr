"""Nostr key management utilities for BigBrotr.

Provides functions and Pydantic models for loading Nostr cryptographic keys
from environment variables. Supports both nsec1 (bech32) and hex-encoded
private key formats.

Private keys must never be stored in configuration files or source code.
Always use environment variables or a secure secret management system.

Example::

    import os

    os.environ["PRIVATE_KEY"] = "nsec1..."  # pragma: allowlist secret
    keys = load_keys_from_env("PRIVATE_KEY")
    print(keys.public_key().to_bech32())
"""

from __future__ import annotations

import os
from typing import Any

from nostr_sdk import Keys
from pydantic import BaseModel, Field, model_validator


ENV_PRIVATE_KEY = "PRIVATE_KEY"  # pragma: allowlist secret  # Default env var name


def load_keys_from_env(env_var: str) -> Keys:
    """Load Nostr keys from an environment variable.

    Parses a private key (nsec1 bech32 or 64-char hex) and returns a Keys
    object containing both the private and derived public key.

    Args:
        env_var: Name of the environment variable containing the private key.

    Returns:
        A nostr_sdk Keys instance ready for signing operations.

    Raises:
        ValueError: If the environment variable is not set or is empty.
        nostr_sdk.NostrError: If the key value is malformed or invalid.
    """
    value = os.getenv(env_var)

    if not value:
        raise ValueError(
            f"{env_var} environment variable is required. Generate one with: openssl rand -hex 32"
        )

    return Keys.parse(value)


class KeysConfig(BaseModel):
    """Pydantic model that auto-loads Nostr keys from an environment variable.

    The ``keys`` field is populated automatically during validation from
    the environment variable named by ``keys_env``. Used by Validator,
    Monitor, and Synchronizer services.

    Attributes:
        keys_env: Environment variable name for the private key.
        keys: Loaded nostr_sdk Keys instance (private + derived public key).

    Raises:
        ValueError: If the environment variable is not set or empty.
        nostr_sdk.NostrError: If the key value is malformed.
    """

    model_config = {"arbitrary_types_allowed": True}

    keys_env: str = Field(
        default=ENV_PRIVATE_KEY,
        min_length=1,
        description="Environment variable name for private key",
    )
    keys: Keys = Field(description="Keys loaded from keys_env (required)")

    @model_validator(mode="before")
    @classmethod
    def _load_keys_from_env(cls, data: Any) -> Any:
        """Auto-populate the ``keys`` field from the environment variable."""
        if isinstance(data, dict) and "keys" not in data:
            env_var = data.get("keys_env", ENV_PRIVATE_KEY)
            data["keys"] = load_keys_from_env(env_var)
        return data

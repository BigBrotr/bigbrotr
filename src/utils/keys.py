"""Key loading utilities for BigBrotr."""

from __future__ import annotations

import os
from typing import Any

from nostr_sdk import Keys
from pydantic import BaseModel, Field, model_validator


# Environment variable for private key
ENV_PRIVATE_KEY = "PRIVATE_KEY"  # pragma: allowlist secret


def load_keys_from_env(env_var: str) -> Keys | None:
    """
    Load Nostr keys from environment variable.

    Args:
        env_var: Environment variable name containing the private key
                 (nsec1... bech32 or hex format)

    Returns:
        Keys instance or None if environment variable is not set

    Raises:
        Exception: If the key value is invalid

    Example:
        >>> keys = load_keys_from_env("PRIVATE_KEY")
        >>> if keys:
        ...     print(f"Loaded keys for: {keys.public_key().to_hex()}")
    """
    value = os.getenv(env_var)

    if not value:
        return None

    return Keys.parse(value)


class KeysConfig(BaseModel):
    """Nostr keys configuration for services requiring authentication.

    Used by Validator (NIP-42), Monitor (NIP-66 publishing), and Synchronizer (NIP-42).
    Keys are automatically loaded from the PRIVATE_KEY environment variable.
    """

    model_config = {"arbitrary_types_allowed": True}

    keys: Keys | None = Field(
        default=None,
        description="Keys loaded from PRIVATE_KEY env",
    )

    @model_validator(mode="before")
    @classmethod
    def _load_keys_from_env(cls, data: Any) -> Any:
        if isinstance(data, dict) and "keys" not in data:
            data["keys"] = load_keys_from_env(ENV_PRIVATE_KEY)
        return data

"""Key loading utilities for BigBrotr."""

import os

from nostr_sdk import Keys


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

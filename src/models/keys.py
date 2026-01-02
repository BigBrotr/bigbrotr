"""
Extended Nostr key management for BigBrotr.

Provides the Keys class for loading Nostr keypairs from hex strings
or environment variables, wrapping nostr_sdk.Keys with additional convenience methods.

Example:
    >>> keys = Keys.from_env("PRIVATE_KEY")
    >>> if keys:
    ...     pubkey = keys.public_key().to_hex()
"""

import os
from typing import Optional

from nostr_sdk import Keys as NostrKeys
from nostr_sdk import SecretKey


class Keys(NostrKeys):  # type: ignore[misc]
    """
    Extended Nostr keys with environment variable loading.

    Inherits from nostr_sdk.Keys and adds the from_env() factory method
    for loading keypairs from environment variables (common in containerized deployments).

    Example:
        >>> keys = Keys.from_env("PRIVATE_KEY")
        >>> if keys:
        ...     print(f"Loaded keys for: {keys.public_key().to_hex()}")
    """

    @classmethod
    def from_env(cls, env_var: str = "PRIVATE_KEY") -> Optional["Keys"]:
        """
        Load keys from environment variable.

        Args:
            env_var: Environment variable name (default: PRIVATE_KEY)

        Returns:
            Keys instance or None if not set

        Raises:
            ValueError: If key is invalid
        """
        key = os.getenv(env_var)

        if not key:
            return None

        try:
            sk = SecretKey.parse(key)
            return cls(sk)
        except Exception:
            # Sanitize error message to avoid exposing the key
            raise ValueError(f"Invalid {env_var}: failed to parse private key") from None

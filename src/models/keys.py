"""
Key utilities for BigBrotr.

Provides Keys class for Nostr key management.
"""

import os
from typing import Optional

from nostr_sdk import Keys as NostrKeys, SecretKey


class Keys(NostrKeys):
    """Extended Nostr keys with environment loading."""

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
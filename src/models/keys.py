"""
Nostr key management wrapper for BigBrotr.

Provides the Keys class that wraps nostr_sdk.Keys with environment variable loading.
Uses frozen dataclass with __getattr__ delegation to transparently proxy all NostrKeys methods.

Example:
    >>> keys = Keys.from_env("PRIVATE_KEY")
    >>> if keys:
    ...     pubkey = keys.public_key().to_hex()
"""

import os
from dataclasses import dataclass
from typing import Any, Self

from nostr_sdk import Keys as NostrKeys


@dataclass(frozen=True, slots=True)
class Keys:
    """
    Immutable Nostr keys wrapper with environment variable loading.

    Frozen dataclass that transparently proxies all NostrKeys methods via
    __getattr__ and adds from_env() for loading from environment variables.

    Example:
        >>> keys = Keys.from_env("PRIVATE_KEY")
        >>> if keys:
        ...     print(f"Loaded keys for: {keys.public_key().to_hex()}")
    """

    _inner: NostrKeys

    def __getattr__(self, name: str) -> Any:
        """Delegate all attribute access to the wrapped NostrKeys."""
        return getattr(self._inner, name)

    @classmethod
    def generate(cls) -> Self:
        """
        Generate new random keys.

        Returns:
            Keys instance with newly generated keypair

        Example:
            >>> keys = Keys.generate()
            >>> print(keys.public_key().to_bech32())  # npub1...
        """
        return cls(NostrKeys.generate())

    @classmethod
    def parse(cls, key: str) -> Self:
        """
        Parse keys from bech32 (nsec) or hex format.

        Args:
            key: Private key in nsec1... or hex format

        Returns:
            Keys instance

        Raises:
            Exception: If key format is invalid

        Example:
            >>> keys = Keys.parse("nsec1...")
            >>> keys = Keys.parse("hex-private-key")
        """
        return cls(NostrKeys.parse(key))

    @classmethod
    def from_mnemonic(cls, mnemonic: str, passphrase: str | None = None) -> Self:
        """
        Derive keys from BIP-39 mnemonic (NIP-06).

        Args:
            mnemonic: BIP-39 mnemonic phrase (12 or 24 words)
            passphrase: Optional passphrase for additional security

        Returns:
            Keys instance derived from mnemonic

        Raises:
            Exception: If mnemonic is invalid

        Example:
            >>> keys = Keys.from_mnemonic("abandon abandon ... about")
            >>> keys = Keys.from_mnemonic("abandon ...", passphrase="secret")
        """
        if passphrase:
            return cls(NostrKeys.from_mnemonic(mnemonic, passphrase))
        return cls(NostrKeys.from_mnemonic(mnemonic))

    @classmethod
    def from_env(cls, env_var: str) -> Self | None:
        """
        Load keys from environment variable.

        Args:
            env_var: Environment variable name containing the private key

        Returns:
            Keys instance or None if not set

        Raises:
            Exception: If key is invalid
        """
        value = os.getenv(env_var)

        if not value:
            return None

        return cls.parse(value)

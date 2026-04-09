"""Nostr key management utilities for BigBrotr.

Provides functions and Pydantic models for loading Nostr cryptographic keys
from service-specific environment variables. Supports both nsec1 (bech32)
and hex-encoded private key formats, and can fall back to generated
ephemeral keys when an environment variable is unset.

Warning:
    Private keys must **never** be stored in configuration files, source code,
    or logged to any output. Always use environment variables or a secure
    secret management system. The ``detect-secrets`` pre-commit hook guards
    against accidental key commits.

Note:
    Key loading happens during config validation via
    [KeysConfig][bigbrotr.utils.keys.KeysConfig]'s Pydantic model validator.
    When the configured environment variable is missing or blank,
    [KeysConfig][bigbrotr.utils.keys.KeysConfig] generates one ephemeral
    keypair at config creation time and the service reuses it for its
    whole lifecycle.

See Also:
    [bigbrotr.services.monitor.Monitor][bigbrotr.services.monitor.Monitor]:
        Primary consumer that signs NIP-66 kind 10166/30166 events.
    [bigbrotr.utils.protocol.broadcast_events][bigbrotr.utils.protocol.broadcast_events]:
        Uses keys for Nostr event broadcasting.
    [bigbrotr.nips.nip66.rtt.Nip66RttDependencies][bigbrotr.nips.nip66.rtt.Nip66RttDependencies]:
        RTT probes require keys for publishing test events.

Examples:
    ```python
    import os

    os.environ["NOSTR_PRIVATE_KEY_MONITOR"] = "nsec1..."  # pragma: allowlist secret
    keys = load_keys_from_env("NOSTR_PRIVATE_KEY_MONITOR")
    print(keys.public_key().to_bech32())
    ```
"""

from __future__ import annotations

import os
from typing import Any

from nostr_sdk import Keys
from pydantic import BaseModel, Field, model_validator


def load_keys_from_env(env_var: str) -> Keys | None:
    """Load Nostr keys from an environment variable if it is defined.

    Parses a private key (nsec1 bech32 or 64-char hex) and returns a ``Keys``
    object containing both the private and derived public key. Missing or blank
    environment variables resolve to ``None``.

    Args:
        env_var: Name of the environment variable containing the private key.

    Returns:
        A ``nostr_sdk.Keys`` instance ready for signing operations, or ``None``
        if the environment variable is unset or blank.

    Raises:
        nostr_sdk.NostrError: If the key value is malformed or invalid.

    Warning:
        The returned ``Keys`` object holds the private key in memory for the
        lifetime of the process. Ensure the calling service handles it
        appropriately and does not serialize or log it.

    See Also:
        [KeysConfig][bigbrotr.utils.keys.KeysConfig]: Pydantic model that
            wraps this function for declarative config loading.
    """
    value = os.getenv(env_var)

    if value is None or not value.strip():
        return None

    return Keys.parse(value)


class KeysConfig(BaseModel):
    """Pydantic model that auto-loads Nostr keys from an environment variable.

    The ``keys`` field is resolved automatically during validation from
    the environment variable named by ``keys_env`` when provided. If
    ``keys_env`` is omitted, or the selected variable is missing or blank,
    an ephemeral keypair is generated once. Used by
    [Monitor][bigbrotr.services.monitor.Monitor],
    [Synchronizer][bigbrotr.services.synchronizer.Synchronizer], and
    [Dvm][bigbrotr.services.dvm.Dvm] services.

    Attributes:
        keys_env: Optional environment variable name for the private key.
        keys: Final ``nostr_sdk.Keys`` instance used by the service,
            loaded from ``keys_env`` or generated ephemerally.

    Raises:
        nostr_sdk.NostrError: If the key value is malformed.

    Warning:
        The ``keys`` field contains a live private key. Do not serialize
        this model to logs, JSON, or any persistent storage. The
        ``arbitrary_types_allowed`` config is required because
        ``nostr_sdk.Keys`` is a Rust-backed FFI type.

    See Also:
        [load_keys_from_env][bigbrotr.utils.keys.load_keys_from_env]:
            Underlying function used by the model validator.
    """

    model_config = {"arbitrary_types_allowed": True}

    keys_env: str | None = Field(
        default=None,
        description="Environment variable name for private key",
    )
    keys: Keys = Field(
        default_factory=Keys.generate,
        description="Keys loaded from keys_env, or generated when unset/blank",
    )

    def __repr__(self) -> str:
        """Redact private key material and show whether keys are configured."""
        keys = getattr(self, "keys", None)
        if keys is None:
            return f"KeysConfig(keys_env={self.keys_env!r}, pubkey=None)"
        pubkey = keys.public_key().to_hex()
        return f"KeysConfig(keys_env={self.keys_env!r}, pubkey={pubkey!r})"

    def __str__(self) -> str:
        """Redact private key material — show only the public key."""
        return self.__repr__()

    @model_validator(mode="before")
    @classmethod
    def _load_keys_from_env(cls, data: Any) -> Any:
        """Resolve ``keys`` from ``keys_env`` when the caller did not provide them."""
        if not isinstance(data, dict):
            return data

        if data.get("keys") is not None:
            return data

        data = dict(data)
        data.pop("keys", None)

        env_var = data.get("keys_env")
        if not isinstance(env_var, str) or not env_var.strip():
            return data

        keys = load_keys_from_env(env_var)
        if keys is not None:
            data["keys"] = keys
        return data

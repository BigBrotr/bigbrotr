"""Nostr key management utilities for BigBrotr.

Provides functions and Pydantic models for loading Nostr cryptographic keys
from environment variables. Supports both nsec1 (bech32) and hex-encoded
private key formats.

Warning:
    Private keys must **never** be stored in configuration files, source code,
    or logged to any output. Always use environment variables or a secure
    secret management system. The ``detect-secrets`` pre-commit hook guards
    against accidental key commits.

Note:
    Key loading happens eagerly at config validation time via
    [KeysConfig][bigbrotr.utils.keys.KeysConfig]'s Pydantic model validator.
    This fail-fast design ensures missing or invalid keys are caught at
    service startup rather than at first use.

See Also:
    [bigbrotr.services.monitor.Monitor][bigbrotr.services.monitor.Monitor]:
        Primary consumer that signs NIP-66 kind 10166/30166 events.
    [bigbrotr.services.monitor_publisher][bigbrotr.services.monitor_publisher]:
        Uses keys for Nostr event broadcasting.
    [bigbrotr.nips.nip66.rtt.Nip66RttDependencies][bigbrotr.nips.nip66.rtt.Nip66RttDependencies]:
        RTT probes require keys for publishing test events.

Examples:
    ```python
    import os

    os.environ["PRIVATE_KEY"] = "nsec1..."  # pragma: allowlist secret
    keys = load_keys_from_env("PRIVATE_KEY")
    print(keys.public_key().to_bech32())
    ```
"""

from __future__ import annotations

import os
from typing import Any

from nostr_sdk import Keys
from pydantic import BaseModel, Field, model_validator


ENV_PRIVATE_KEY = "PRIVATE_KEY"  # pragma: allowlist secret  # Default env var name


def load_keys_from_env(env_var: str) -> Keys:
    """Load Nostr keys from an environment variable.

    Parses a private key (nsec1 bech32 or 64-char hex) and returns a ``Keys``
    object containing both the private and derived public key.

    Args:
        env_var: Name of the environment variable containing the private key.

    Returns:
        A ``nostr_sdk.Keys`` instance ready for signing operations.

    Raises:
        ValueError: If the environment variable is not set or is empty.
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

    if not value:
        raise ValueError(
            f"{env_var} environment variable is required. Generate one with: openssl rand -hex 32"
        )

    return Keys.parse(value)


class KeysConfig(BaseModel):
    """Pydantic model that auto-loads Nostr keys from an environment variable.

    The ``keys`` field is populated automatically during validation from
    the environment variable named by ``keys_env``. Used by
    [Validator][bigbrotr.services.validator.Validator],
    [Monitor][bigbrotr.services.monitor.Monitor], and
    [Synchronizer][bigbrotr.services.synchronizer.Synchronizer] services.

    Attributes:
        keys_env: Environment variable name for the private key.
        keys: Loaded ``nostr_sdk.Keys`` instance (private + derived public key).

    Raises:
        ValueError: If the environment variable is not set or empty.
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

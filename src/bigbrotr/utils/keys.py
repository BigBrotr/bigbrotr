"""Low-level Nostr key loading utilities for BigBrotr.

Provides the environment-variable loader used by shared service config to
resolve Nostr cryptographic keys. Supports both nsec1 (bech32) and
hex-encoded private key formats.

Warning:
    Private keys must **never** be stored in configuration files, source code,
    or logged to any output. Always use environment variables or a secure
    secret management system. The ``detect-secrets`` pre-commit hook guards
    against accidental key commits.

See Also:
    [bigbrotr.services.monitor.Monitor][bigbrotr.services.monitor.Monitor]:
        Primary consumer that signs NIP-66 kind 10166/30166 events.
    [bigbrotr.services.common.configs.KeysConfig][bigbrotr.services.common.configs.KeysConfig]:
        Shared service-key config that wraps this loader and adds the
        ephemeral-key fallback policy.
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

from nostr_sdk import Keys


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
    """
    value = os.getenv(env_var)

    if value is None or not value.strip():
        return None

    return Keys.parse(value)

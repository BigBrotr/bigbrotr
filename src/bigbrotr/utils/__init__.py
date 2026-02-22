"""DNS resolution, Nostr key management, and WebSocket/HTTP transport.

The utils layer sits in the middle of the diamond DAG, depending only on
[bigbrotr.models][bigbrotr.models]. It provides low-level network and
cryptographic utilities used by [bigbrotr.nips][bigbrotr.nips] and
[bigbrotr.services][bigbrotr.services].

Attributes:
    dns: Async DNS resolution of A, AAAA, and CNAME records via the system
        resolver. Used by NIP-66 DNS tests.
    keys: Nostr key pair loading from environment variables (nsec1 bech32 or
        hex format) with Pydantic validation. Required by Monitor for signing.
    protocol: High-level Nostr client operations -- relay connection, event
        broadcasting, relay validation, and event fetching. Built on top of
        WebSocket transport primitives.
    transport: WebSocket transport primitives with SSL fallback strategy.
        Clearnet tries verified SSL first, falls back to insecure if cert errors
        and ``allow_insecure=True``. Overlay networks (Tor/I2P/Lokinet) require
        ``proxy_url`` and always use insecure SSL context.

Note:
    The utils layer has **zero** imports from ``bigbrotr.core`` or
    ``bigbrotr.services``. This strict dependency boundary ensures the
    diamond DAG architecture is maintained.

See Also:
    [bigbrotr.nips][bigbrotr.nips]: Protocol-specific logic that builds on
        these utilities.
    [bigbrotr.models.relay.Relay][bigbrotr.models.relay.Relay]: The relay
        model consumed by transport and DNS utilities.
    [bigbrotr.models.constants.NetworkType][bigbrotr.models.constants.NetworkType]:
        Network classification enum used to select transport strategies.

Examples:
    ```python
    from bigbrotr.utils import create_client, KeysConfig
    ```
"""

from bigbrotr.utils.dns import ResolvedHost, resolve_host
from bigbrotr.utils.http import download_bounded_file, read_bounded_json
from bigbrotr.utils.keys import KeysConfig, load_keys_from_env
from bigbrotr.utils.parsing import models_from_db_params, models_from_dict
from bigbrotr.utils.protocol import (
    broadcast_events,
    connect_relay,
    create_client,
    fetch_relay_events,
    is_nostr_relay,
)


__all__ = [
    "KeysConfig",
    "ResolvedHost",
    "broadcast_events",
    "connect_relay",
    "create_client",
    "download_bounded_file",
    "fetch_relay_events",
    "is_nostr_relay",
    "load_keys_from_env",
    "models_from_db_params",
    "models_from_dict",
    "read_bounded_json",
    "resolve_host",
]

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
    transport: WebSocket/HTTP client factory with SSL fallback strategy.
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

from bigbrotr.models.constants import NetworkType
from bigbrotr.utils.dns import ResolvedHost, resolve_host
from bigbrotr.utils.http import read_bounded_json
from bigbrotr.utils.keys import KeysConfig, load_keys_from_env
from bigbrotr.utils.transport import create_client


__all__ = [
    "KeysConfig",
    "NetworkType",
    "ResolvedHost",
    "create_client",
    "load_keys_from_env",
    "read_bounded_json",
    "resolve_host",
]

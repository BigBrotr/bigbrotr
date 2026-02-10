"""DNS resolution, Nostr key management, and WebSocket/HTTP transport.

The utils layer sits in the middle of the diamond DAG, depending only on
`bigbrotr.models`. It provides low-level network and cryptographic utilities
used by `bigbrotr.nips` and `bigbrotr.services`.

Attributes:
    dns: Async DNS resolution of A, AAAA, and CNAME records via the system
        resolver. Used by NIP-66 DNS tests.
    keys: Nostr key pair loading from environment variables (nsec1 bech32 or
        hex format) with Pydantic validation. Required by Monitor for signing.
    transport: WebSocket/HTTP client factory with SSL fallback strategy.
        Clearnet tries verified SSL first, falls back to insecure if cert errors
        and `allow_insecure=True`. Overlay networks (Tor/I2P/Lokinet) require
        `proxy_url` and always use insecure SSL context.

Examples:
    ```python
    from bigbrotr.utils import create_client, KeysConfig
    ```
"""

from bigbrotr.models.constants import NetworkType
from bigbrotr.utils.dns import ResolvedHost, resolve_host
from bigbrotr.utils.keys import KeysConfig, load_keys_from_env
from bigbrotr.utils.transport import create_client


__all__ = [
    "KeysConfig",
    "NetworkType",
    "ResolvedHost",
    "create_client",
    "load_keys_from_env",
    "resolve_host",
]

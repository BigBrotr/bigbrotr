"""Low-level DNS, HTTP, streaming, and Nostr transport helpers.

The utils layer sits in the middle of the diamond DAG, depending only on
[bigbrotr.models][bigbrotr.models]. It provides low-level network and
cryptographic utilities used by [bigbrotr.nips][bigbrotr.nips] and
[bigbrotr.services][bigbrotr.services].

Attributes:
    dns: Async A/AAAA hostname resolution via the system resolver. Used by
        NIP-66 geo/net flows and other low-level IP-discovery helpers.
    http: Bounded HTTP read/download helpers used by NIP fetchers and support
        tooling.
    keys: Low-level Nostr key loading from environment variables (nsec1 bech32
        or hex format). Higher layers may wrap this loader with deployment- or
        service-specific key policy.
    protocol: High-level public facade for relay connection, event
        broadcasting, relay validation, client-session management, and
        normalized connect/publish result helpers.
    protocol_*: Internal seams that split client construction, connection
        fallback, publication, sessions, validation, and manager logic behind
        the public ``protocol`` facade.
    streaming: Bounded event-stream traversal helpers used by archive flows.
    transport: WebSocket transport primitives with SSL fallback strategy.
        Clearnet tries verified SSL first, falls back to insecure if cert errors
        and ``allow_insecure=True``. Overlay networks (Tor/I2P/Lokinet) still
        require ``proxy_url``, but their TLS policy depends on the higher-level
        helper using these transport primitives rather than always forcing the
        custom insecure transport.

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
    from bigbrotr.utils.protocol import create_client
    from nostr_sdk import Keys

    keys = Keys.generate()
    client = await create_client(keys=keys)
    ```
"""

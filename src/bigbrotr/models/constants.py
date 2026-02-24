"""Shared constants for the models layer.

Defines enumerations and other constants that are used across multiple
model modules. Placing them here avoids circular dependencies between
the models and utils layers.

See Also:
    [bigbrotr.models.relay][]: Uses [NetworkType][bigbrotr.models.constants.NetworkType]
        to classify relay URLs during construction.
    [bigbrotr.nips.nip66][]: Relies on network type for overlay-specific health checks.
    [bigbrotr.models.service_state][]: Uses [ServiceName][bigbrotr.models.constants.ServiceName]
        and imports [EventKind][bigbrotr.models.constants.EventKind] for service state types.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class NetworkType(StrEnum):
    """Network type enum for relay classification.

    Each relay URL is classified into exactly one network type during
    [Relay][bigbrotr.models.relay.Relay] construction. The scheme is then
    enforced per network: clearnet requires ``wss://`` (TLS), while overlay
    networks use ``ws://`` (encryption handled by the overlay).

    Attributes:
        CLEARNET: Public internet relay using ``wss://`` (TLS required).
        TOR: Tor hidden service identified by a ``.onion`` hostname.
        I2P: I2P eepsite identified by a ``.i2p`` hostname.
        LOKI: Lokinet service identified by a ``.loki`` hostname.
        LOCAL: Private or reserved IP address (rejected during validation).
        UNKNOWN: Hostname that could not be classified (rejected during validation).

    Examples:
        Network detection is performed by
        ``Relay._detect_network()``:

        ```python
        Relay("wss://relay.damus.io").network   # NetworkType.CLEARNET
        Relay("ws://abc123.onion").network       # NetworkType.TOR
        Relay("ws://relay.i2p").network          # NetworkType.I2P
        ```

    Warning:
        ``LOCAL`` and ``UNKNOWN`` network types cause [Relay][bigbrotr.models.relay.Relay]
        construction to raise ``ValueError``. They exist for internal detection logic
        and are never exposed on a successfully constructed instance.

    See Also:
        [Relay][bigbrotr.models.relay.Relay]: Performs network detection and scheme enforcement.
        [RelayDbParams][bigbrotr.models.relay.RelayDbParams]: Stores the network type as a string
            for database persistence.
    """

    CLEARNET = "clearnet"
    TOR = "tor"
    I2P = "i2p"
    LOKI = "loki"
    LOCAL = "local"
    UNKNOWN = "unknown"


class ServiceName(StrEnum):
    """Canonical service identifiers used in logging, metrics, and persistence.

    Each member corresponds to one of the five pipeline services. The string
    values are used as the ``service_name`` column in the ``service_state``
    table and as the ``service`` label in Prometheus metrics.

    Attributes:
        SEEDER: One-shot bootstrapping service
            ([Seeder][bigbrotr.services.seeder.Seeder]).
        FINDER: Continuous relay URL discovery service
            ([Finder][bigbrotr.services.finder.Finder]).
        VALIDATOR: WebSocket-based Nostr protocol validation service
            ([Validator][bigbrotr.services.validator.Validator]).
        MONITOR: NIP-11 / NIP-66 health monitoring service
            ([Monitor][bigbrotr.services.monitor.Monitor]).
        SYNCHRONIZER: Cursor-based event collection service
            ([Synchronizer][bigbrotr.services.synchronizer.Synchronizer]).
        REFRESHER: Periodic materialized view refresh service
            ([Refresher][bigbrotr.services.refresher.Refresher]).

    See Also:
        [BaseService][bigbrotr.core.base_service.BaseService]: Abstract
            base class that uses ``SERVICE_NAME`` for logging context.
        [queries][bigbrotr.services.common.queries]: SQL functions that
            filter ``service_state`` rows by service name.
    """

    SEEDER = "seeder"
    FINDER = "finder"
    VALIDATOR = "validator"
    MONITOR = "monitor"
    SYNCHRONIZER = "synchronizer"
    REFRESHER = "refresher"


class EventKind(IntEnum):
    """Well-known Nostr event kinds used across services.

    Each member corresponds to a NIP-defined event kind that BigBrotr
    processes or publishes.

    Attributes:
        SET_METADATA: Kind 0 -- user profile metadata (NIP-01).
        RECOMMEND_RELAY: Kind 2 -- legacy relay recommendation (NIP-01, deprecated).
        CONTACTS: Kind 3 -- contact list with relay hints (NIP-02).
        RELAY_LIST: Kind 10002 -- NIP-65 relay list metadata.
        NIP66_TEST: Kind 22456 -- ephemeral NIP-66 relay test event.
        MONITOR_ANNOUNCEMENT: Kind 10166 -- NIP-66 monitor announcement
            (replaceable, published by the
            [Monitor][bigbrotr.services.monitor.Monitor] service).
        RELAY_DISCOVERY: Kind 30166 -- NIP-66 relay discovery event
            (parameterized replaceable, published by the
            [Monitor][bigbrotr.services.monitor.Monitor] service).

    See Also:
        [Event][bigbrotr.models.event.Event]: The event wrapper that carries
            these kinds.
        ``EVENT_KIND_MAX``: Maximum valid event kind value (65535).
    """

    SET_METADATA = 0
    RECOMMEND_RELAY = 2
    CONTACTS = 3
    RELAY_LIST = 10_002
    NIP66_TEST = 22_456
    MONITOR_ANNOUNCEMENT = 10_166
    RELAY_DISCOVERY = 30_166


EVENT_KIND_MAX = 65_535

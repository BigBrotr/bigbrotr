"""Shared constants for the models layer.

Defines enumerations and other constants that are used across multiple
model modules. Placing them here avoids circular dependencies between
the models and utils layers.

See Also:
    [bigbrotr.models.relay][]: Uses [NetworkType][bigbrotr.models.constants.NetworkType]
        to classify relay URLs during construction.
    [bigbrotr.nips.nip66][]: Relies on network type for overlay-specific health checks.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


DEFAULT_TIMEOUT: Final[float] = 10.0


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

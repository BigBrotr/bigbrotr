"""Shared constants for the models layer.

Defines enumerations and other constants that are used across multiple
model modules. Placing them here avoids circular dependencies between
the models and utils layers.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


DEFAULT_TIMEOUT: Final[float] = 10.0


class NetworkType(StrEnum):
    """Network type enum for relay classification.

    Values: CLEARNET (wss://), TOR (.onion), I2P (.i2p), LOKI (.loki),
    LOCAL (private/rejected), UNKNOWN (invalid/rejected).
    """

    CLEARNET = "clearnet"
    TOR = "tor"
    I2P = "i2p"
    LOKI = "loki"
    LOCAL = "local"
    UNKNOWN = "unknown"

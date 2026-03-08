"""Synchronizer service configuration models.

See Also:
    [Synchronizer][bigbrotr.services.synchronizer.Synchronizer]: The service
        class that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval`` and ``log_level`` fields.
"""

from __future__ import annotations

import json
import time
from typing import Any

from nostr_sdk import Filter
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.models.constants import NetworkType
from bigbrotr.services.common.configs import NetworksConfig
from bigbrotr.utils.keys import KeysConfig


def _parse_filter(raw: Any, index: int) -> Filter:
    """Parse a single NIP-01 filter dict into a nostr-sdk ``Filter``.

    Accepts any dict with NIP-01 REQ filter keys (``ids``, ``authors``,
    ``kinds``, ``#<letter>``, ``since``, ``until``, ``limit``).
    Temporal fields (``since``, ``until``, ``limit``) are accepted but
    ignored at runtime — the sync algorithm manages those.

    Raises:
        TypeError: If the value is not a dict.
        ValueError: If ``Filter.from_json`` rejects the content
            (e.g. invalid hex in ``authors``).
    """
    if isinstance(raw, Filter):
        return raw
    if not isinstance(raw, dict):
        raise TypeError(f"filters[{index}]: expected dict, got {type(raw).__name__}")
    try:
        return Filter.from_json(json.dumps(raw))
    except Exception as e:
        raise ValueError(f"filters[{index}]: {e}") from e


class TimeoutsConfig(BaseModel):
    """Sync timeout limits: per-relay bounds and optional phase-level cap.

    The ``relay_*`` fields control the maximum wall-clock time for syncing
    a single relay (enforced via ``asyncio.wait_for``).  The per-request
    WebSocket timeout comes from
    [NetworksConfig][bigbrotr.services.common.configs.NetworksConfig].

    ``max_duration`` caps the entire sync phase: once exceeded, remaining
    relays are skipped.  ``None`` (the default) means unlimited.

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Parent config that embeds this model.
    """

    relay_clearnet: float = Field(
        default=1800.0, ge=60.0, le=14_400.0, description="Max time per clearnet relay sync"
    )
    relay_tor: float = Field(
        default=3600.0, ge=60.0, le=14_400.0, description="Max time per Tor relay sync"
    )
    relay_i2p: float = Field(
        default=3600.0, ge=60.0, le=14_400.0, description="Max time per I2P relay sync"
    )
    relay_loki: float = Field(
        default=3600.0, ge=60.0, le=14_400.0, description="Max time per Loki relay sync"
    )
    max_duration: float | None = Field(
        default=None,
        ge=60.0,
        le=86_400.0,
        description="Maximum seconds for the entire sync phase (None = unlimited)",
    )

    @model_validator(mode="after")
    def _validate_max_duration_covers_relay_timeouts(self) -> TimeoutsConfig:
        """Ensure max_duration is at least as long as the shortest relay timeout."""
        if self.max_duration is None:
            return self
        min_relay = min(self.relay_clearnet, self.relay_tor, self.relay_i2p, self.relay_loki)
        if self.max_duration < min_relay:
            raise ValueError(
                f"max_duration ({self.max_duration}) must be >= the shortest "
                f"relay timeout ({min_relay})"
            )
        return self

    def get_relay_timeout(self, network: NetworkType) -> float:
        """Get the maximum sync duration for a relay on the given network."""
        if network == NetworkType.TOR:
            return self.relay_tor
        if network == NetworkType.I2P:
            return self.relay_i2p
        if network == NetworkType.LOKI:
            return self.relay_loki
        return self.relay_clearnet


class SynchronizerConfig(BaseServiceConfig):
    """Synchronizer service configuration.

    Sync parameters follow NIP-01 REQ semantics:

    - ``filters`` — NIP-01 filter dicts, converted to ``nostr_sdk.Filter``
      at load time for fail-fast validation.
    - ``since`` — default start timestamp for relays without a cursor.
    - ``until`` — upper bound; ``None`` (default) means ``now()``.
    - ``limit`` — max events per relay request (REQ limit).
    - ``end_lag`` — seconds subtracted from ``until`` to compute the
      actual sync end time: ``(until or now()) - end_lag``.

    See Also:
        [Synchronizer][bigbrotr.services.synchronizer.Synchronizer]: The
            service class that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval``, ``max_consecutive_failures``, and ``metrics`` fields.
        [NetworksConfig][bigbrotr.services.common.configs.NetworksConfig]:
            Per-network timeout and proxy settings.
        [KeysConfig][bigbrotr.utils.keys.KeysConfig]: Nostr key management
            for NIP-42 authentication during event fetching.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    networks: NetworksConfig = Field(
        default_factory=NetworksConfig, description="Per-network connection settings"
    )
    keys: KeysConfig = Field(
        default_factory=lambda: KeysConfig.model_validate({}),
        description="Nostr key configuration for NIP-42 authentication",
    )
    filters: list[Filter] = Field(
        default_factory=lambda: [Filter()],
        description="NIP-01 filter dicts for event subscription",
    )
    since: int = Field(default=0, ge=0, description="Default start timestamp (0 = epoch)")
    until: int | None = Field(
        default=None,
        ge=0,
        description="Upper bound timestamp (None = now())",
    )
    limit: int = Field(
        default=500, ge=1, le=5000, description="Max events per relay request (REQ limit)"
    )
    end_lag: int = Field(
        default=86_400,
        ge=0,
        le=604_800,
        description="Seconds subtracted from until: end_time = (until or now()) - end_lag",
    )
    timeouts: TimeoutsConfig = Field(
        default_factory=TimeoutsConfig, description="Per-network and phase timeout limits"
    )
    flush_interval: int = Field(default=50, ge=1, description="Flush cursor updates every N relays")

    @field_validator("filters", mode="before")
    @classmethod
    def parse_filters(cls, v: Any) -> list[Filter]:
        """Convert raw NIP-01 filter dicts to ``nostr_sdk.Filter`` objects."""
        if not isinstance(v, list):
            raise TypeError(f"filters: expected list, got {type(v).__name__}")
        return [_parse_filter(raw, i) for i, raw in enumerate(v)]

    def get_end_time(self) -> int:
        """Compute the sync end timestamp: ``(until or now()) - end_lag``."""
        base = self.until if self.until is not None else int(time.time())
        return base - self.end_lag

    @model_validator(mode="after")
    def _validate_end_time_after_since(self) -> SynchronizerConfig:
        """Ensure ``get_end_time() >= since``."""
        end = self.get_end_time()
        if end < self.since:
            raise ValueError(f"get_end_time() = {end} must be >= since ({self.since})")
        return self

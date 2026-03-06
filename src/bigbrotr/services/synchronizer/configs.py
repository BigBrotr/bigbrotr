"""Synchronizer service configuration models.

See Also:
    [Synchronizer][bigbrotr.services.synchronizer.Synchronizer]: The service
        class that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval`` and ``log_level`` fields.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.models.constants import EVENT_KIND_MAX, NetworkType
from bigbrotr.services.common.configs import NetworksConfig
from bigbrotr.utils.keys import KeysConfig


_HEX_STRING_LENGTH = 64


def _validate_hex_list(v: list[str] | None) -> list[str] | None:
    """Validate a list of 64-character hex strings (event IDs or pubkeys)."""
    if v is None:
        return v
    for hex_str in v:
        if len(hex_str) != _HEX_STRING_LENGTH:
            raise ValueError(
                f"Invalid hex string length: {len(hex_str)} (expected {_HEX_STRING_LENGTH})"
            )
        try:
            bytes.fromhex(hex_str)
        except ValueError as e:
            raise ValueError(f"Invalid hex string: {hex_str}") from e
    return v


class FilterConfig(BaseModel):
    """NIP-01 REQ filter configuration (minus since/until/limit).

    Supports ``ids``, ``kinds``, ``authors``, and single-letter tag filters
    per the NIP-01 specification.  Time range and limit are managed by the
    sync algorithm, not by this config.

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Parent config that embeds a list of these.
    """

    ids: list[str] | None = Field(default=None, description="Event IDs to fetch (None = all)")
    kinds: list[int] | None = Field(default=None, description="Event kinds to sync (None = all)")
    authors: list[str] | None = Field(default=None, description="Authors to sync (None = all)")
    tags: dict[str, list[str]] | None = Field(default=None, description="Tag filters (None = all)")

    @field_validator("kinds", mode="after")
    @classmethod
    def validate_kinds(cls, v: list[int] | None) -> list[int] | None:
        """Validate that all event kinds are within the valid range (0-65535)."""
        if v is None:
            return v
        for kind in v:
            if not 0 <= kind <= EVENT_KIND_MAX:
                raise ValueError(f"Event kind {kind} out of valid range (0-{EVENT_KIND_MAX})")
        return v

    @field_validator("ids", "authors", mode="after")
    @classmethod
    def validate_hex_strings(cls, v: list[str] | None) -> list[str] | None:
        """Validate that all entries are valid 64-character hex strings."""
        return _validate_hex_list(v)

    @field_validator("tags", mode="after")
    @classmethod
    def validate_tags(cls, v: dict[str, list[str]] | None) -> dict[str, list[str]] | None:
        """Validate tag filter keys per NIP-01: single English letter (a-zA-Z)."""
        if v is None:
            return v
        for key, values in v.items():
            if len(key) != 1 or not key.isascii() or not key.isalpha():
                raise ValueError(
                    f"Invalid tag key '{key}': must be a single letter a-zA-Z (NIP-01)"
                )
            if not values:
                raise ValueError(f"Tag '{key}' has empty values list")
        return v


class TimeRangeConfig(BaseModel):
    """Time range configuration controlling the sync window boundaries.

    The sync start time is determined by the per-relay cursor plus one
    second (to avoid re-fetching the last event). Relays without a cursor
    start from ``default_start``. The ``end_lag_seconds`` parameter
    controls how far back from ``now()`` the sync window extends.

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Parent config that embeds this model.
    """

    default_start: int = Field(default=0, ge=0, description="Default start timestamp (0 = epoch)")
    end_lag_seconds: int = Field(
        default=86_400,
        ge=3_600,
        le=604_800,
        description="Lag from now for sync upper bound: end_time = now - end_lag_seconds",
    )


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

    networks: NetworksConfig = Field(default_factory=NetworksConfig)
    keys: KeysConfig = Field(default_factory=lambda: KeysConfig.model_validate({}))
    filters: list[FilterConfig] = Field(default_factory=lambda: [FilterConfig()])
    time_range: TimeRangeConfig = Field(default_factory=TimeRangeConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    cursor_flush_interval: int = Field(
        default=50, ge=1, description="Flush cursor updates every N relays"
    )
    fetch_limit: int = Field(
        default=500, ge=1, le=5000, description="Max events per relay request (REQ limit)"
    )

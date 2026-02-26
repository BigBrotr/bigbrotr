"""Synchronizer service configuration models.

See Also:
    [Synchronizer][bigbrotr.services.synchronizer.Synchronizer]: The service
        class that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval`` and ``log_level`` fields.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.models.constants import EVENT_KIND_MAX, NetworkType
from bigbrotr.services.common.configs import NetworksConfig
from bigbrotr.utils.keys import KeysConfig


_HEX_STRING_LENGTH = 64


class FilterConfig(BaseModel):
    """Nostr event filter configuration for sync subscriptions.

    See Also:
        ``_create_filter``:
            Converts this config into a nostr-sdk ``Filter`` object.
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Parent config that embeds this model.
    """

    ids: list[str] | None = Field(default=None, description="Event IDs to sync (None = all)")
    kinds: list[int] | None = Field(default=None, description="Event kinds to sync (None = all)")
    authors: list[str] | None = Field(default=None, description="Authors to sync (None = all)")
    tags: dict[str, list[str]] | None = Field(default=None, description="Tag filters (None = all)")
    limit: int = Field(default=500, ge=1, le=5000, description="Events per request")

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


class TimeRangeConfig(BaseModel):
    """Time range configuration controlling the sync window boundaries.

    Note:
        When ``use_relay_state`` is ``True`` (the default), the sync
        start time is determined by the per-relay cursor plus one second
        (to avoid re-fetching the last event). When ``False``, all relays
        start from ``default_start``. The ``lookback_seconds`` parameter
        controls how far back from ``now()`` the sync window extends.

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Parent config that embeds this model.
        [get_all_cursor_values][bigbrotr.services.common.queries.get_all_cursor_values]:
            Fetches the per-relay cursor values used when
            ``use_relay_state`` is enabled.
    """

    default_start: int = Field(default=0, ge=0, description="Default start timestamp (0 = epoch)")
    use_relay_state: bool = Field(
        default=True, description="Use per-relay state for start timestamp"
    )
    lookback_seconds: int = Field(
        default=86_400,
        ge=3_600,
        le=604_800,
        description="Lookback window in seconds (default: 86400 = 24 hours)",
    )


class TimeoutsConfig(BaseModel):
    """Per-relay sync timeout limits by network type.

    These are the maximum total times allowed for syncing a single relay.
    The per-request WebSocket timeout comes from
    [NetworksConfig][bigbrotr.services.common.configs.NetworksConfig].

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

    def get_relay_timeout(self, network: NetworkType) -> float:
        """Get the maximum sync duration for a relay on the given network."""
        if network == NetworkType.TOR:
            return self.relay_tor
        if network == NetworkType.I2P:
            return self.relay_i2p
        if network == NetworkType.LOKI:
            return self.relay_loki
        return self.relay_clearnet


class ConcurrencyConfig(BaseModel):
    """Concurrency settings for parallel relay connections.

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Parent config that embeds this model.
    """

    cursor_flush_interval: int = Field(
        default=50, ge=1, description="Flush cursor updates every N relays"
    )


class SourceConfig(BaseModel):
    """Configuration for selecting which relays to sync from.

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Parent config that embeds this model.
        [fetch_all_relays][bigbrotr.services.common.queries.fetch_all_relays]:
            Query used when ``from_database`` is ``True``.
    """

    from_database: bool = Field(default=True, description="Fetch relays from database")


class RelayOverrideTimeouts(BaseModel):
    """Per-relay timeout overrides (None means use the network default)."""

    request: float | None = None
    relay: float | None = None


class RelayOverride(BaseModel):
    """Per-relay configuration overrides (e.g., for high-traffic relays)."""

    url: str
    timeouts: RelayOverrideTimeouts = Field(default_factory=RelayOverrideTimeouts)


class SynchronizerConfig(BaseServiceConfig):
    """Synchronizer service configuration.

    See Also:
        [Synchronizer][bigbrotr.services.synchronizer.Synchronizer]: The
            service class that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval`` and ``log_level`` fields.
        [NetworksConfig][bigbrotr.services.common.configs.NetworksConfig]:
            Per-network timeout and proxy settings.
        [KeysConfig][bigbrotr.utils.keys.KeysConfig]: Nostr key management
            for NIP-42 authentication during event fetching.
    """

    networks: NetworksConfig = Field(default_factory=NetworksConfig)
    keys: KeysConfig = Field(default_factory=lambda: KeysConfig.model_validate({}))
    filter: FilterConfig = Field(default_factory=FilterConfig)
    time_range: TimeRangeConfig = Field(default_factory=TimeRangeConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    source: SourceConfig = Field(default_factory=SourceConfig)
    overrides: list[RelayOverride] = Field(default_factory=list)

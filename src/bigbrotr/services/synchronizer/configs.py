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
from bigbrotr.services.common.configs import KeysConfig, NetworksConfig


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
    """Sync timeout limits: idle progress check and phase-level cap.

    ``idle`` controls the progress-based idle timeout per relay: if
    ``stream_events`` yields no events for this many seconds the relay
    is abandoned and the semaphore slot freed.  The timer resets on
    every yielded event, so a relay that produces events slowly but
    steadily is never killed.

    ``max_duration`` caps the entire sync phase: once exceeded,
    remaining relays are skipped.

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Parent config that embeds this model.
    """

    idle: float = Field(
        default=300.0,
        ge=10.0,
        le=3600.0,
        description="Abandon relay if no events received for this many seconds",
    )
    max_duration: float = Field(
        default=14_400.0,
        ge=60.0,
        le=86_400.0,
        description="Maximum seconds for the entire sync phase",
    )


class ProcessingConfig(BaseModel):
    """Sync processing parameters following NIP-01 REQ semantics.

    Attributes:
        filters: NIP-01 filter dicts, converted to ``nostr_sdk.Filter``
            at load time for fail-fast validation.
        since: Default start timestamp for relays without a cursor.
        until: Upper bound; ``None`` (default) means ``now()``.
        limit: Max events per relay request (REQ limit).
        end_lag: Seconds subtracted from ``until`` to compute the
            actual sync end time: ``(until or now()) - end_lag``.
        allow_insecure: Fall back to insecure transport on SSL failure.

    See Also:
        [SynchronizerConfig][bigbrotr.services.synchronizer.SynchronizerConfig]:
            Parent config that embeds this model.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

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
        default=500, ge=10, le=5000, description="Max events per relay request (REQ limit)"
    )
    end_lag: int = Field(
        default=86_400,
        ge=0,
        le=604_800,
        description="Seconds subtracted from until: end_time = (until or now()) - end_lag",
    )
    batch_size: int = Field(
        default=1000,
        ge=100,
        le=10_000,
        description="Events to buffer before flushing to the database",
    )
    allow_insecure: bool = Field(
        default=False,
        description="Fall back to insecure transport on SSL certificate failure",
    )
    max_event_size: int | None = Field(
        default=None,
        ge=1024,
        description="Maximum event JSON size in bytes (None = no limit)",
    )

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
    def _validate_end_time_after_since(self) -> ProcessingConfig:
        """Ensure ``get_end_time() >= since``."""
        end = self.get_end_time()
        if end < self.since:
            raise ValueError(f"get_end_time() = {end} must be >= since ({self.since})")
        return self


class SynchronizerConfig(BaseServiceConfig):
    """Synchronizer service configuration.

    See Also:
        [Synchronizer][bigbrotr.services.synchronizer.Synchronizer]: The
            service class that consumes this configuration.
        [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
            Base class providing ``interval``, ``max_consecutive_failures``, and ``metrics`` fields.
        [NetworksConfig][bigbrotr.services.common.configs.NetworksConfig]:
            Per-network timeout and proxy settings.
        [KeysConfig][bigbrotr.services.common.configs.KeysConfig]: Nostr key management
            for NIP-42 authentication during event fetching.
    """

    networks: NetworksConfig = Field(
        default_factory=NetworksConfig, description="Per-network connection settings"
    )
    keys: KeysConfig = Field(
        default_factory=lambda: KeysConfig(keys_env="NOSTR_PRIVATE_KEY_SYNCHRONIZER"),
        description="Nostr key configuration for NIP-42 authentication",
    )
    processing: ProcessingConfig = Field(
        default_factory=ProcessingConfig, description="Sync processing parameters"
    )
    timeouts: TimeoutsConfig = Field(
        default_factory=TimeoutsConfig, description="Per-network and phase timeout limits"
    )

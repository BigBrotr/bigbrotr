"""DVM service configuration models.

See Also:
    [Dvm][bigbrotr.services.dvm.Dvm]: The service class that consumes
        these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval``, ``max_consecutive_failures``,
        and ``metrics`` fields.
    [KeysConfig][bigbrotr.utils.keys.KeysConfig]: Mixin providing
        Nostr key management fields.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.models import Relay
from bigbrotr.services.common.configs import TableConfig  # noqa: TC001 (Pydantic runtime)
from bigbrotr.utils.keys import KeysConfig


class DvmConfig(BaseServiceConfig, KeysConfig):
    """Configuration for the DVM service.

    Inherits key management from
    [KeysConfig][bigbrotr.utils.keys.KeysConfig] for Nostr signing.

    Attributes:
        relays: Relay URLs to listen on and publish to.
        kind: NIP-90 request event kind (result = kind + 1000).
        max_page_size: Hard ceiling on query limit.
        tables: Per-table policies (enable/disable, pricing).
        announce: Whether to publish a NIP-89 handler announcement at startup.
        fetch_timeout: Timeout in seconds for relay event fetching.
    """

    relays: list[str] = Field(min_length=1)
    kind: int = Field(default=5050, ge=5000, le=5999)

    @field_validator("relays")
    @classmethod
    def validate_relay_urls(cls, v: list[str]) -> list[str]:
        """Validate that all relay URLs are valid WebSocket URLs."""
        for url in v:
            try:
                Relay(url)
            except (ValueError, TypeError) as e:
                raise ValueError(f"Invalid relay URL '{url}': {e}") from e
        return v

    max_page_size: int = Field(default=1000, ge=1, le=10000)
    tables: dict[str, TableConfig] = Field(default_factory=dict)
    announce: bool = Field(default=True)
    fetch_timeout: float = Field(default=30.0, ge=1.0, le=300.0)

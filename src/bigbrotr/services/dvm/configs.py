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

from typing import Annotated

from pydantic import BeforeValidator, Field, model_validator

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.models import Relay
from bigbrotr.services.common.configs import TableConfig  # noqa: TC001 (Pydantic runtime)
from bigbrotr.utils.keys import KeysConfig
from bigbrotr.utils.parsing import parse_relay_url, safe_parse


class DvmConfig(BaseServiceConfig, KeysConfig):
    """Configuration for the DVM service.

    Inherits key management from
    [KeysConfig][bigbrotr.utils.keys.KeysConfig] for Nostr signing.

    Attributes:
        relays: Relay URLs to listen on and publish to.
        kind: NIP-90 request event kind (result = kind + 1000).
        default_page_size: Default ``limit`` when not specified.
        max_page_size: Hard ceiling on query limit.
        tables: Per-table policies (enable/disable, pricing).
        announce: Whether to publish a NIP-89 handler announcement at startup.
        fetch_timeout: Timeout in seconds for relay event fetching.
    """

    name: str = Field(
        default="BigBrotr DVM",
        min_length=1,
        description="NIP-89 handler display name",
    )
    about: str = Field(
        default="Read-only access to BigBrotr relay monitoring data",
        min_length=1,
        description="NIP-89 handler description",
    )
    d_tag: str = Field(
        default="bigbrotr-dvm",
        min_length=1,
        description="NIP-89 unique handler identifier",
    )
    relays: Annotated[
        list[Relay],
        BeforeValidator(lambda v: safe_parse(v, parse_relay_url)),
    ] = Field(
        default_factory=lambda: [
            Relay("wss://relay.mostr.pub"),
            Relay("wss://relay.damus.io"),
            Relay("wss://nos.lol"),
            Relay("wss://relay.primal.net"),
        ],
        min_length=1,
        description="Relay URLs to listen on and publish to",
    )
    kind: int = Field(
        default=5050,
        ge=5000,
        le=5999,
        description="NIP-90 request event kind (result = kind + 1000)",
    )

    default_page_size: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Default query limit when not specified",
    )
    max_page_size: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Hard ceiling on query limit",
    )
    tables: dict[str, TableConfig] = Field(
        default_factory=dict,
        description="Per-table access and pricing policies",
    )
    announce: bool = Field(
        default=True,
        description="Publish NIP-89 handler announcement at startup",
    )
    fetch_timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Timeout for relay event fetching in seconds",
    )
    allow_insecure: bool = Field(
        default=False,
        description="Fall back to insecure transport on SSL certificate failure",
    )

    @model_validator(mode="after")
    def _validate_page_sizes(self) -> DvmConfig:
        """Ensure default_page_size does not exceed max_page_size."""
        if self.default_page_size > self.max_page_size:
            msg = (
                f"default_page_size ({self.default_page_size}) "
                f"must not exceed max_page_size ({self.max_page_size})"
            )
            raise ValueError(msg)
        return self

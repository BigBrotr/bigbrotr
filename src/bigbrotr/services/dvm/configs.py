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

from typing import Annotated, Any

from pydantic import AliasChoices, BeforeValidator, Field, model_validator

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.models import Relay
from bigbrotr.services.common.configs import TableConfig  # noqa: TC001 (Pydantic runtime)
from bigbrotr.services.common.read_models import read_models_for_surface
from bigbrotr.utils.keys import KeysConfig
from bigbrotr.utils.parsing import parse_relay_url, safe_parse


class DvmConfig(BaseServiceConfig):
    """Configuration for the DVM service.

    Embeds key management via
    [KeysConfig][bigbrotr.utils.keys.KeysConfig] for Nostr signing.

    Attributes:
        relays: Relay URLs to listen on and publish to.
        kind: NIP-90 request event kind (result = kind + 1000).
        default_page_size: Default ``limit`` when not specified.
        max_page_size: Hard ceiling on query limit.
        tables: Backward-compatible alias for ``read_models``.
        read_models: Per-read-model policies (enable/disable, pricing).
        announce: Whether to publish a NIP-89 handler announcement at startup.
        fetch_timeout: Timeout in seconds for relay event fetching.
    """

    keys: KeysConfig = Field(
        default_factory=lambda: KeysConfig(keys_env="NOSTR_PRIVATE_KEY_DVM"),
        description="Nostr key configuration for the DVM identity",
    )

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
        validation_alias=AliasChoices("read_models", "tables"),
        description="Per-read-model access and pricing policies",
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

    @model_validator(mode="before")
    @classmethod
    def _reject_duplicate_read_model_keys(cls, data: Any) -> Any:
        if isinstance(data, dict) and "tables" in data and "read_models" in data:
            raise ValueError("Specify only one of tables or read_models")
        return data

    @model_validator(mode="after")
    def _validate_public_tables(self) -> DvmConfig:
        allowed_tables = set(read_models_for_surface("dvm"))
        invalid_tables = sorted(set(self.tables) - allowed_tables)
        if invalid_tables:
            invalid = ", ".join(invalid_tables)
            allowed = ", ".join(sorted(allowed_tables))
            raise ValueError(
                "read_models contains non-public DVM read models: "
                f"{invalid}. Allowed read models: {allowed}"
            )
        return self

    @property
    def read_models(self) -> dict[str, TableConfig]:
        """Canonical access policy mapping for public DVM read models."""
        return self.tables

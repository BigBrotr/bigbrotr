"""DVM service configuration models.

See Also:
    [Dvm][bigbrotr.services.dvm.Dvm]: The service class that consumes
        these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval``, ``max_consecutive_failures``,
        and ``metrics`` fields.
    [NostrKeysConfig][bigbrotr.services.common.configs.NostrKeysConfig]:
        Shared Nostr key configuration.
"""

from __future__ import annotations

from collections.abc import Sequence as SequenceABC
from typing import Annotated, Any, ClassVar, cast

from pydantic import BeforeValidator, ConfigDict, Field, ValidationInfo, field_validator

from bigbrotr.models import Relay
from bigbrotr.services.common.configs import (
    NostrKeysConfig,
    PublicReadAdapterConfig,
    parse_relay_list_fail_soft,
)


def _normalize_required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name}: expected string, got {type(value).__name__}")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _require_number(value: Any, field_name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name}: expected number, got {type(value).__name__}")
    return cast("int | float", value)


def _require_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name}: expected integer, got {type(value).__name__}")
    return cast("int", value)


class DvmConfig(PublicReadAdapterConfig):
    """Configuration for the DVM service.

    Embeds key management via
    [NostrKeysConfig][bigbrotr.services.common.configs.NostrKeysConfig] for Nostr signing.

    Attributes:
        relays: Relay URLs to listen on and publish to.
        kind: NIP-90 request event kind (result = kind + 1000).
        default_page_size: Default ``limit`` when not specified.
        max_page_size: Hard ceiling on query limit.
        read_models: Adapter-local protocol exposure policy with enable/price
            controls per public readable resource.
        announce: Whether to publish a NIP-89 handler announcement at startup.
        fetch_timeout: Timeout in seconds for relay subscription setup and replay startup.
    """

    READ_SURFACE: ClassVar[str] = "dvm"
    model_config = ConfigDict(extra="forbid")

    keys: NostrKeysConfig = Field(
        default_factory=lambda: NostrKeysConfig(keys_env="NOSTR_PRIVATE_KEY_DVM"),
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
        BeforeValidator(parse_relay_list_fail_soft),
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

    announce: bool = Field(
        default=True,
        description="Publish NIP-89 handler announcement at startup",
    )
    fetch_timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Timeout for relay subscription setup and replay startup in seconds",
    )
    allow_insecure: bool = Field(
        default=False,
        description="Fall back to insecure transport on SSL certificate failure",
    )

    @field_validator("relays", mode="before")
    @classmethod
    def _require_string_relay_entries(cls, value: Any, info: ValidationInfo) -> Any:
        field_name = info.field_name or "value"
        if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, SequenceABC):
            return value
        for index, item in enumerate(value):
            if not isinstance(item, (str, Relay)):
                raise ValueError(
                    f"{field_name}[{index}]: expected string or Relay, got {type(item).__name__}"
                )
        return value

    @field_validator("announce", "allow_insecure", mode="before")
    @classmethod
    def _require_boolean_flags(cls, value: Any, info: ValidationInfo) -> bool:
        field_name = info.field_name or "value"
        if not isinstance(value, bool):
            raise ValueError(f"{field_name}: expected bool, got {type(value).__name__}")
        return value

    @field_validator("name", "about", "d_tag", mode="before")
    @classmethod
    def _normalize_announcement_text_fields(cls, value: Any, info: ValidationInfo) -> str:
        field_name = info.field_name or "value"
        return _normalize_required_text(value, field_name)

    @field_validator("kind", mode="before")
    @classmethod
    def _require_integer_kind(cls, value: Any, info: ValidationInfo) -> int:
        field_name = info.field_name or "value"
        return _require_int(value, field_name)

    @field_validator("fetch_timeout", mode="before")
    @classmethod
    def _require_numeric_fetch_timeout(cls, value: Any, info: ValidationInfo) -> int | float:
        field_name = info.field_name or "value"
        return _require_number(value, field_name)

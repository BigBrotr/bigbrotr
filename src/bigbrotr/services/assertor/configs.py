"""Assertor service configuration models.

See Also:
    [Assertor][bigbrotr.services.assertor.Assertor]: The service class
        that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval``, ``max_consecutive_failures``,
        and ``metrics`` fields.
    [NostrKeysConfig][bigbrotr.services.common.configs.NostrKeysConfig]:
        Shared Nostr key configuration.
"""

from __future__ import annotations

import re
from collections.abc import Mapping as MappingABC
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationInfo, field_validator

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.models import Relay
from bigbrotr.models._validation import normalize_json_data
from bigbrotr.models.constants import EventKind
from bigbrotr.services.common.configs import NostrKeysConfig, parse_relay_list_fail_soft


_SUPPORTED_KINDS = frozenset(
    {
        EventKind.NIP85_USER_ASSERTION,
        EventKind.NIP85_EVENT_ASSERTION,
        EventKind.NIP85_ADDRESSABLE_ASSERTION,
        EventKind.NIP85_IDENTIFIER_ASSERTION,
    }
)
_ALGORITHM_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_DEFAULT_ALGORITHM_ID = "global-pagerank"
_RESERVED_PROFILE_EXTRA_KEYS = frozenset(
    {"name", "about", "picture", "nip05", "website", "banner", "lud16"}
)


def _reject_bool_alias(value: Any, field_name: str, expected_type: str) -> Any:
    """Reject bool aliases before Pydantic coerces them into numeric budgets."""
    if isinstance(value, bool):
        raise ValueError(f"{field_name}: expected {expected_type}, got bool")
    return value


def _require_bool(value: Any, field_name: str) -> bool:
    """Require a real bool instead of allowing truthy/falsy aliases."""
    if not isinstance(value, bool):
        raise ValueError(f"{field_name}: expected bool, got {type(value).__name__}")
    return value


def _normalize_profile_extra_fields(value: Any) -> dict[str, object]:
    """Normalize provider-profile extras to the same JSON contract used by the Kind 0 builder."""
    if value is None:
        return {}
    if not isinstance(value, MappingABC):
        raise ValueError("extra_fields must be a mapping")

    normalized: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError("extra_fields keys must be strings")
        canonical_key = key.strip()
        if not canonical_key or item is None:
            continue
        if canonical_key in _RESERVED_PROFILE_EXTRA_KEYS:
            raise ValueError(
                f"extra_fields must not contain reserved profile field {canonical_key!r}"
            )
        if canonical_key in normalized:
            raise ValueError("extra_fields contains duplicate normalized keys")
        try:
            normalized[canonical_key] = normalize_json_data(
                item,
                f"extra_fields[{canonical_key!r}]",
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
    return normalized


def _normalize_required_profile_text(value: Any, field_name: str) -> str:
    """Trim required provider-profile text fields and reject blank payloads."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name}: expected string, got {type(value).__name__}")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _normalize_optional_profile_text(value: Any, field_name: str) -> str | None:
    """Trim optional provider-profile text fields and collapse blank payloads to ``None``."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name}: expected string, got {type(value).__name__}")
    normalized = value.strip()
    return normalized or None


class ProviderProfileKind0Content(BaseModel):
    """Kind 0 metadata content for the optional NIP-85 provider profile."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        default="BigBrotr Trusted Assertions",
        min_length=1,
        description="Display name for the assertion provider profile",
    )
    about: str = Field(
        default="NIP-85 trusted assertion provider",
        min_length=1,
        description="Human-readable description of the provider and its algorithm",
    )
    website: str = Field(
        default="https://bigbrotr.com",
        min_length=1,
        description="Website URL for the provider profile",
    )
    picture: str | None = Field(default=None, description="Profile picture URL")
    nip05: str | None = Field(default=None, description="NIP-05 identifier")
    banner: str | None = Field(default=None, description="Banner image URL")
    lud16: str | None = Field(default=None, description="Lightning address (LNURL)")
    extra_fields: dict[str, object] = Field(
        default_factory=dict,
        description="Additional JSON metadata to merge into the Kind 0 content",
    )

    @field_validator("extra_fields", mode="before")
    @classmethod
    def extra_fields_valid(cls, value: Any) -> dict[str, object]:
        return _normalize_profile_extra_fields(value)

    @field_validator("name", "about", "website", mode="before")
    @classmethod
    def required_text_fields_valid(cls, value: Any, info: ValidationInfo) -> str:
        return _normalize_required_profile_text(value, str(info.field_name))

    @field_validator("picture", "nip05", "banner", "lud16", mode="before")
    @classmethod
    def optional_text_fields_valid(cls, value: Any, info: ValidationInfo) -> str | None:
        return _normalize_optional_profile_text(value, str(info.field_name))


class ProviderProfileConfig(BaseModel):
    """Optional Kind 0 metadata publishing for the NIP-85 service key."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description="Enable Kind 0 provider profile publishing for the service key",
    )
    kind0_content: ProviderProfileKind0Content = Field(
        default_factory=ProviderProfileKind0Content,
        description="Kind 0 metadata content for the provider profile",
    )

    @field_validator("enabled", mode="before")
    @classmethod
    def enabled_is_bool(cls, value: Any, info: ValidationInfo) -> bool:
        return _require_bool(value, str(info.field_name))


class TrustedProviderListConfig(BaseModel):
    """Optional Kind 10040 trusted-provider list publishing for the service key."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=False,
        description="Enable Kind 10040 trusted-provider list publishing for the service key",
    )
    relay_hint: str | None = Field(
        default=None,
        description=(
            "Canonical relay hint to advertise in Kind 10040 declarations; "
            "defaults to the first publishing relay when omitted"
        ),
    )
    tag_names: list[str] = Field(
        default_factory=lambda: ["rank"],
        min_length=1,
        description=(
            "Assertion tag names to declare for each enabled assertion kind in "
            "the Kind 10040 provider list"
        ),
    )
    content: str = Field(
        default="",
        description="Optional event content for Kind 10040 publishing",
    )

    @field_validator("tag_names", mode="before")
    @classmethod
    def tag_names_are_strings(cls, value: Any, info: ValidationInfo) -> Any:
        if not isinstance(value, list | tuple):
            return value
        if any(not isinstance(tag, str) for tag in value):
            raise ValueError(f"{info.field_name}: expected strings, got mixed types")
        return value

    @field_validator("tag_names")
    @classmethod
    def tag_names_valid(cls, v: list[str]) -> list[str]:
        normalized = [tag.strip().lower() for tag in v]
        if any(not tag for tag in normalized):
            raise ValueError("tag_names must not contain blank values")
        if any(":" in tag for tag in normalized):
            raise ValueError("tag_names must not contain ':'")
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate trusted-provider tag names are not allowed")
        return normalized

    @field_validator("relay_hint", mode="before")
    @classmethod
    def relay_hint_is_string(cls, value: Any, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{info.field_name}: expected string, got {type(value).__name__}")
        return value

    @field_validator("content", mode="before")
    @classmethod
    def content_is_string(cls, value: Any, info: ValidationInfo) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{info.field_name}: expected string, got {type(value).__name__}")
        return value

    @field_validator("relay_hint")
    @classmethod
    def relay_hint_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return Relay.parse(value).url
        except ValueError as exc:
            raise ValueError("relay_hint must be a valid relay URL") from exc

    @field_validator("enabled", mode="before")
    @classmethod
    def enabled_is_bool(cls, value: Any, info: ValidationInfo) -> bool:
        return _require_bool(value, str(info.field_name))


class AssertorSelectionConfig(BaseModel):
    """Subject selection and per-kind assertion scope."""

    model_config = ConfigDict(extra="forbid")

    kinds: list[int] = Field(
        default_factory=lambda: [30382, 30383, 30384, 30385],
        min_length=1,
        description=(
            "NIP-85 assertion kinds to publish "
            "(30382=user, 30383=event, 30384=addressable, 30385=identifier)"
        ),
    )
    batch_size: int = Field(
        default=500,
        ge=1,
        le=50000,
        description="Maximum subjects to process per cycle",
    )
    min_events: int = Field(
        default=1,
        ge=0,
        description="Minimum event count for a pubkey to qualify for user assertion",
    )
    top_topics: int = Field(
        default=5,
        ge=0,
        le=50,
        description="Number of topic tags to include per user assertion",
    )

    @field_validator("batch_size", "min_events", "top_topics", mode="before")
    @classmethod
    def reject_boolean_numerics(cls, value: Any, info: ValidationInfo) -> Any:
        return _reject_bool_alias(value, str(info.field_name), "integer")

    @field_validator("kinds", mode="before")
    @classmethod
    def kinds_must_be_integers(cls, value: Any) -> Any:
        if isinstance(value, list | tuple):
            items = list(value)
            if any(isinstance(item, bool) or not isinstance(item, int) for item in items):
                raise ValueError("kinds must contain only integers")
            return items
        return value

    @field_validator("kinds")
    @classmethod
    def kinds_supported(cls, v: list[int]) -> list[int]:
        if len(v) != len(set(v)):
            raise ValueError("duplicate assertion kinds are not allowed")
        unsupported = set(v) - _SUPPORTED_KINDS
        if unsupported:
            raise ValueError(
                f"unsupported assertion kinds: {sorted(unsupported)}; "
                f"supported: {sorted(_SUPPORTED_KINDS)}"
            )
        return v


class AssertorPublishingConfig(BaseModel):
    """Relay publishing settings for assertion events."""

    model_config = ConfigDict(extra="forbid")

    relays: Annotated[
        list[Relay],
        BeforeValidator(parse_relay_list_fail_soft),
    ] = Field(
        default_factory=lambda: [
            Relay("wss://relay.damus.io"),
            Relay("wss://nos.lol"),
            Relay("wss://relay.primal.net"),
        ],
        min_length=1,
        description="Relay URLs to publish assertions to",
    )
    allow_insecure: bool = Field(
        default=False,
        description="Allow insecure SSL connections to relays",
    )

    @field_validator("allow_insecure", mode="before")
    @classmethod
    def allow_insecure_is_bool(cls, value: Any, info: ValidationInfo) -> bool:
        return _require_bool(value, str(info.field_name))


class AssertorCleanupConfig(BaseModel):
    """Checkpoint cleanup behavior for assertor state."""

    model_config = ConfigDict(extra="forbid")

    remove_stale_checkpoints: bool = Field(
        default=True,
        description="Delete stale or non-canonical checkpoints after each cycle",
    )

    @field_validator("remove_stale_checkpoints", mode="before")
    @classmethod
    def remove_stale_checkpoints_is_bool(cls, value: Any, info: ValidationInfo) -> bool:
        return _require_bool(value, str(info.field_name))


class AssertorConfig(BaseServiceConfig):
    """Configuration for the Assertor service.

    Embeds key management via
    [NostrKeysConfig][bigbrotr.services.common.configs.NostrKeysConfig] for Nostr signing.

    Attributes:
        algorithm_id: Stable identifier of the ranking/assertion algorithm.
        keys: Nostr key configuration for the assertor identity.
        selection: Subject selection and per-kind assertion scope.
        publishing: Relay publishing settings for assertion events.
        cleanup: Checkpoint cleanup behavior.
        provider_profile: Optional Kind 0 profile metadata for the service key.
        trusted_provider_list: Optional Kind 10040 trusted-provider list
            publishing settings for the service key.
    """

    model_config = ConfigDict(extra="forbid")

    algorithm_id: str = Field(
        default=_DEFAULT_ALGORITHM_ID,
        min_length=1,
        max_length=128,
        description="Stable identifier for the assertion algorithm/service key namespace",
    )
    keys: NostrKeysConfig = Field(
        default_factory=lambda: NostrKeysConfig(keys_env="NOSTR_PRIVATE_KEY_ASSERTOR"),
        description="Nostr key configuration for the assertor identity",
    )
    selection: AssertorSelectionConfig = Field(
        default_factory=AssertorSelectionConfig,
        description="Subject selection and per-kind assertion scope",
    )
    publishing: AssertorPublishingConfig = Field(
        default_factory=AssertorPublishingConfig,
        description="Relay publishing settings for assertion events",
    )
    cleanup: AssertorCleanupConfig = Field(
        default_factory=AssertorCleanupConfig,
        description="Checkpoint cleanup behavior",
    )

    @field_validator("algorithm_id", mode="before")
    @classmethod
    def require_string_algorithm_id(cls, value: Any, info: ValidationInfo) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{info.field_name}: expected str, got {type(value).__name__}")
        return value

    @field_validator("algorithm_id")
    @classmethod
    def algorithm_id_valid(cls, v: str) -> str:
        if not _ALGORITHM_ID_PATTERN.fullmatch(v):
            raise ValueError(
                "algorithm_id must match [a-z0-9]+(?:[._-][a-z0-9]+)* "
                "(lowercase letters, digits, '.', '_' and '-')"
            )
        return v

    interval: float = Field(
        default=3600.0,
        ge=60.0,
        description="Target seconds between assertion cycles",
    )

    provider_profile: ProviderProfileConfig = Field(
        default_factory=ProviderProfileConfig,
        description="Optional Kind 0 provider profile publishing settings",
    )
    trusted_provider_list: TrustedProviderListConfig = Field(
        default_factory=TrustedProviderListConfig,
        description="Optional Kind 10040 trusted-provider list publishing settings",
    )

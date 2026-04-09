"""Assertor service configuration models.

See Also:
    [Assertor][bigbrotr.services.assertor.Assertor]: The service class
        that consumes these configurations.
    [BaseServiceConfig][bigbrotr.core.base_service.BaseServiceConfig]:
        Base class providing ``interval``, ``max_consecutive_failures``,
        and ``metrics`` fields.
    [KeysConfig][bigbrotr.utils.keys.KeysConfig]: Mixin providing
        Nostr key management fields.
"""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, field_validator

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.models import Relay
from bigbrotr.models.constants import EventKind
from bigbrotr.utils.keys import KeysConfig


_SUPPORTED_KINDS = frozenset({EventKind.NIP85_USER_ASSERTION, EventKind.NIP85_EVENT_ASSERTION})
_ALGORITHM_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_DEFAULT_ALGORITHM_ID = "global-pagerank-v1"


class ProviderProfileKind0Content(BaseModel):
    """Kind 0 metadata content for the optional NIP-85 provider profile."""

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
    extra_fields: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict,
        description="Additional JSON metadata to merge into the Kind 0 content",
    )


class ProviderProfileConfig(BaseModel):
    """Optional Kind 0 metadata publishing for the NIP-85 service key."""

    enabled: bool = Field(
        default=False,
        description="Enable Kind 0 provider profile publishing for the service key",
    )
    kind0_content: ProviderProfileKind0Content = Field(
        default_factory=ProviderProfileKind0Content,
        description="Kind 0 metadata content for the provider profile",
    )


class AssertorConfig(BaseServiceConfig, KeysConfig):
    """Configuration for the Assertor service.

    Inherits key management from
    [KeysConfig][bigbrotr.utils.keys.KeysConfig] for Nostr signing.

    Note:
        Uses the same ``NOSTR_PRIVATE_KEY`` environment variable as other
        publishing services (Monitor, DVM) by default. Override ``keys_env``
        to use a dedicated signing identity per algorithm.

    Attributes:
        algorithm_id: Stable identifier of the ranking/assertion algorithm.
        relays: Relay URLs to publish assertions to.
        kinds: NIP-85 assertion kinds to publish.
        batch_size: Maximum pubkeys/events to process per cycle.
        min_events: Minimum event count for a pubkey to qualify for assertion.
        top_topics: Number of topic tags to include per user assertion.
        provider_profile: Optional Kind 0 profile metadata for the service key.
        allow_insecure: Allow insecure SSL connections to relays.
    """

    algorithm_id: str = Field(
        default=_DEFAULT_ALGORITHM_ID,
        min_length=1,
        max_length=128,
        description="Stable identifier for the assertion algorithm/service key namespace",
    )

    relays: Annotated[
        list[Relay],
        BeforeValidator(lambda v: [Relay(url) if isinstance(url, str) else url for url in v]),
    ] = Field(
        default_factory=lambda: [
            Relay("wss://relay.damus.io"),
            Relay("wss://nos.lol"),
            Relay("wss://relay.primal.net"),
        ],
        min_length=1,
        description="Relay URLs to publish assertions to",
    )

    kinds: list[int] = Field(
        default_factory=lambda: [30382, 30383],
        min_length=1,
        description="NIP-85 assertion kinds to publish (30382=user, 30383=event)",
    )

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

    @field_validator("algorithm_id")
    @classmethod
    def algorithm_id_valid(cls, v: str) -> str:
        if not _ALGORITHM_ID_PATTERN.fullmatch(v):
            raise ValueError(
                "algorithm_id must match [a-z0-9]+(?:[._-][a-z0-9]+)* "
                "(lowercase letters, digits, '.', '_' and '-')"
            )
        return v

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

    interval: float = Field(
        default=3600.0,
        ge=60.0,
        description="Target seconds between assertion cycles",
    )

    allow_insecure: bool = Field(
        default=False,
        description="Allow insecure SSL connections to relays",
    )

    provider_profile: ProviderProfileConfig = Field(
        default_factory=ProviderProfileConfig,
        description="Optional Kind 0 provider profile publishing settings",
    )

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

from typing import Annotated

from pydantic import BeforeValidator, Field

from bigbrotr.core.base_service import BaseServiceConfig
from bigbrotr.models import Relay
from bigbrotr.utils.keys import KeysConfig


class AssertorConfig(BaseServiceConfig, KeysConfig):
    """Configuration for the Assertor service.

    Inherits key management from
    [KeysConfig][bigbrotr.utils.keys.KeysConfig] for Nostr signing.

    Note:
        Uses the same ``NOSTR_PRIVATE_KEY`` environment variable as other
        publishing services (Monitor, DVM) by default. Override ``keys_env``
        to use a dedicated signing identity if required.

    Attributes:
        relays: Relay URLs to publish assertions to.
        kinds: NIP-85 assertion kinds to publish.
        batch_size: Maximum pubkeys/events to process per cycle.
        min_events: Minimum event count for a pubkey to qualify for assertion.
        top_topics: Number of topic tags to include per user assertion.
        allow_insecure: Allow insecure SSL connections to relays.
    """

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
